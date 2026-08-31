from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from payrecover.diagnosis import diagnose
from payrecover.models import Case, DiagnosisPath, PaymentFailure
from tests.helpers import make_settings


def _case(reason: str, description: str = "x") -> Case:
    return Case(
        case_id="c1",
        failure=PaymentFailure(
            amount_paise=10000,
            error_reason=reason,
            error_code="BAD_REQUEST_ERROR",
            error_description=description,
            method="card",
            international=True,
        ),
        created_at=datetime.now(UTC),
    )


def test_unambiguous_reason_skips_llm() -> None:
    diagnosis = diagnose(
        _case("international_transaction_not_allowed"),
        settings=make_settings(),
    )
    assert diagnosis.path == DiagnosisPath.RULES
    assert diagnosis.cause == "international_transaction_not_allowed"
    assert diagnosis.confidence >= 0.9
    assert diagnosis.model is None


def test_ambiguous_falls_back_without_key() -> None:
    settings = make_settings()
    diagnosis = diagnose(_case("ambiguous"), settings=settings)
    assert diagnosis.path == DiagnosisPath.RULES
    assert diagnosis.cause == "ambiguous"
    assert diagnosis.confidence < 0.6


def test_llm_path_when_complete_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    import payrecover.diagnosis as diagnosis_mod

    def fake_complete(api_key: str, model: str, case: Case) -> str:
        _ = api_key, model, case
        return '{"cause": "network_glitch", "confidence": 0.72, "rationale": "llm"}'

    monkeypatch.setattr(diagnosis_mod, "_complete_llm", fake_complete)
    settings = make_settings(anthropic_api_key=SecretStr("sk-test"))
    diagnosis = diagnose(_case("nope"), settings=settings)
    assert diagnosis.path == DiagnosisPath.LLM
    assert diagnosis.cause == "network_glitch"
    assert diagnosis.confidence == 0.72


def test_malformed_llm_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import payrecover.diagnosis as diagnosis_mod

    monkeypatch.setattr(diagnosis_mod, "_complete_llm", lambda *a, **k: "not json")
    diagnosis = diagnose(_case("nope"), settings=make_settings(anthropic_api_key=SecretStr("sk")))
    assert diagnosis.path == DiagnosisPath.RULES
    assert diagnosis.cause == "ambiguous"
