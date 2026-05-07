"""
Shared LLM JSON parsing: markdown cleanup, json_repair, ast fallback, and single-key extract.
"""
import ast
import json
import logging
import re
from typing import Any, Optional

from json_repair import repair_json as _json_repair

logger = logging.getLogger("llm_output_json")


def _extract_single_key_json(text: str) -> Optional[dict]:
    """
    Fallback: extract all simple string-valued keys from the JSON block.
    Uses non-greedy matching so one key's value doesn't bleed into the next.
    """
    if not text:
        return None
    # Non-greedy match stops at the first unescaped closing quote.
    pairs = re.findall(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if pairs:
        result = dict(pairs)
        logger.info(
            " === format_llm_output, fallback extraction succeeded for keys "
            "%s",
            list(result.keys()),
        )
        return result
    return None


def _extract_json_block(text: str) -> str:
    """
    Extract the first balanced {...} block from text that may have Chinese
    explanation text before or after the JSON.  Returns the original text
    unchanged when no '{' is found so callers still see a meaningful error.
    """
    start = text.find('{')
    if start == -1:
        return text
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def _strip_code_fence_and_normalize_quotes(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')
    cleaned = cleaned.replace("\u2018", "'").replace("\u2019", "'")
    # Normalize Chinese full-width punctuation that LLMs sometimes use in JSON
    # structural positions (e.g. \uff08 where , is expected).
    cleaned = cleaned.replace("\uff08", "(").replace("\uff09", ")")  # \uff08\uff09
    cleaned = cleaned.replace("\uff0c", ",")                          # \uff0c
    cleaned = cleaned.replace("\uff1a", ":")                          # \uff1a
    cleaned = cleaned.replace("\uff3b", "[").replace("\uff3d", "]")  # \uff3b\uff3d
    cleaned = cleaned.replace("\u3010", "[").replace("\u3011", "]")  # \u3010\u3011
    cleaned = _extract_json_block(cleaned)
    return cleaned


def _try_json_repair(cleaned: str) -> Any:
    """Parse via json_repair; returns a Python object on success, else None."""
    if not cleaned or not cleaned.strip():
        return None
    try:
        out = _json_repair(cleaned, return_objects=True, skip_json_loads=True)
    except Exception as e:
        logger.error(" === format_llm_output, json_repair (return_objects) failed: %s", e)
        return None
    if out is None:
        return None
    if isinstance(out, str) and not out.strip():
        return None
    if isinstance(out, (dict, list)):
        return out
    if isinstance(out, (str, int, float, bool)):
        return out
    return None


def _try_json_repair_as_string(cleaned: str) -> Any:
    """If return_objects did not work, try repaired JSON string + json.loads."""
    try:
        fixed = _json_repair(cleaned, skip_json_loads=True)
    except Exception as e:
        logger.error(" === format_llm_output, json_repair (string) failed: %s", e)
        return None
    if not isinstance(fixed, str) or not fixed.strip():
        return None
    try:
        return json.loads(fixed, strict=False)
    except json.JSONDecodeError as e:
        logger.error(" === format_llm_output, json.loads after json_repair string failed: %s", e)
        return None


def parse_llm_output_string(
    content: str,
    *,
    use_single_key_fallback: bool = True,
) -> Any:
    """
    Parse model output to a Python value (dict/list/...) using json.loads, cleanup,
    json_repair, ast.literal_eval, single-quote fix, and optional single-key regex.
    """
    if content is None:
        return None

    # 1) Direct JSON (strict=False to tolerate control chars in LLM output)
    try:
        return json.loads(content, strict=False)
    except json.JSONDecodeError:
        pass

    cleaned = _strip_code_fence_and_normalize_quotes(content)

    # 2) After markdown / smart-quote cleanup
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError as e2:
        logger.error(" === format_llm_output, Parsing failed after cleanup.: %s", e2)

    # 3) json_repair
    data_dict = _try_json_repair(cleaned)
    if data_dict is not None:
        return data_dict
    data_dict = _try_json_repair_as_string(cleaned)
    if data_dict is not None:
        return data_dict

    # 4) Python literal
    try:
        return ast.literal_eval(cleaned)
    except (ValueError, SyntaxError) as e3:
        logger.error(" === format_llm_output, ast parsing fail: %s", e3)
    except Exception as e5:
        logger.error(" === format_llm_output, exception occurred during ast parse: %s", e5)

    # 5) Single quotes to double
    try:
        return json.loads(cleaned.replace("'", '"'), strict=False)
    except json.JSONDecodeError as e4:
        logger.error(
            " === format_llm_output, secondary parsing failed: %s, using default value",
            e4,
        )

    if use_single_key_fallback:
        return _extract_single_key_json(cleaned)

    return None
