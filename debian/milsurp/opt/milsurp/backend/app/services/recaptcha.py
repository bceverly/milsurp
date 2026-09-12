"""Google reCAPTCHA verification.

Used by the public "request access" form, which is the only unauthenticated
endpoint in the application that sends email. Without a challenge, a bot could
burn the Gmail sending quota or use the server to relay junk to the support
address.

Supports both v2 ("I'm not a robot" — pass/fail) and v3 (a 0.0-1.0 score). The
response tells us which: v3 includes a ``score`` field, v2 does not.
"""

from __future__ import annotations

import logging

import requests

from ..config import Config

log = logging.getLogger("milsurp.recaptcha")


class RecaptchaError(RuntimeError):
    """The challenge was not satisfied."""


#: Error codes Google returns that mean "the user needs to try again" rather
#: than "the server is misconfigured".
USER_FIXABLE = {
    "missing-input-response",
    "invalid-input-response",
    "timeout-or-duplicate",
}


def verify(token: str, remote_ip: str | None, config: Config) -> float | None:
    """Validate a reCAPTCHA token. Returns the v3 score, or ``None`` for v2.

    Raises :class:`RecaptchaError` when the challenge fails.
    """
    settings = config.recaptcha
    if not settings.enabled:
        # Verification is off; the caller decides whether that is acceptable.
        return None
    if not settings.secret_key:
        raise RecaptchaError("reCAPTCHA is enabled but recaptcha.secret_key is not set.")
    if not token:
        raise RecaptchaError("Please complete the verification challenge.")

    payload = {"secret": settings.secret_key, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        response = requests.post(settings.verify_url, data=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        # Google being unreachable must not be treated as a passing challenge.
        log.warning("reCAPTCHA verification request failed: %s", exc)
        raise RecaptchaError(
            "Could not reach the verification service. Please try again shortly."
        ) from exc

    if not result.get("success"):
        codes = result.get("error-codes") or []
        log.info("reCAPTCHA rejected a submission: %s", codes)
        if any(code in USER_FIXABLE for code in codes):
            raise RecaptchaError("Verification failed. Please try the challenge again.")
        raise RecaptchaError("Verification failed.")

    score = result.get("score")
    if score is None:
        return None  # v2: success alone is the answer.

    if float(score) < settings.minimum_score:
        log.info("reCAPTCHA score %.2f below the %.2f threshold", score, settings.minimum_score)
        raise RecaptchaError(
            "This request looked automated. Please try again, or email us directly."
        )
    return float(score)
