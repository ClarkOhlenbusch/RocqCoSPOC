"""
Thin client for Open Router chat completions.
Loads OPENROUTER_API_KEY from environment (.env when available).
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    raise

# Load .env from repo root if python-dotenv is available
def _load_dotenv():
    try:
        import dotenv
        repo_root = Path(__file__).resolve().parent.parent
        env_path = repo_root / ".env"
        if env_path.exists():
            dotenv.load_dotenv(env_path)
    except ImportError:
        pass

_load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_TIMEOUT = 120
DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_SEC = 1.5
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_MAX_BACKOFF_SEC = 20.0
DEFAULT_JITTER_SEC = 0.35


def _extract_message_text(content) -> str:
    """Handle string or structured message content payloads."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    chunks.append(str(item["text"]))
                elif item.get("content"):
                    chunks.append(str(item["content"]))
            elif isinstance(item, str):
                chunks.append(item)
        return "\n".join(chunks).strip()
    if content is None:
        return ""
    return str(content).strip()


def _payload_prompt_text(payload: dict) -> str:
    messages = payload.get("messages") or []
    rendered: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "user")).strip() or "user"
        content = _extract_message_text(msg.get("content"))
        rendered.append(f"[{role}]\n{content}".strip())
    return "\n\n".join(part for part in rendered if part).strip()


def _append_model_log(log_path: Optional[Path], entry: dict) -> None:
    if not log_path:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _parse_retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = float(value)
        return parsed if parsed >= 0 else None
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def _compute_backoff_seconds(
    attempt: int,
    *,
    base_delay: float,
    multiplier: float,
    max_delay: float,
    jitter: float,
) -> float:
    delay = min(max_delay, base_delay * (multiplier ** attempt))
    if jitter > 0:
        delay += random.uniform(0.0, jitter)
    return max(0.0, delay)


def _request_chat(
    payload: dict,
    headers: dict,
    timeout: int,
    retries: int,
    *,
    backoff_base_sec: float,
    backoff_multiplier: float,
    backoff_max_sec: float,
    backoff_jitter_sec: float,
    log_path: Optional[Path] = None,
    log_context: Optional[dict] = None,
):
    last_error = None
    for attempt in range(retries + 1):
        request_started_at = datetime.now(timezone.utc).isoformat()
        try:
            resp = requests.post(
                OPENROUTER_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            last_error = e
            sleep_for = None
            if attempt < retries:
                sleep_for = _compute_backoff_seconds(
                    attempt,
                    base_delay=backoff_base_sec,
                    multiplier=backoff_multiplier,
                    max_delay=backoff_max_sec,
                    jitter=backoff_jitter_sec,
                )
            _append_model_log(
                log_path,
                {
                    "timestamp": request_started_at,
                    "status": "request_exception",
                    "attempt": attempt + 1,
                    "model": payload.get("model"),
                    "timeout_sec": timeout,
                    "error": str(e),
                    "prompt_text": _payload_prompt_text(payload),
                    "prompt_preview": str(payload.get("messages", [{}])[0].get("content", ""))[:800],
                    "retry_sleep_sec": sleep_for,
                    "metadata": log_context or {},
                },
            )
            if attempt >= retries:
                raise RuntimeError(f"Open Router request failed: {e}") from e
            time.sleep(sleep_for)
            continue

        request_id = resp.headers.get("x-request-id") or resp.headers.get("request-id")
        retry_after = _parse_retry_after_seconds(resp.headers.get("retry-after"))
        body_text = resp.text
        _append_model_log(
            log_path,
            {
                "timestamp": request_started_at,
                "status": "http_response",
                "attempt": attempt + 1,
                "model": payload.get("model"),
                "timeout_sec": timeout,
                "status_code": resp.status_code,
                "request_id": request_id,
                "retry_after_sec": retry_after,
                "raw_response": body_text,
                "prompt_text": _payload_prompt_text(payload),
                "prompt_preview": str(payload.get("messages", [{}])[0].get("content", ""))[:800],
                "metadata": log_context or {},
            },
        )
        if resp.ok:
            return resp

        body = body_text
        try:
            j = resp.json()
            body = j.get("error", {}).get("message", body) or body
        except Exception:
            pass
        rid_part = f" [request-id: {request_id}]" if request_id else ""

        # Retry common transient statuses.
        if resp.status_code in (408, 409, 425, 429, 500, 502, 503, 504) and attempt < retries:
            sleep_for = retry_after
            if sleep_for is None:
                sleep_for = _compute_backoff_seconds(
                    attempt,
                    base_delay=backoff_base_sec,
                    multiplier=backoff_multiplier,
                    max_delay=backoff_max_sec,
                    jitter=backoff_jitter_sec,
                )
            time.sleep(sleep_for)
            continue

        raise RuntimeError(
            f"Open Router API error {resp.status_code}{rid_part}: {body}"
        )

    if last_error:
        raise RuntimeError(f"Open Router request failed: {last_error}") from last_error
    raise RuntimeError("Open Router request failed for unknown reason")


def get_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env in the repo root or export it."
        )
    return key


def chat(
    model: str,
    user_content: str,
    *,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_base_sec: float = DEFAULT_BACKOFF_SEC,
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    backoff_max_sec: float = DEFAULT_MAX_BACKOFF_SEC,
    backoff_jitter_sec: float = DEFAULT_JITTER_SEC,
    log_path: Optional[Path] = None,
    metadata: Optional[dict] = None,
) -> str:
    """
    Send a single user message to Open Router and return the assistant message text.
    Raises on non-2xx or timeout.
    """
    key = get_api_key()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/RocqCoSPOC",
    }
    resp = _request_chat(
        payload,
        headers,
        timeout,
        retries=retries,
        backoff_base_sec=backoff_base_sec,
        backoff_multiplier=backoff_multiplier,
        backoff_max_sec=backoff_max_sec,
        backoff_jitter_sec=backoff_jitter_sec,
        log_path=log_path,
        log_context=metadata,
    )
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Open Router returned no choices")
    msg = choices[0].get("message") or {}
    text = _extract_message_text(msg.get("content"))
    if not text:
        # Some providers return text in a top-level field.
        text = _extract_message_text(choices[0].get("text"))
    if not text:
        # Some reasoning-capable models return only reasoning text.
        text = _extract_message_text(msg.get("reasoning"))
    if not text:
        raise RuntimeError("Open Router returned an empty message")
    return text


def chat_raw(
    model: str,
    user_content: str,
    *,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_base_sec: float = DEFAULT_BACKOFF_SEC,
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    backoff_max_sec: float = DEFAULT_MAX_BACKOFF_SEC,
    backoff_jitter_sec: float = DEFAULT_JITTER_SEC,
    log_path: Optional[Path] = None,
    metadata: Optional[dict] = None,
):
    """Same as chat() but returns the full JSON response for debugging."""
    key = get_api_key()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/RocqCoSPOC",
    }
    resp = _request_chat(
        payload,
        headers,
        timeout,
        retries=retries,
        backoff_base_sec=backoff_base_sec,
        backoff_multiplier=backoff_multiplier,
        backoff_max_sec=backoff_max_sec,
        backoff_jitter_sec=backoff_jitter_sec,
        log_path=log_path,
        log_context=metadata,
    )
    return resp.json()
