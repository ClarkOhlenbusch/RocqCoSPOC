"""Model invocation with format retries and fallback."""

from pathlib import Path
from typing import Optional, Union

from pipeline.config import as_model_list, is_retryable_model_error
from pipeline.utils import preview_text


def chat_with_model_fallback(
    model_value: Union[str, list], prompt: str, config: dict,
    *, stage: str, metadata: Optional[dict] = None,
) -> tuple[str, str]:
    from pipeline.openrouter_client import chat

    models = as_model_list(model_value)
    errors = []
    debug_enabled = bool(config.get("debug"))
    debug_limit = int(config.get("debug_char_limit", 500))
    if debug_enabled:
        print(f"[DEBUG:{stage}] trying models in order: {models}", flush=True)
    for i, model in enumerate(models):
        try:
            if debug_enabled:
                print(f"[DEBUG:{stage}] invoking model {i + 1}/{len(models)}: {model}", flush=True)
            response = chat(
                model, prompt,
                max_tokens=config.get("max_tokens", 4096),
                temperature=config.get("temperature", 0.3),
                timeout=config.get("request_timeout_sec", 60),
                retries=config.get("request_retries", 4),
                backoff_base_sec=config.get("request_backoff_base_sec", 1.5),
                backoff_multiplier=config.get("request_backoff_multiplier", 2.0),
                backoff_max_sec=config.get("request_backoff_max_sec", 20.0),
                backoff_jitter_sec=config.get("request_backoff_jitter_sec", 0.35),
                log_path=Path(config["model_log_path"]) if config.get("model_log_path") else None,
                metadata={"stage": stage, "model_index": i + 1, "model_count": len(models), **(metadata or {})},
            )
            if debug_enabled:
                print(f"[DEBUG:{stage}] model succeeded: {model}, response_chars={len(response)}", flush=True)
                print(f"[DEBUG:{stage}] response preview:\n{preview_text(response, limit=debug_limit)}", flush=True)
            return response, model
        except Exception as e:
            msg = str(e)
            errors.append(f"{model}: {msg}")
            if debug_enabled:
                print(f"[DEBUG:{stage}] model failure from {model}: {msg}", flush=True)
            if i == len(models) - 1 or not is_retryable_model_error(msg):
                break
            print(f"  Warning: {stage} failed with '{model}', trying fallback...", flush=True)
    raise RuntimeError(f"{stage} failed:\n  - " + "\n  - ".join(errors))


def generate_with_format_retries(
    model_value: Union[str, list], prompt: str, config: dict,
    *, stage: str, parser, retry_guidance_fn=None,
    debug_attempts: Optional[list[dict]] = None,
    log_metadata: Optional[dict] = None,
    formal_statement: str = "",
) -> str:
    max_attempts = int(config.get("format_retries", 3))
    current_prompt = prompt
    errors: list[str] = []
    debug_enabled = bool(config.get("debug"))
    debug_limit = int(config.get("debug_char_limit", 500))
    if debug_enabled:
        print(f"[DEBUG:{stage}] format retries enabled, max_attempts={max_attempts}, prompt_chars={len(prompt)}", flush=True)
        print(f"[DEBUG:{stage}] prompt preview:\n{preview_text(prompt, limit=debug_limit)}", flush=True)
    for attempt in range(1, max_attempts + 1):
        if debug_enabled:
            print(f"[DEBUG:{stage}] model-format attempt {attempt}/{max_attempts}", flush=True)
        attempt_config = config
        if attempt > 1:
            attempt_config = dict(config)
            attempt_config["temperature"] = max(config.get("temperature", 0.0), 0.4)
        out, resolved_model = chat_with_model_fallback(
            model_value, current_prompt, attempt_config,
            stage=stage, metadata={**(log_metadata or {}), "format_attempt": attempt},
        )
        attempt_info = {"format_attempt": attempt, "model": resolved_model, "raw_output": out}
        if debug_enabled:
            print(f"[DEBUG:{stage}] model={resolved_model}, raw_chars={len(out)}", flush=True)
            print(f"[DEBUG:{stage}] raw output preview:\n{preview_text(out, limit=debug_limit)}", flush=True)
        try:
            parsed = parser(out)
            attempt_info["status"] = "parsed"
            attempt_info["parsed_output"] = parsed
            if debug_enabled:
                print(f"[DEBUG:{stage}] parser success, parsed_chars={len(parsed)}", flush=True)
                print(f"[DEBUG:{stage}] parsed preview:\n{preview_text(parsed, limit=debug_limit)}", flush=True)
            if debug_attempts is not None:
                debug_attempts.append(attempt_info)
            return parsed
        except Exception as e:
            attempt_info["status"] = "invalid_format"
            attempt_info["error"] = str(e)
            if debug_enabled:
                print(f"[DEBUG:{stage}] parser failure: {e}", flush=True)
            if debug_attempts is not None:
                debug_attempts.append(attempt_info)
            errors.append(f"Attempt {attempt}: {e}")
            if attempt == max_attempts:
                break
            retry_guidance = ""
            if retry_guidance_fn:
                retry_guidance = retry_guidance_fn(stage, str(e), formal_statement=formal_statement)
            current_prompt = (
                prompt
                + "\n\nYour previous output was invalid.\n"
                + f"Reason: {e}\n"
                + (retry_guidance + "\n" if retry_guidance else "")
                + "Return a corrected answer from scratch that follows the required output format exactly.\n"
                + "Do not explain. Do not analyze. Output only the required final artifact.\n"
            )
            print(f"  Warning: {stage} output had invalid format, retrying ({attempt}/{max_attempts - 1})...", flush=True)
    raise RuntimeError(f"{stage} failed format validation:\n  - " + "\n  - ".join(errors))
