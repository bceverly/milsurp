"""Decide whether `npm audit --json` found anything not covered by an exception.

    python scripts/npm_audit_exceptions.py REPORT.json GHSA-xxxx:YYYY-MM-DD ...

Called by scripts/security.sh when `npm audit --audit-level=high` fails. Each
high or critical package npm lists is traced back through its "via" chain to
the advisories at the bottom of it -- npm reports one advisory once for every
package that depends on the affected one, so a single picomatch bug shows up as
six findings. A package is excused only when every advisory under it has an
exception that has not expired; anything else fails the scan, as before.

An exception stops working after its date, with no one having to remember to
remove it. When it lapses the scan fails again and says so, which is the
point: either upstream has shipped a fix by then, or someone looks again and
decides on purpose.

Exit status: 0 when everything left is excused, 1 otherwise.
"""

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

SERIOUS = {"high", "critical"}


def advisories(name, vulns, seen=None):
    """The advisory IDs (GHSA-...) at the bottom of a package's "via" chain."""
    seen = set() if seen is None else seen
    if name in seen:
        return set()
    seen.add(name)
    found = set()
    for via in vulns.get(name, {}).get("via", []):
        if isinstance(via, str):
            found |= advisories(via, vulns, seen)
        else:
            found.add(via.get("url", "").rsplit("/", 1)[-1])
    return found


def main(argv):
    report, specs = argv[1], argv[2:]
    with Path(report).open(encoding="utf-8") as f:
        vulns = json.load(f).get("vulnerabilities", {})

    today = datetime.now(UTC).date()
    exceptions = {}
    for spec in specs:
        ghsa, _, until = spec.partition(":")
        exceptions[ghsa] = date.fromisoformat(until)

    used, lapsed, failing = set(), set(), []
    for name, vuln in sorted(vulns.items()):
        if vuln.get("severity") not in SERIOUS:
            continue
        under = advisories(name, vulns)
        live = {a for a in under if a in exceptions and today <= exceptions[a]}
        lapsed |= {a for a in under if a in exceptions and today > exceptions[a]}
        if under and under == live:
            used |= live
        else:
            failing.append(name)

    for ghsa in sorted(used):
        print(f"excused: {ghsa} (exception expires {exceptions[ghsa]})")
    for ghsa in sorted(lapsed):
        print(f"EXPIRED: the exception for {ghsa} ended {exceptions[ghsa]}")
    for name in failing:
        print(f"not excused: {name}")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
