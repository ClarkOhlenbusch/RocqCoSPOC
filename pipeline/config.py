"""Pipeline configuration loading and model helpers."""

from pathlib import Path
from typing import Union

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    config_path = Path(__file__).resolve().parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def as_model_list(model_value: Union[str, list]) -> list[str]:
    if isinstance(model_value, list):
        models = [str(m).strip() for m in model_value if str(m).strip()]
        if not models:
            raise ValueError("Model list is empty in config.")
        return models
    model = str(model_value).strip()
    if not model:
        raise ValueError("Model is empty in config.")
    return [model]


def is_retryable_model_error(msg: str) -> bool:
    m = msg.lower()
    return any(s in m for s in [
        "open router api error 404", "open router api error 408",
        "open router api error 429", "open router api error 500",
        "open router api error 502", "open router api error 503",
        "open router api error 504", "open router request failed",
        "no endpoints found",
        "returned an empty message",
    ])
