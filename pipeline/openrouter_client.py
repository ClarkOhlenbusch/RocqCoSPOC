"""
Thin client for Open Router chat completions.
Loads OPENROUTER_API_KEY from environment (.env when available).
"""

import os
import sys
import time
from pathlib import Path

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


def _request_chat(payload: dict, headers: dict, timeout: int, retries: int):
    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                OPENROUTER_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        except requests.RequestException as e:
            last_error = e
            if attempt >= retries:
                raise RuntimeError(f"Open Router request failed: {e}") from e
            time.sleep(1.5 * (attempt + 1))
            continue

        if resp.ok:
            return resp

        body = resp.text
        try:
            j = resp.json()
            body = j.get("error", {}).get("message", body) or body
        except Exception:
            pass
        request_id = resp.headers.get("x-request-id") or resp.headers.get("request-id")
        rid_part = f" [request-id: {request_id}]" if request_id else ""

        # Retry common transient statuses.
        if resp.status_code in (408, 409, 425, 429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
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
    resp = _request_chat(payload, headers, timeout, retries=DEFAULT_RETRIES)
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
    resp = _request_chat(payload, headers, timeout, retries=DEFAULT_RETRIES)
    return resp.json()
