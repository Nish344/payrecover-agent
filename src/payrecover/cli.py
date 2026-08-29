from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from payrecover import __version__
from payrecover.config import Settings
from payrecover.models import ActionRequest, Case, Diagnosis
from payrecover.razorpay_client import (
    RazorpayAuthError,
    RazorpayClient,
    RazorpayClientError,
)
from payrecover.simulator.batchgen import seed_batch
from payrecover.store import Store

app = typer.Typer(name="payrecover", no_args_is_help=True, add_completion=False)

_REPORTS_DIR = Path("reports")
_FILL_IN = (
    "Implement these from docs/decisions.md (Day 1), then re-run:\n"
    "  src/payrecover/audit.py\n"
    "  src/payrecover/policy.py\n"
    "  src/payrecover/diagnosis.py\n"
    "  src/payrecover/metrics.py"
)


class _SqliteAudit:
    def __init__(self, conn: object) -> None:
        self._conn = conn

    def append(self, event: object) -> None:
        from payrecover.audit import append

        append(self._conn, event)  # type: ignore[arg-type]

    def list_for_case(self, case_id: str) -> list[object]:
        from payrecover.audit import list_for_case

        return list_for_case(self._conn, case_id)  # type: ignore[arg-type, return-value]


@app.callback()
def _configure(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _settings() -> Settings:
    try:
        return Settings()
    except ValidationError:
        typer.echo("Missing credentials. Copy .env.example to .env and fill test keys.", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def ping() -> None:
    """Verify test-mode Razorpay credentials with a single authenticated read."""
    settings = _settings()
    try:
        client = RazorpayClient(settings)
        result = client.ping()
    except RazorpayAuthError as exc:
        typer.echo(f"auth failed: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except RazorpayClientError as exc:
        typer.echo(f"razorpay error: {exc.__class__.__name__}: {exc}", err=True)
        raise typer.Exit(code=1) from None
    count = result.get("count", len(result.get("items", [])))
    typer.echo(f"ok  payrecover {__version__}  test-mode ping  payments_visible={count}")


@app.command()
def seed(
    seed: int = typer.Option(42, "--seed", help="Deterministic batch seed"),
    force: bool = typer.Option(False, "--force", help="Wipe existing cases and reseed"),
) -> None:
    """Create 80 synthetic failed-payment cases (local; no Razorpay writes)."""
    settings = _settings()
    store = Store(settings.db_path)
    if store.batch_for_seed(seed) is not None and not force:
        typer.echo(f"batch for seed={seed} already exists. Pass --force to replace.")
        return
    if force:
        store.wipe()
    batch_id = seed_batch(store, seed=seed)
    typer.echo(f"ok  seeded {store.case_count()} cases  batch_id={batch_id}  db={settings.db_path}")


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Policy + audit, no Razorpay writes"),
) -> None:
    """Process the batch: detect → diagnose → policy → act → simulate."""
    from payrecover.audit import ensure_schema
    from payrecover.diagnosis import diagnose
    from payrecover.policy import decide
    from payrecover.runner import run_batch

    settings = _settings()
    store = Store(settings.db_path)
    if store.case_count() == 0:
        typer.echo("No cases. Run `payrecover seed` first.", err=True)
        raise typer.Exit(code=1)
    try:
        ensure_schema(store.conn)
    except NotImplementedError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(_FILL_IN, err=True)
        raise typer.Exit(code=1) from None
    client = None if dry_run else RazorpayClient(settings)

    def _diagnose(case: Case) -> Diagnosis:
        return diagnose(case, settings=settings)

    def _decide(case: Case, diagnosis: Diagnosis) -> ActionRequest:
        return decide(case, diagnosis, kill_switch=settings.kill_switch)

    try:
        finished = run_batch(
            store,
            settings=settings,
            audit=_SqliteAudit(store.conn),
            diagnose=_diagnose,
            decide=_decide,
            client=client,
            dry_run=dry_run,
        )
    except NotImplementedError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(_FILL_IN, err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"ok  processed {len(finished)} cases  dry_run={dry_run}")


@app.command()
def report(
    output_dir: Annotated[Path, typer.Option("--output-dir")] = _REPORTS_DIR,
) -> None:
    """Write the recovery report (markdown + JSON)."""
    from payrecover.audit import list_for_case
    from payrecover.metrics import build_report

    settings = _settings()
    store = Store(settings.db_path)
    cases = store.list_cases()
    try:
        events = []
        for case in cases:
            events.extend(list_for_case(store.conn, case.case_id))
        path = build_report(cases, events, output_dir=output_dir)
    except NotImplementedError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(_FILL_IN, err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"ok  report {path}")


@app.command("audit")
def audit_cmd(case_id: str = typer.Argument(..., help="Case id, e.g. c42_00")) -> None:
    """Show the append-only audit trail for a case."""
    from payrecover.audit import export_text, list_for_case

    settings = _settings()
    store = Store(settings.db_path)
    try:
        events = list_for_case(store.conn, case_id)
        typer.echo(export_text(events))
    except NotImplementedError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(_FILL_IN, err=True)
        raise typer.Exit(code=1) from None


if __name__ == "__main__":
    app()
