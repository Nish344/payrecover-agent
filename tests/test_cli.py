from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from payrecover.cli import app
from payrecover.razorpay_client import RazorpayAuthError
from tests.helpers import make_settings

runner = CliRunner()


def test_detect_ingests_failed_payments_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = make_settings(db_path=tmp_path / "t.db")
    monkeypatch.setattr("payrecover.cli._settings", lambda: settings)

    class FakeClient:
        def __init__(self, _settings: object) -> None:
            pass

        def list_payments(self) -> dict[str, object]:
            return {
                "count": 2,
                "items": [
                    {"id": "pay_ok", "status": "captured", "amount": 10000},
                    {
                        "id": "pay_TVGlLnELbwZeV2",
                        "status": "failed",
                        "amount": 10000,
                        "error_reason": "international_transaction_not_allowed",
                    },
                ],
            }

    monkeypatch.setattr("payrecover.cli.RazorpayClient", FakeClient)
    result = runner.invoke(app, ["detect"])
    assert result.exit_code == 0
    assert "detected 1 failed payments" in result.stdout
    assert "rzp_pay_TVGlLnELbwZeV2" in result.stdout


def test_detect_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("payrecover.cli._settings", lambda: make_settings())

    class FakeClient:
        def __init__(self, _settings: object) -> None:
            raise RazorpayAuthError("refusing non-test Razorpay key")

    monkeypatch.setattr("payrecover.cli.RazorpayClient", FakeClient)
    result = runner.invoke(app, ["detect"])
    assert result.exit_code == 1
    assert "auth failed" in result.output


def test_live_without_case_or_limit_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from payrecover.simulator.batchgen import seed_batch
    from payrecover.store import Store

    settings = make_settings(db_path=tmp_path / "t.db")
    seed_batch(Store(settings.db_path), seed=42)
    monkeypatch.setattr("payrecover.cli._settings", lambda: settings)
    result = runner.invoke(app, ["run", "--live"])
    assert result.exit_code == 1
    assert "refusing unbounded --live" in result.output
