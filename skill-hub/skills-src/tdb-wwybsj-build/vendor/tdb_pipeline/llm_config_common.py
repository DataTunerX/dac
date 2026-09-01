"""Shared LLM config loading for pipeline scripts.

Precedence:
1. Built-in defaults keep local smoke tests runnable.
2. dac.json provides checked-in defaults.
3. Environment variables override both, so deploy/runtime config wins.

Do not map the app-level LLM_PROVIDER here. The pipeline calls an
OpenAI-compatible /chat/completions endpoint, even when the upstream model is
Gemma/Gemini-style behind a proxy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_LLM_CONFIG: dict[str, Any] = {
    "provider": "openai_compatible",
    "baseUrl": "http://10.124.48.200:8000/v1",
    "model": "google/gemma-4-31B-it",
    "apiKey": "",
    "timeoutSeconds": 300,
    "maxRetries": 3,
    "temperature": 0.0,
    "tokenParameter": "auto",
}

TOKEN_PARAMETERS = {"auto", "max_tokens", "max_completion_tokens"}
TEMPERATURE_POLICIES = {"auto", "default", "none"}


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _env_int(*names: str) -> int | None:
    value = _first_env(*names)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        joined = " / ".join(names)
        raise ValueError(f"{joined} must be an integer, got {value!r}") from exc


def _env_float(*names: str) -> float | None:
    value = _first_env(*names)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError as exc:
        joined = " / ".join(names)
        raise ValueError(f"{joined} must be a number, got {value!r}") from exc


def _env_temperature(*names: str) -> float | str | None:
    value = _first_env(*names)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in TEMPERATURE_POLICIES:
        return normalized
    try:
        temperature = float(value)
    except ValueError as exc:
        joined = " / ".join(names)
        raise ValueError(
            f"{joined} must be auto, default, none, or a number between 0 and 2; got {value!r}"
        ) from exc
    if not 0 <= temperature <= 2:
        joined = " / ".join(names)
        raise ValueError(f"{joined} must be between 0 and 2, got {value!r}")
    return temperature


def is_official_openai_endpoint(base_url: str) -> bool:
    hostname = (urlparse(base_url).hostname or "").lower()
    return hostname == "api.openai.com" or hostname.endswith(".api.openai.com")


def resolve_chat_token_parameter(cfg: dict[str, Any]) -> str:
    configured = str(
        cfg.get("tokenParameter", cfg.get("token_parameter", "auto"))
    ).strip().lower()
    if configured not in TOKEN_PARAMETERS:
        raise ValueError(
            "LLM token parameter must be auto, max_tokens, or max_completion_tokens; "
            f"got {configured!r}"
        )
    if configured != "auto":
        return configured
    base_url = str(cfg.get("baseUrl", cfg.get("base_url", "")))
    return "max_completion_tokens" if is_official_openai_endpoint(base_url) else "max_tokens"


def resolve_chat_temperature(
    cfg: dict[str, Any],
    *,
    default_temperature: float = 0.0,
) -> float | None:
    value = cfg.get("temperature", default_temperature)
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "auto":
            base_url = str(cfg.get("baseUrl", cfg.get("base_url", "")))
            return None if is_official_openai_endpoint(base_url) else default_temperature
        if normalized in {"", "default", "none"}:
            return None
        try:
            value = float(normalized)
        except ValueError as exc:
            raise ValueError(
                "LLM temperature must be auto, default, none, or a number between 0 and 2; "
                f"got {value!r}"
            ) from exc
    temperature = float(value)
    if not 0 <= temperature <= 2:
        raise ValueError(f"LLM temperature must be between 0 and 2, got {temperature!r}")
    return temperature


def build_chat_completions_payload(
    messages: list[dict[str, Any]],
    cfg: dict[str, Any],
    *,
    default_max_tokens: int = 4096,
    default_temperature: float = 0.0,
) -> dict[str, Any]:
    max_tokens = int(cfg.get("maxTokens", cfg.get("max_tokens", default_max_tokens)))
    if max_tokens < 1:
        raise ValueError("LLM max tokens must be positive")
    payload: dict[str, Any] = {
        "model": cfg.get("model", "google/gemma-4-31B-it"),
        "messages": messages,
        resolve_chat_token_parameter(cfg): max_tokens,
    }
    temperature = resolve_chat_temperature(
        cfg,
        default_temperature=default_temperature,
    )
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


def load_llm_config(
    dac_json_path: Path | str | None = None,
    *,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load LLM config from defaults, dac.json, then environment overrides."""
    cfg: dict[str, Any] = dict(defaults or DEFAULT_LLM_CONFIG)

    path: Path | None = None
    if dac_json_path is not None:
        path = Path(dac_json_path)
    else:
        env_path = _first_env("TDB_DAC_JSON")
        if env_path:
            path = Path(env_path)

    if path and path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        llm = data.get("llm", {})
        if isinstance(llm, dict):
            cfg.update(llm)

    provider = _first_env("TDB_LLM_PROVIDER", "PIPELINE_LLM_PROVIDER")
    if provider:
        cfg["provider"] = provider

    base_url = _first_env(
        "TDB_LLM_BASE_URL",
        "PIPELINE_LLM_BASE_URL",
        "LLM_BASE_URL",
        "GOOGLE_NIM_BASE_URL",
        "NVIDIA_NIM_BASE_URL",
        "OPENAI_BASE_URL",
    )
    if base_url:
        cfg["baseUrl"] = base_url

    model = _first_env("TDB_LLM_MODEL", "PIPELINE_LLM_MODEL", "LLM_CHAT_MODEL")
    if model:
        cfg["model"] = model

    api_key = _first_env(
        "TDB_LLM_API_KEY",
        "PIPELINE_LLM_API_KEY",
        "LLM_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
    )
    if api_key:
        cfg["apiKey"] = api_key

    timeout = _env_int("TDB_LLM_TIMEOUT_SECONDS", "PIPELINE_LLM_TIMEOUT_SECONDS", "LLM_TIMEOUT_SECONDS")
    if timeout is not None:
        cfg["timeoutSeconds"] = timeout

    retries = _env_int("TDB_LLM_MAX_RETRIES", "PIPELINE_LLM_MAX_RETRIES", "LLM_MAX_RETRIES")
    if retries is not None:
        cfg["maxRetries"] = retries

    max_tokens = _env_int("TDB_LLM_MAX_TOKENS", "PIPELINE_LLM_MAX_TOKENS", "LLM_MAX_TOKENS")
    if max_tokens is not None:
        cfg["maxTokens"] = max_tokens

    temperature = _env_temperature(
        "TDB_LLM_TEMPERATURE", "PIPELINE_LLM_TEMPERATURE", "LLM_TEMPERATURE"
    )
    if temperature is not None:
        cfg["temperature"] = temperature

    token_parameter = _first_env(
        "TDB_LLM_TOKEN_PARAMETER",
        "PIPELINE_LLM_TOKEN_PARAMETER",
        "LLM_TOKEN_PARAMETER",
    )
    if token_parameter:
        normalized_token_parameter = token_parameter.strip().lower()
        if normalized_token_parameter not in TOKEN_PARAMETERS:
            raise ValueError(
                "TDB_LLM_TOKEN_PARAMETER / PIPELINE_LLM_TOKEN_PARAMETER / "
                "LLM_TOKEN_PARAMETER must be auto, max_tokens, or max_completion_tokens; "
                f"got {token_parameter!r}"
            )
        cfg["tokenParameter"] = normalized_token_parameter

    parallel = _env_int("TDB_LLM_MAX_PARALLEL_CHUNKS", "PIPELINE_LLM_MAX_PARALLEL_CHUNKS")
    if parallel is not None:
        cfg["maxParallelChunks"] = parallel

    direct_parallel = _env_int(
        "TDB_LLM_DIRECT_WORKERS",
        "PIPELINE_LLM_DIRECT_WORKERS",
        "LLM_DIRECT_WORKERS",
    )
    if direct_parallel is not None:
        cfg["maxParallelDirectRelations"] = direct_parallel

    direct_batch_size = _env_int(
        "TDB_LLM_DIRECT_BATCH_SIZE",
        "PIPELINE_LLM_DIRECT_BATCH_SIZE",
        "LLM_DIRECT_BATCH_SIZE",
    )
    if direct_batch_size is not None:
        cfg["directRelationBatchSize"] = direct_batch_size

    workers = _env_int("TDB_GEMMAOCR_WORKERS", "PIPELINE_GEMMAOCR_WORKERS", "GEMMAOCR_WORKERS")
    if workers is not None:
        cfg["gemmaocr_workers"] = workers

    return cfg


