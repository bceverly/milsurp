"""The postinst's decision to restart the service.

This file exists because a release once installed cleanly, reported success,
exited 0 -- and left the site down. ``dh_installsystemd --no-start`` means the
preinst stops the service on upgrade and nothing brings it back, so every
upgrade was an outage lasting until somebody read the line telling them to
restart by hand.

The condition below is what replaced that. It is a few words of shell in a
file nothing else covers, and it is the difference between a deploy and an
outage, so it is tested here rather than trusted.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

POSTINST = Path(__file__).resolve().parents[2] / "debian" / "milsurp.postinst"

#: The states ``MIGRATION_STATE`` can hold by the time the decision is made.
STATES = ("current", "migrated", "failed", "unreachable")


@pytest.fixture(scope="module")
def postinst() -> str:
    return POSTINST.read_text()


@pytest.fixture(scope="module")
def restart_condition(postinst: str) -> str:
    """The real `if` test out of the shipped file, not a copy of it.

    A copy would keep passing after somebody edited the postinst, which is
    the one thing this test is for.
    """
    match = re.search(
        r'^\s*if (\[ "\$FRESH_CONFIG" != yes \][\s\S]*?); then$',
        postinst,
        re.M,
    )
    assert match, "the restart condition is no longer recognizable in the postinst"
    return " ".join(match.group(1).split())


def _decides_to_restart(condition: str, *, fresh: str, state: str) -> bool:
    """Run the shipped condition under /bin/sh with these two variables set."""
    script = (
        f"FRESH_CONFIG={fresh}\n"
        f"MIGRATION_STATE={state}\n"
        f"if {condition}; then echo YES; else echo NO; fi\n"
    )
    out = subprocess.run(
        ["/bin/sh", "-c", script], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out in {"YES", "NO"}, out
    return out == "YES"


class TestWhenTheServiceComesBack:
    """An upgrade that leaves the site down is the failure worth preventing."""

    @pytest.mark.parametrize("state", ["current", "migrated"])
    def test_an_ordinary_upgrade_restarts(self, restart_condition, state):
        """The schema matches this build, so serving it is safe."""
        assert _decides_to_restart(restart_condition, fresh="no", state=state)

    def test_a_failed_migration_does_not(self, restart_condition):
        """The whole reason for --no-start: never serve an unmigrated database."""
        assert not _decides_to_restart(restart_condition, fresh="no", state="failed")

    def test_an_unreachable_database_does_not(self, restart_condition):
        """A first install with PostgreSQL, or a database that is not up yet.
        The four-step block tells the operator what to do; starting is theirs."""
        assert not _decides_to_restart(restart_condition, fresh="no", state="unreachable")

    @pytest.mark.parametrize("state", STATES)
    def test_a_fresh_config_never_starts(self, restart_condition, state):
        """config.yaml is still placeholders and there is no admin password;
        starting would only produce a service nobody can sign into."""
        assert not _decides_to_restart(restart_condition, fresh="yes", state=state)

    def test_an_empty_state_does_not_restart(self, restart_condition):
        """Whatever went wrong, an unrecognized state is not a yes."""
        assert not _decides_to_restart(restart_condition, fresh="no", state="")


class TestTheRestOfTheSystemdHandling:
    def test_the_units_are_reloaded(self, postinst: str):
        """debhelper only emits daemon-reload beside the start code that
        --no-start suppresses, so without this a changed unit file is read
        from a stale copy until somebody notices the warning by hand."""
        assert "systemctl --system daemon-reload" in postinst

    def test_the_reload_cannot_fail_the_install(self, postinst: str):
        reload_line = next(
            line
            for line in postinst.splitlines()
            if "systemctl --system daemon-reload" in line and not line.lstrip().startswith("#")
        )
        assert "|| true" in reload_line

    def test_the_restart_respects_policy_rc_d(self, postinst: str):
        """`deb-systemd-invoke`, not `systemctl`: a container build sets
        policy-rc.d to keep services from starting, and the installer test
        runs in one."""
        assert "deb-systemd-invoke restart 'milsurp.service'" in postinst

    def test_it_is_all_guarded_by_configure_and_systemd(self, postinst: str):
        assert 'if [ "$1" = configure ] && [ -d /run/systemd/system ]; then' in postinst

    def test_the_script_parses(self):
        """A postinst with a syntax error is a package that cannot install."""
        subprocess.run(["/bin/sh", "-n", str(POSTINST)], check=True)
