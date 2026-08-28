from __future__ import annotations

import logging

import typer
from pydantic import ValidationError

from payrecover import __version__
from payrecover.config import Settings
from payrecover.razorpay_client import (
    RazorpayAuthError,
    RazorpayClient,
    RazorpayClientError,
)

app = typer.Typer(name="payrecover", no_args_is_help=True, add_completion=False)


@app.callback()
def _configure(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def ping() -> None:
    """Verify test-mode Razorpay credentials with a single authenticated read."""
    try:
        settings = Settings()
    except ValidationError:
        typer.echo("Missing credentials. Copy .env.example to .env and fill test keys.", err=True)
        raise typer.Exit(code=1) from None
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
def seed() -> None:
    """Create the synthetic failed-payment batch (Day 2+)."""
    typer.echo("seed is not wired yet. Needs simulator/batchgen plus your customer-behavior spec.")
    raise typer.Exit(code=1)


@app.command()
def run() -> None:
    """Process the batch: detect → diagnose → policy → act."""
    typer.echo("run is not wired yet. Needs diagnosis, policy, and the action executor.")
    raise typer.Exit(code=1)


@app.command()
def report() -> None:
    """Write the recovery report (markdown + JSON)."""
    typer.echo("report is not wired yet. Needs metrics.py.")
    raise typer.Exit(code=1)


@app.command("audit")
def audit_cmd(case_id: str | None = typer.Argument(None)) -> None:
    """Show the append-only audit trail for a case."""
    _ = case_id
    typer.echo("audit is not wired yet. Needs audit.py.")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
