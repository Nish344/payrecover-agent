from __future__ import annotations

from pydantic import SecretStr

from payrecover.config import Settings


def make_settings(**overrides: object) -> Settings:
    payload: dict[str, object] = {
        "razorpay_key_id": "rzp_test_dummykeyid",
        "razorpay_key_secret": SecretStr("test_secret"),
        "gemini_api_key": SecretStr(""),
        "llm_model": "test-model",
        "kill_switch": False,
        "razorpay_timeout_seconds": 0.05,
        "razorpay_read_retries": 3,
    }
    payload.update(overrides)
    return Settings(_env_file=None, **payload)  # type: ignore[arg-type]
