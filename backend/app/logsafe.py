"""Making untrusted values safe to put in a log record.

A value that reaches a log line from a request body — a username, an email
address, a form field — is attacker-controlled. If it can carry a newline, the
attacker can forge whole log entries: an invented "Failed sign-in" from an IP
of their choosing, a fake success line to bury a real failure. It also breaks
any downstream reader that assumes one record per line.

This is OWASP A09, *Security Logging and Monitoring Failures*: logs that can be
poisoned are worse than no logs, because they are trusted during an incident.

Use :func:`scrub` on every untrusted value passed to the logging module.
"""

from __future__ import annotations

import re

#: Long enough to identify what was attempted, short enough that a megabyte of
#: junk in a username cannot flood the log file.
MAX_LOGGED_LENGTH = 128


def scrub(value: object, *, limit: int = MAX_LOGGED_LENGTH) -> str:
    """Return ``value`` as a single-line, length-capped, printable string.

    Control characters become visible escapes rather than disappearing, so a
    log reader can tell the difference between someone whose name is "Bob" and
    someone who submitted ``Bob\\nINFO Successful sign-in for admin``.
    """
    text = value if isinstance(value, str) else str(value)

    # Newlines first, and explicitly: this is the part that stops record
    # forgery, and keeping it as a plain replace makes the barrier obvious to
    # a reader and to static analysis alike.
    text = text.replace("\r", "\\r").replace("\n", "\\n")

    # Everything else non-printable (NUL, escape sequences that could drive a
    # terminal, bidirectional overrides) becomes an escape too.
    text = "".join(ch if ch.isprintable() else f"\\u{ord(ch):04x}" for ch in text)

    if len(text) > limit:
        text = text[:limit] + "…(truncated)"
    return text


#: What an account name may contain, matching what the create-user endpoint
#: accepts. Anything else is, by definition, not one of this application's
#: usernames.
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._\-]{1,64}")

#: What a peer address may contain: an IPv4 or IPv6 address, or the marker used
#: when there is no peer at all.
#:
#: Deliberately a shape rather than a scrub. The address comes off the
#: connection rather than out of a header, so in practice it holds nothing but
#: an address — but :func:`scrub` only escapes it, and an escape is string
#: manipulation as far as a taint tracker is concerned, so CodeQL went on
#: reporting log injection on a line that was already safe. An allowlist is a
#: barrier it recognizes, and it is the stronger claim to a reader as well.
ADDRESS_PATTERN = re.compile(r"unknown|[0-9.]{7,15}|[0-9A-Fa-f:.]{2,45}")

#: Stands in for a value that failed the allowlist. Fixed text, so it can never
#: itself carry anything from the request.
REJECTED = "<rejected>"


def safe_identifier(value: object, pattern: re.Pattern[str] = USERNAME_PATTERN) -> str:
    """Return ``value`` only if it matches ``pattern`` in full, else a marker.

    An allowlist, not an escape — and the difference matters twice over.

    For the reader: "this is one of our usernames, or it is nothing" is a
    stronger claim than "this has had its newlines removed", and it cannot be
    weakened by a character nobody thought of.

    For static analysis: :func:`scrub` escapes, and an escaping function is
    just string manipulation as far as a taint tracker is concerned, so the
    value stays tainted all the way to the log call.

    **This function does not fix that, and it was once claimed here that it
    did.** It returns the original string on the matching branch, so a taint
    tracker follows the value straight through the conditional — CodeQL went on
    reporting log injection on the sign-in failure this was written for, and it
    was right to. A guard narrows what an attacker can *say*; it does not
    change where the string came from.

    So use it where a bounded shape is the point — an IP address, a slug — and
    do not reach for it to launder request data into a log line. The way to
    keep request data out of a log is to log something else: the sign-in path
    now names the account it matched, read back from the database, and a fixed
    marker when there was none.
    """
    text = value if isinstance(value, str) else str(value)
    return text if pattern.fullmatch(text) else REJECTED
