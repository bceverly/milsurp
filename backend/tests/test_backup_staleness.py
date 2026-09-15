"""Noticing that copies have stopped leaving the machine.

An off-machine backup is a cron job, and a cron job that stops does so quietly:
the first sign is an empty directory on the day it is needed. That is the same
failure the canary exists for — something that should be happening has stopped,
and nothing announces it — so it is reported by the same nightly email.

**The check reads a stamp, not the far side.** The application cannot see a NAS
across the network, and asking it to would mean handing it credentials for the
one place a compromised application must not reach: the backups.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from app.services import backup, canary


@pytest.fixture
def snapshots(tmp_path, app_config):
    """A config whose snapshot directory is a scratch one."""
    directory = tmp_path / "backups"
    directory.mkdir()
    config = dataclasses.replace(
        app_config, backups=dataclasses.replace(app_config.backups, directory=directory)
    )
    return directory, config


def _stamp(directory, *, hours_ago: float) -> None:
    path = directory / backup.OFFSITE_STAMP
    path.write_text("2026-09-15T03:10:00+00:00 10074739 nas:/backup\n", encoding="utf-8")
    when = (datetime.now(UTC) - timedelta(hours=hours_ago)).timestamp()
    import os

    os.utime(path, (when, when))


class TestReadingTheStamp:
    def test_a_fresh_copy(self, snapshots):
        directory, _config = snapshots
        _stamp(directory, hours_ago=3)
        assert backup.offsite_age_hours(directory) == pytest.approx(3, abs=0.1)

    def test_no_stamp_at_all_is_none_rather_than_zero(self, snapshots):
        """None means "never set up", which is reported differently from "it
        has been four days" — one is a deployment that made a choice and the
        other is a job that broke."""
        directory, _config = snapshots
        assert backup.offsite_age_hours(directory) is None

    def test_a_directory_that_does_not_exist(self, tmp_path):
        assert backup.offsite_age_hours(tmp_path / "nowhere") is None


class TestWhatTheCanarySays:
    def test_a_recent_copy_is_not_a_problem(self, snapshots):
        directory, config = snapshots
        _stamp(directory, hours_ago=12)
        health = canary.backup_health(config)
        assert health.configured is True
        assert health.stale is False

    def test_one_missed_night_is_not_either(self, snapshots):
        """Reporting on a single miss — a NAS rebooting, an hour of no network —
        would teach whoever reads this to skim past it, which is the failure a
        nightly report can least afford."""
        directory, config = snapshots
        _stamp(directory, hours_ago=30)
        assert canary.backup_health(config).stale is False

    def test_but_two_is(self, snapshots):
        directory, config = snapshots
        _stamp(directory, hours_ago=50)
        health = canary.backup_health(config)
        assert health.stale is True
        assert "day(s) ago" in health.headline

    def test_a_deployment_that_never_set_it_up_is_not_nagged(self, snapshots):
        """Somebody running this on a laptop has not forgotten to configure
        off-machine backups; they have decided not to. A nightly complaint
        about a choice is noise."""
        _directory, config = snapshots
        health = canary.backup_health(config)
        assert health.configured is False
        assert health.stale is False


class TestTheStampIsOnlyWrittenOnSuccess:
    def test_the_script_writes_it_after_the_byte_check(self):
        """Source-inspected. A stamp touched at the start of the run would age
        correctly while the copy failed every single night, which is precisely
        the reassuring-and-wrong state this is meant to catch."""
        import pathlib

        script = (
            pathlib.Path(__file__).resolve().parents[2] / "scripts" / "offsite-backup.sh"
        ).read_text(encoding="utf-8")
        verified = script.index("verified $LOCAL_BYTES bytes")
        written = script.index(".offsite-stamp")
        assert verified < written, "the stamp must be written after the copy is verified"
