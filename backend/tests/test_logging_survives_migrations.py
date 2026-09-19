"""The migration chain must not switch off the application's logging.

``logging.config.fileConfig`` defaults to ``disable_existing_loggers=True``,
which disables every logger that already exists and is not named in the config
file. alembic.ini names three -- root, ``sqlalchemy.engine``, ``alembic`` -- and
the application has twenty-six ``milsurp.*`` loggers, all created when their
modules import. So running the chain in-process after those imports switched
them all off.

The failure mode is the reason this is worth a test of its own: nothing raises,
nothing is missing, the loggers still exist and still accept every call. They
just discard them. A failed sign-in would be recorded exactly as carefully as
before and land nowhere -- and the first you would know about it is looking for
an attack in a log that had been empty for months.
"""

from __future__ import annotations

import logging

from app.migrations import upgrade


def _milsurp_loggers() -> dict[str, logging.Logger]:
    return {
        name: item
        for name, item in logging.root.manager.loggerDict.items()
        if name.startswith("milsurp") and isinstance(item, logging.Logger)
    }


def run_the_chain() -> None:
    """Load and run alembic's env.py, which is where fileConfig lives.

    Already at head in the test database, so this upgrades nothing -- and it
    does not need to. env.py is imported and executed either way, and that is
    the step that used to switch the loggers off.
    """
    upgrade(revision="head")


class TestLoggingSurvivesTheMigrationChain:
    def test_the_suite_has_application_loggers_to_protect(self):
        """Guard on the guard: if nothing had imported them, the tests below
        would pass while proving nothing."""
        assert len(_milsurp_loggers()) > 5

    def test_none_are_disabled_afterward(self):
        run_the_chain()
        assert sorted(name for name, lg in _milsurp_loggers().items() if lg.disabled) == []

    def test_and_a_warning_still_comes_out(self):
        """The property that actually matters, asserted on behavior rather than
        on the `disabled` flag."""
        seen: list[str] = []

        class Catcher(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                seen.append(record.getMessage())

        log = logging.getLogger("milsurp.auth")
        handler = Catcher()
        log.addHandler(handler)
        try:
            run_the_chain()
            log.warning("Failed sign-in for admin from 203.0.113.9")
        finally:
            log.removeHandler(handler)

        assert any("Failed sign-in" in message for message in seen)