def _official_openai_api(cfg: dict[str, Any]) -> bool:
    base_url = str(cfg.get("baseUrl", ""))
    host = urlparse(base_url).hostname or ""
    return host == "api.openai.com" or host.endswith(".api.openai.com")


def _requires_max_completion_tokens(cfg: dict[str, Any]) -> bool:
    model = str(cfg.get("model", "")).lower()
    if not _official_openai_api(cfg):
        return False
    return model.startswith(("gpt-5.4", "gpt-5.6"))


def apply_chat_completion_token_limit(
    payload: dict[str, Any],
    cfg: dict[str, Any],
    max_tokens: int,
) -> dict[str, Any]:
    """Set the right output-token key for the configured chat endpoint.

    Local vLLM and most OpenAI-compatible proxies still expect ``max_tokens``.
    Some official OpenAI models reject that key and require
    ``max_completion_tokens`` instead.
    """
    payload = dict(payload)
    key = "max_completion_tokens" if _requires_max_completion_tokens(cfg) else "max_tokens"
    payload.pop("max_tokens", None)
    payload.pop("max_completion_tokens", None)
    payload[key] = max_tokens
    return payload


def redacted_llm_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a log-safe copy of an LLM config."""
    safe = dict(cfg)
    if safe.get("apiKey"):
        safe["apiKey"] = "<set>"
    return safe
