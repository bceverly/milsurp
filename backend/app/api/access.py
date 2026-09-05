"""The public "request access" form.

This is the only unauthenticated, email-sending endpoint in the application, so
it carries three layers of protection: reCAPTCHA, a per-IP rate limit, and a
hard cap on field lengths. It is also production-only — in dev there is no
support inbox to write to and no captcha keys configured.

Nothing is written to the database: the request is delivered to the support
address, and an administrator creates the account by hand. That keeps the
public surface to a single outbound email with no persistence to poison.
"""

from __future__ import annotations

import html
import logging
import threading
import time

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from ..deps import AppConfig
from ..services import mailer
from ..services.recaptcha import RecaptchaError, verify

router = APIRouter(tags=["access"])
log = logging.getLogger("milsurp.access")

# Per-IP submission times. In-process, like the login throttle: this is a
# single-worker application, and nginx enforces its own limit in front.
_submissions: dict[str, list[float]] = {}
_lock = threading.Lock()
WINDOW_SECONDS = 3600


class AccessRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    email: EmailStr
    # Optional context from the requester; capped so the email stays readable.
    message: str | None = Field(default=None, max_length=1000)
    recaptcha_token: str | None = Field(default=None, max_length=4096)


class AccessConfigOut(BaseModel):
    """What the login page needs in order to render the form."""

    enabled: bool
    recaptcha_site_key: str | None = None
    # "v2" | "v3" | None — the widget the frontend should render.
    recaptcha_version: str | None = None


def _client_ip(request: Request) -> str:
    # X-Forwarded-For is set by our own nginx; uvicorn is started with
    # forwarded_allow_ips restricted to loopback, so it cannot be spoofed from
    # outside.
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str, limit: int) -> None:
    now = time.monotonic()
    with _lock:
        recent = [t for t in _submissions.get(ip, []) if now - t < WINDOW_SECONDS]
        _submissions[ip] = recent
        if len(recent) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Too many access requests from this address. "
                    "Please try again later, or email us directly."
                ),
            )


def _record(ip: str) -> None:
    with _lock:
        _submissions.setdefault(ip, []).append(time.monotonic())


@router.get("/access-request/config", response_model=AccessConfigOut)
def access_config(config: AppConfig) -> AccessConfigOut:
    """Whether the login page should offer the form, and with which widget."""
    # Dev has no support inbox and no captcha keys; showing the form there would
    # only produce confusing failures.
    if config.is_dev or not config.access_requests.enabled:
        return AccessConfigOut(enabled=False)
    if not config.email.enabled:
        return AccessConfigOut(enabled=False)

    site_key = config.recaptcha.site_key if config.recaptcha.enabled else None
    return AccessConfigOut(
        enabled=True,
        recaptcha_site_key=site_key,
        # A v3 key is used with a score threshold; the config's minimum_score
        # being left at its default still works for v2, which ignores it.
        recaptcha_version="v3" if site_key else None,
    )


@router.post("/access-request", status_code=status.HTTP_202_ACCEPTED)
def submit_access_request(
    payload: AccessRequest, request: Request, config: AppConfig
) -> dict[str, str]:
    if config.is_dev or not config.access_requests.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access requests are not enabled on this server.",
        )
    if not config.email.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Access requests are unavailable: email is not configured.",
        )

    ip = _client_ip(request)
    _check_rate_limit(ip, config.access_requests.rate_limit_per_hour)

    if config.recaptcha.enabled:
        try:
            verify(payload.recaptcha_token or "", ip, config)
        except RecaptchaError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    support = config.email.support_address
    if not support:
        log.error("email.support_email is not set; cannot deliver the access request")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Access requests are unavailable: no support address is configured.",
        )

    # Every value came from an unauthenticated form, so it is escaped before it
    # goes anywhere near the HTML body.
    first = html.escape(payload.first_name.strip())
    last = html.escape(payload.last_name.strip())
    email = html.escape(str(payload.email))
    note = html.escape(payload.message.strip()) if payload.message else ""
    safe_ip = html.escape(ip)

    subject = f"Milsurp Monitor: access request from {first} {last}"
    body = f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#F4F6FA;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;">
  <tr><td style="background:#0A2240;padding:20px 24px;color:#fff;">
    <div style="font-size:17px;font-weight:700;">Access request</div>
    <div style="color:#C7CEDB;font-size:12px;margin-top:3px;">Milsurp Monitor</div>
  </td></tr>
  <tr><td style="padding:22px 24px;color:#11151C;font-size:14px;line-height:1.6;">
    <p style="margin:0 0 16px;">Someone has asked for an account.</p>
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;font-size:14px;">
      <tr><td style="padding:6px 0;color:#5A6474;width:120px;">Name</td>
          <td style="padding:6px 0;font-weight:600;">{first} {last}</td></tr>
      <tr><td style="padding:6px 0;color:#5A6474;">Email</td>
          <td style="padding:6px 0;font-weight:600;">{email}</td></tr>
      <tr><td style="padding:6px 0;color:#5A6474;">From IP</td>
          <td style="padding:6px 0;">{safe_ip}</td></tr>
    </table>
    {f'<p style="margin:16px 0 0;padding:12px;background:#F4F6FA;border-radius:6px;white-space:pre-wrap;">{note}</p>' if note else ''}
    <p style="margin:20px 0 0;color:#5A6474;font-size:13px;">
      To grant access, sign in as an administrator and create the account under
      <strong>Users</strong>. Nothing was written to the database by this request.
    </p>
  </td></tr>
</table></body></html>"""

    try:
        mailer.send_html(support, subject, body, config=config)
    except mailer.MailError as exc:
        log.exception("Could not deliver an access request")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the request right now. Please try again later.",
        ) from exc

    _record(ip)
    log.info("Access request from %s <%s> delivered to %s", f"{first} {last}", email, support)
    return {
        "message": (
            "Thanks — your request has been sent. " "An administrator will be in touch by email."
        )
    }
