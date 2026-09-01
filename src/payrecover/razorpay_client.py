from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

import razorpay
import requests
from razorpay.errors import BadRequestError, GatewayError, ServerError

from payrecover.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RazorpayClientError(Exception):
    """Base for every error this wrapper raises."""


class RazorpayAuthError(RazorpayClientError):
    """Missing, live, or rejected credentials. Never retry."""


class RazorpayTimeoutError(RazorpayClientError):
    """HTTP timeout. Demo graceful-failure path for in-flight writes."""


class RazorpayUnavailableError(RazorpayClientError):
    """Connection/network failure talking to Razorpay."""


class RazorpayAPIError(RazorpayClientError):
    """Razorpay returned an application-level error."""

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


class _TimeoutSession(requests.Session):
    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self._timeout)
        return super().request(method, url, **kwargs)


def _redact(value: str) -> str:
    for needle in ("rzp_test_", "rzp_live_"):
        if needle in value:
            return "[redacted]"
    return value


class RazorpayClient:
    """Thin test-mode wrapper. Reads may retry; writes never do."""

    def __init__(
        self,
        settings: Settings,
        *,
        sdk: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key_id = settings.razorpay_key_id
        if not key_id.startswith("rzp_test_"):
            raise RazorpayAuthError("refusing non-test Razorpay key")
        self._read_retries = settings.razorpay_read_retries
        self._sleep = sleep
        if sdk is not None:
            self._sdk = sdk
            return
        session = _TimeoutSession(settings.razorpay_timeout_seconds)
        self._sdk = razorpay.Client(
            session=session,
            auth=(key_id, settings.razorpay_key_secret.get_secret_value()),
        )

    def ping(self) -> Mapping[str, Any]:
        """Cheap authenticated read used by `payrecover ping`."""
        return self.list_payments(count=1, skip=0)

    def fetch_order(self, order_id: str) -> Mapping[str, Any]:
        return self._read(self._sdk.order.fetch, order_id)

    def fetch_payment(self, payment_id: str) -> Mapping[str, Any]:
        return self._read(self._sdk.payment.fetch, payment_id)

    def list_payments(self, *, count: int = 100, skip: int = 0) -> Mapping[str, Any]:
        return self._read(self._sdk.payment.all, {"count": count, "skip": skip})

    def fetch_payment_link(self, payment_link_id: str) -> Mapping[str, Any]:
        return self._read(self._sdk.payment_link.fetch, payment_link_id)

    def list_payment_links(
        self,
        *,
        reference_id: str | None = None,
        count: int = 100,
        skip: int = 0,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {"count": count, "skip": skip}
        if reference_id is not None:
            params["reference_id"] = reference_id
        return self._read(self._sdk.payment_link.all, params)

    def create_order(
        self,
        *,
        case_id: str,
        amount_paise: int,
        receipt: str,
        notes: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": {"case_id": case_id, **dict(notes or {})},
        }
        return self._write(self._sdk.order.create, payload)

    def create_payment_link(
        self,
        *,
        case_id: str,
        amount_paise: int,
        description: str,
        customer: Mapping[str, str],
        reference_id: str,
        notes: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "accept_partial": False,
            "description": description,
            "reference_id": reference_id,
            "customer": dict(customer),
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {"case_id": case_id, **dict(notes or {})},
        }
        return self._write(self._sdk.payment_link.create, payload)

    def notify_payment_link(
        self,
        *,
        case_id: str,
        payment_link_id: str,
        medium: str = "email",
    ) -> Mapping[str, Any]:
        logger.info("notify_payment_link case_id=%s medium=%s", case_id, medium)
        return self._write(self._sdk.payment_link.notifyBy, payment_link_id, medium)

    def cancel_payment_link(self, *, case_id: str, payment_link_id: str) -> Mapping[str, Any]:
        logger.info("cancel_payment_link case_id=%s", case_id)
        return self._write(self._sdk.payment_link.cancel, payment_link_id)

    def _read(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return self._call(fn, *args, retry=True, **kwargs)

    def _write(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return self._call(fn, *args, retry=False, **kwargs)

    def _call(self, fn: Callable[..., T], *args: Any, retry: bool, **kwargs: Any) -> T:
        attempts = self._read_retries if retry else 1
        delay = 0.5
        last: RazorpayClientError | None = None
        for attempt in range(attempts):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                mapped = _map_error(exc)
                if not retry or not _is_transient(mapped) or attempt == attempts - 1:
                    raise mapped from exc
                last = mapped
                logger.warning(
                    "razorpay read retry attempt=%s error=%s",
                    attempt + 1,
                    mapped.__class__.__name__,
                )
                self._sleep(delay)
                delay *= 2
        assert last is not None
        raise last


class InjectedTimeoutClient:
    """Demo client: every write raises RazorpayTimeoutError. No network."""

    def create_payment_link(self, **kwargs: Any) -> Mapping[str, Any]:
        raise RazorpayTimeoutError("injected timeout")

    def notify_payment_link(self, **kwargs: Any) -> Mapping[str, Any]:
        raise RazorpayTimeoutError("injected timeout")

    def cancel_payment_link(self, **kwargs: Any) -> Mapping[str, Any]:
        raise RazorpayTimeoutError("injected timeout")


def _is_transient(error: RazorpayClientError) -> bool:
    return isinstance(error, (RazorpayTimeoutError, RazorpayUnavailableError))


def _map_error(exc: BaseException) -> RazorpayClientError:
    if isinstance(exc, RazorpayClientError):
        return exc
    if isinstance(exc, (requests.Timeout, requests.ConnectTimeout, requests.ReadTimeout)):
        return RazorpayTimeoutError("Razorpay request timed out")
    if isinstance(exc, requests.ConnectionError):
        return RazorpayUnavailableError("Razorpay connection failed")
    message = _redact(str(exc) or exc.__class__.__name__)
    lower = message.lower()
    if "authentication" in lower or "unauthorized" in lower:
        return RazorpayAuthError(message)
    if isinstance(exc, BadRequestError):
        return RazorpayAPIError(message, kind="bad_request")
    if isinstance(exc, GatewayError):
        return RazorpayAPIError(message, kind="gateway")
    if isinstance(exc, ServerError):
        return RazorpayAPIError(message, kind="server")
    if isinstance(exc, requests.RequestException):
        return RazorpayUnavailableError(message)
    return RazorpayAPIError(message, kind="unknown")
