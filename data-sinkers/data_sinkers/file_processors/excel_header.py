"""Excel header detection: LLM by default (EXCEL_HEADER_LLM=true), heuristic fallback."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from ..llm_config import llm_request_timeout_seconds
from ..llm_invoke_retry import invoke_llm_with_json_retry
from ..llm_output_json import parse_llm_output_string

logger = logging.getLogger("ExcelHeader")

_HEADER_LLM: Any = None
_HEADER_RESOLUTION_CACHE: Dict[str, HeaderResolution] = {}
_LAST_HEADER_RESOLUTION: Optional[HeaderResolution] = None


@dataclass
class HeaderResolution:
    data_start: int
    column_names: List[str]
    method: str  # heuristic | llm | heuristic_fallback


def _cell_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _is_blank_row(row: pd.Series) -> bool:
    return all(not _cell_text(value) for value in row)


def skip_leading_empty_rows(df: pd.DataFrame) -> pd.DataFrame:
    start = 0
    while start < len(df) and _is_blank_row(df.iloc[start]):
        start += 1
    return df.iloc[start:]


def _is_numeric_like(text: str) -> bool:
    if not text:
        return False
    try:
        float(text.replace(",", ""))
        return True
    except ValueError:
        return False


def _numeric_fraction(row: pd.Series) -> float:
    cells = [_cell_text(v) for v in row if _cell_text(v)]
    if not cells:
        return 0.0
    return sum(1 for cell in cells if _is_numeric_like(cell)) / len(cells)


def _is_title_like_row(row: pd.Series) -> bool:
    cells = [_cell_text(v) for v in row if _cell_text(v)]
    return len(cells) == 1 and len(cells[0]) > 15


def _has_mixed_alpha_and_digit(text: str) -> bool:
    return any(ch.isalpha() for ch in text) and any(ch.isdigit() for ch in text)


def _is_label_header_row(row: pd.Series) -> bool:
    cells = [_cell_text(v) for v in row if _cell_text(v)]
    if len(cells) < 2:
        return False

    numeric_fraction = _numeric_fraction(row)
    avg_len = sum(len(cell) for cell in cells) / len(cells)
    if numeric_fraction >= 0.3 or avg_len > 20:
        return False

    mixed_code_cells = sum(1 for cell in cells if _has_mixed_alpha_and_digit(cell))
    if mixed_code_cells >= max(1, len(cells) // 2):
        return True

    return avg_len >= 3


def _is_data_like_row(row: pd.Series, data_numeric_baseline: float) -> bool:
    if _is_title_like_row(row) or _is_label_header_row(row):
        return False

    numeric_fraction = _numeric_fraction(row)
    if numeric_fraction >= max(0.2, data_numeric_baseline - 0.05):
        return True

    cells = [_cell_text(v) for v in row if _cell_text(v)]
    if len(cells) >= 2 and numeric_fraction > 0.1 and any(len(cell) > 10 for cell in cells):
        return True

    if (
        len(cells) >= 2
        and numeric_fraction < 0.1
        and all(len(cell) <= 2 for cell in cells)
        and not any(_has_mixed_alpha_and_digit(cell) for cell in cells)
    ):
        return True

    return False


def _row_header_likelihood(row: pd.Series, data_numeric_baseline: float) -> float:
    cells = [_cell_text(v) for v in row if _cell_text(v)]
    if not cells:
        return 0.0

    if _is_title_like_row(row):
        return 0.1

    numeric_fraction = _numeric_fraction(row)
    avg_len = sum(len(cell) for cell in cells) / len(cells)

    length_score = max(0.0, 1.0 - avg_len / 30.0)
    numeric_score = max(0.0, data_numeric_baseline - numeric_fraction)
    return (length_score + numeric_score) / 2.0


def _first_col_index(value) -> Optional[int]:
    text = _cell_text(value)
    if text.isdigit():
        return int(text)
    return None


def _data_numeric_baseline(df: pd.DataFrame) -> float:
    fractions = [
        _numeric_fraction(df.iloc[i])
        for i in range(len(df))
        if not _is_blank_row(df.iloc[i])
    ]
    if not fractions:
        return 0.0
    tail = fractions[len(fractions) // 2:]
    return sorted(tail)[len(tail) // 2]


def _count_leading_header_rows(df: pd.DataFrame, data_numeric_baseline: float) -> int:
    count = 0
    for i in range(len(df)):
        row = df.iloc[i]
        if _is_blank_row(row):
            continue
        if _is_data_like_row(row, data_numeric_baseline):
            break
        is_header_row = (
            _is_title_like_row(row)
            or _is_label_header_row(row)
            or _row_header_likelihood(row, data_numeric_baseline) > 0.15
        )
        if is_header_row:
            count = i + 1
        else:
            break
    return count


def _find_sequential_data_start(df: pd.DataFrame, min_run: int = 2) -> Optional[int]:
    best_start: Optional[int] = None
    best_run = 0
    run_start: Optional[int] = None
    run_len = 0
    prev_idx: Optional[int] = None

    def close_run() -> None:
        nonlocal best_start, best_run, run_start, run_len, prev_idx
        if run_len > best_run:
            best_run = run_len
            best_start = run_start
        run_start = None
        run_len = 0
        prev_idx = None

    for i in range(len(df)):
        idx = _first_col_index(df.iloc[i, 0])
        if idx is None:
            close_run()
            continue

        if run_start is None:
            run_start = i
            run_len = 1
            prev_idx = idx
            continue

        if idx == prev_idx + 1:
            run_len += 1
            prev_idx = idx
        else:
            close_run()
            run_start = i
            run_len = 1
            prev_idx = idx

    close_run()
    if best_start is not None and best_run >= min_run:
        return best_start
    return None


def auto_detect_data_start_row(df: pd.DataFrame) -> int:
    if len(df) == 0:
        return 0

    data_numeric_baseline = _data_numeric_baseline(df)
    sequential_start = _find_sequential_data_start(df)
    leading_header_rows = _count_leading_header_rows(df, data_numeric_baseline)

    if sequential_start is not None and leading_header_rows > 0:
        if sequential_start <= leading_header_rows:
            return sequential_start
        if sequential_start == leading_header_rows + 1:
            return sequential_start

    if leading_header_rows > 0 and leading_header_rows < len(df):
        return leading_header_rows

    if sequential_start is not None:
        return sequential_start

    if len(df) > 1:
        return 1

    return 0


def build_column_names(header_rows_df: pd.DataFrame) -> List[str]:
    level0 = header_rows_df.iloc[0].ffill()
    columns: List[str] = []
    seen: Dict[str, bool] = {}

    for col_idx in range(header_rows_df.shape[1]):
        parts: List[str] = []
        v0 = level0.iloc[col_idx]
        if pd.notna(v0) and str(v0).strip():
            parts.append(str(v0).strip())

        for row_idx in range(1, len(header_rows_df)):
            value = header_rows_df.iloc[row_idx, col_idx]
            if pd.notna(value) and str(value).strip():
                part = str(value).strip()
                if part not in parts:
                    parts.append(part)

        col_name = " / ".join(parts) if parts else f"column_{col_idx}"
        if col_name in seen:
            col_name = f"{col_name}_{col_idx}"
        seen[col_name] = True
        columns.append(col_name)

    return columns


def _header_llm_enabled() -> bool:
    """Default true: use LLM for header detection unless explicitly disabled."""
    flag = os.getenv("EXCEL_HEADER_LLM", "true").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _header_llm_credentials_available() -> bool:
    return bool(os.getenv("API_KEY"))


def _preview_row_limit() -> int:
    raw = os.getenv("EXCEL_HEADER_PREVIEW_ROWS", "12")
    try:
        return max(4, int(raw))
    except (TypeError, ValueError):
        return 12


def _log_llm_text(label: str, text: str) -> None:
    logger.info("[excel_header_llm] %s:\n%s", label, text)


def _get_header_llm() -> Any:
    global _HEADER_LLM
    if _HEADER_LLM is None:
        from model_sdk import ModelManager

        manager = ModelManager()
        _HEADER_LLM = manager.get_llm(
            provider=os.getenv("PROVIDER", "openai_compatible"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
            model=os.getenv("Model"),
            temperature=0.01,
            timeout=llm_request_timeout_seconds(),
            extra_body={"enable_thinking": False},
        )
    return _HEADER_LLM


def _normalize_column_names(names: List[str], col_count: int) -> List[str]:
    cleaned = [str(n).strip() for n in names if str(n).strip()]
    if len(cleaned) >= col_count:
        return cleaned[:col_count]
    result = list(cleaned)
    for idx in range(len(result), col_count):
        result.append(f"column_{idx}")
    return result


def _heuristic_confident(raw_df: pd.DataFrame, data_start: int, column_names: List[str]) -> bool:
    if data_start <= 0 or data_start >= len(raw_df):
        return False
    if not column_names:
        return False
    if len(raw_df) - data_start < 1:
        return False

    generic_ratio = sum(1 for name in column_names if name.startswith("column_")) / max(
        len(column_names), 1
    )
    if generic_ratio > 0.4:
        return False

    if generic_ratio <= 0.15:
        return True

    baseline = _data_numeric_baseline(raw_df)
    first_data = raw_df.iloc[data_start]
    if _is_label_header_row(first_data) and not _is_data_like_row(first_data, baseline):
        return False

    return True


def _build_preview_text(raw_df: pd.DataFrame, max_rows: int) -> str:
    lines: List[str] = []
    for row_idx in range(min(max_rows, len(raw_df))):
        row = raw_df.iloc[row_idx]
        if _is_blank_row(row):
            continue
        cells: List[str] = []
        for col_idx in range(raw_df.shape[1]):
            text = _cell_text(row.iloc[col_idx])
            cells.append(f"C{col_idx}={text}" if text else f"C{col_idx}=")
        lines.append(f"Row{row_idx}: " + " | ".join(cells))
    return "\n".join(lines)


def _response_text(response: Any) -> str:
    return response.content if hasattr(response, "content") else str(response)


def _parse_llm_response(response: Any) -> Dict[str, Any]:
    content = _response_text(response)
    parsed = parse_llm_output_string(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM output is not a JSON object")
    return parsed


def _validate_llm_header(parsed: Any, raw_df: pd.DataFrame) -> Optional[str]:
    if not isinstance(parsed, dict):
        return "expected object"

    header_row_count = parsed.get("header_row_count")
    column_names = parsed.get("column_names")

    if not isinstance(header_row_count, int):
        try:
            header_row_count = int(header_row_count)
        except (TypeError, ValueError):
            return "header_row_count must be int"

    if header_row_count <= 0 or header_row_count >= len(raw_df):
        return f"header_row_count out of range: {header_row_count}"

    if not isinstance(column_names, list) or not column_names:
        return "column_names must be a non-empty list"

    stripped = [str(n).strip() for n in column_names]
    if len(stripped) != raw_df.shape[1]:
        return f"column_names length {len(stripped)} != column count {raw_df.shape[1]}"
    if not all(stripped):
        return "column_names must all be non-empty"

    return None


def _detect_header_with_llm(raw_df: pd.DataFrame, file_label: str) -> Optional[HeaderResolution]:
    preview = _build_preview_text(raw_df, _preview_row_limit())
    if not preview:
        logger.warning("[excel_header_llm] empty preview for %s, skip LLM", file_label)
        return None

    logger.info(
        "[excel_header_llm] start file=%s rows=%d cols=%d preview_rows=%d",
        file_label,
        len(raw_df),
        raw_df.shape[1],
        _preview_row_limit(),
    )
    logger.info(
        "[excel_header_llm] model=%s provider=%s base_url=%s",
        os.getenv("Model", ""),
        os.getenv("PROVIDER", "openai_compatible"),
        os.getenv("BASE_URL", ""),
    )
    _log_llm_text("preview sent to LLM", preview)

    system = SystemMessage(
        content=(
            "You analyze spreadsheet previews and identify table headers.\n"
            "Return ONLY a JSON object with:\n"
            "- header_row_count: number of leading rows that are headers/titles (not data), "
            "counting from Row0 after blank rows were removed.\n"
            "- column_names: final field name for each column C0..Cn-1; "
            "length MUST equal Total columns (include columns with sparse/empty header cells). "
            "For multi-level headers use 'parent / child'. "
            "For duplicate semantics append _columnIndex like name_3.\n"
            "Do not include markdown or explanation."
        )
    )
    human = HumanMessage(
        content=(
            f"File: {file_label}\n"
            f"Total columns: {raw_df.shape[1]}\n"
            f"Preview rows:\n{preview}\n"
            f"Identify header_row_count and column_names (exactly one name per column C0..C{raw_df.shape[1] - 1})."
        )
    )

    def validate(parsed: Any) -> Optional[str]:
        return _validate_llm_header(parsed, raw_df)

    last_raw_response: Optional[str] = None

    def parse_and_log(response: Any) -> Dict[str, Any]:
        nonlocal last_raw_response
        last_raw_response = _response_text(response)
        _log_llm_text("raw LLM response", last_raw_response)
        parsed = _parse_llm_response(response)
        logger.info(
            "[excel_header_llm] parsed header_row_count=%s column_names_len=%s column_names=%s",
            parsed.get("header_row_count"),
            len(parsed.get("column_names", [])) if isinstance(parsed.get("column_names"), list) else 0,
            parsed.get("column_names"),
        )
        return parsed

    parsed = invoke_llm_with_json_retry(
        _get_header_llm(),
        [system, human],
        parse_and_log,
        validate=validate,
        label="excel_header_llm",
    )
    if not parsed:
        logger.error("[excel_header_llm] failed for %s after retries", file_label)
        return None

    data_start = int(parsed["header_row_count"])
    column_names = _normalize_column_names(
        [str(n) for n in parsed["column_names"]],
        raw_df.shape[1],
    )
    if any(name.startswith("column_") for name in column_names):
        logger.warning(
            "[excel_header_llm] placeholder column names for %s after normalize, treat as failure",
            file_label,
        )
        return None
    logger.info(
        "[excel_header_llm] success file=%s header_row_count=%d column_count=%d column_names=%s",
        file_label,
        data_start,
        len(column_names),
        column_names,
    )
    return HeaderResolution(data_start=data_start, column_names=column_names, method="llm")


def _header_cache_key(raw_df: pd.DataFrame) -> str:
    preview = _build_preview_text(raw_df, _preview_row_limit())
    return f"{raw_df.shape[0]}x{raw_df.shape[1]}:{hash(preview)}"


def get_last_header_resolution() -> Optional[HeaderResolution]:
    return _LAST_HEADER_RESOLUTION


def _dedupe_column_names(column_names: List[str]) -> List[str]:
    seen: Dict[str, bool] = {}
    result: List[str] = []
    for col_idx, name in enumerate(column_names):
        final_name = name
        if final_name in seen:
            final_name = f"{final_name}_{col_idx}"
        seen[final_name] = True
        result.append(final_name)
    return result


def resolve_excel_header(raw_df: pd.DataFrame, file_label: str) -> Optional[HeaderResolution]:
    """Resolve headers via LLM by default (EXCEL_HEADER_LLM=true); heuristic on failure or opt-out."""
    global _LAST_HEADER_RESOLUTION

    if len(raw_df) == 0:
        return None

    cache_key = _header_cache_key(raw_df)
    cached = _HEADER_RESOLUTION_CACHE.get(cache_key)
    if cached is not None:
        logger.info(
            "Header resolution cache hit for %s (same sheet preview as prior call)",
            file_label,
        )
        _LAST_HEADER_RESOLUTION = cached
        return cached

    data_start = auto_detect_data_start_row(raw_df)
    column_names = (
        build_column_names(raw_df.iloc[:data_start])
        if data_start > 0 and data_start < len(raw_df)
        else []
    )

    logger.info(
        "Heuristic baseline for %s: data_start=%d column_names=%s",
        file_label,
        data_start,
        column_names,
    )

    if _header_llm_enabled():
        if not _header_llm_credentials_available():
            logger.warning(
                "EXCEL_HEADER_LLM is enabled (default=true) but API_KEY is unset; "
                "using heuristic header detection for %s",
                file_label,
            )
        else:
            llm_result = _detect_header_with_llm(raw_df, file_label)
            if llm_result:
                llm_result.column_names = _dedupe_column_names(llm_result.column_names)
                logger.info(
                    "Header resolved via LLM: %d row(s), %d columns (%s) column_names=%s",
                    llm_result.data_start,
                    len(llm_result.column_names),
                    file_label,
                    llm_result.column_names,
                )
                _HEADER_RESOLUTION_CACHE[cache_key] = llm_result
                _LAST_HEADER_RESOLUTION = llm_result
                return llm_result
            logger.warning(
                "LLM header detection failed for %s, falling back to heuristic",
                file_label,
            )

    if _heuristic_confident(raw_df, data_start, column_names):
        logger.info(
            "Header resolved via heuristic: %d row(s), %d columns (%s) column_names=%s",
            data_start,
            len(column_names),
            file_label,
            column_names,
        )
        result = HeaderResolution(
            data_start=data_start,
            column_names=column_names,
            method="heuristic",
        )
        _HEADER_RESOLUTION_CACHE[cache_key] = result
        _LAST_HEADER_RESOLUTION = result
        return result

    logger.warning(
        "Heuristic header uncertain for %s (data_start=%d, columns=%d)",
        file_label,
        data_start,
        len(column_names),
    )

    if data_start <= 0 or data_start >= len(raw_df):
        return None

    if not column_names:
        column_names = build_column_names(raw_df.iloc[:data_start])

    result = HeaderResolution(
        data_start=data_start,
        column_names=column_names,
        method="heuristic_fallback",
    )
    _HEADER_RESOLUTION_CACHE[cache_key] = result
    _LAST_HEADER_RESOLUTION = result
    return result
