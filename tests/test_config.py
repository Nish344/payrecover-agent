from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from payrecover.config import Settings
from tests.helpers import make_settings


def test_secret_is_not_in_repr() -> None:
    settings = make_settings()
    dumped = repr(settings)
    assert "test_secret" not in dumped
    assert settings.razorpay_key_secret.get_secret_value() == "test_secret"


def test_kill_switch_parses_true() -> None:
    settings = make_settings(kill_switch=True)
    assert settings.kill_switch is True


def test_missing_key_id_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, razorpay_key_secret=SecretStr("x"))
    assert "razorpay_key_id" in str(exc_info.value)
