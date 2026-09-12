#!/usr/bin/env python3
"""Print the URL `make test-postgres` should use, or explain why there is none.

The tests need their own database, and the credentials for it are already in
config.yaml -- so asking someone to retype them is asking for the typo that
prompted this file. Deriving the URL means the same role, the same host, the
same password, and the database name with ``_test`` on the end.

It is deliberately a *separate* database, never the configured one: these tests
run DROP SCHEMA public CASCADE.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_config  # noqa: E402

#: Appended to the configured database name. The tests refuse any name that
#: does not identify itself as a test database, so this is load-bearing.
SUFFIX = "_test"


def reachable(url: str) -> bool:
    import sqlalchemy as sa

    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    # Broad on purpose: no server, no database, wrong password -- from here
    # they are all just "not available", and the caller falls back to skipping.
    except Exception:
        return False
    else:
        return True
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--if-reachable",
        action="store_true",
        help=(
            "Print nothing and succeed when the derived database does not "
            "answer, so a caller can fall back to skipping rather than failing."
        ),
    )
    args = parser.parse_args()

    database = get_config().database
    if not database.is_postgres:
        if args.if_reachable:
            return 0
        print(
            "config.yaml does not name a PostgreSQL database, so there is nothing to\n"
            "derive a test URL from. Set MILSURP_TEST_POSTGRES_URL yourself:\n"
            "\n"
            '  sudo -u postgres psql -c "CREATE DATABASE milsurp_test OWNER milsurp;"\n'
            '  sudo -u postgres psql -d milsurp_test -c "GRANT ALL ON SCHEMA public TO milsurp;"\n'
            "\n"
            "  make test-postgres \\\n"
            "    MILSURP_TEST_POSTGRES_URL=postgresql+psycopg://USER:PASS@HOST/milsurp_test",
            file=sys.stderr,
        )
        return 1

    from dataclasses import replace

    url = replace(database, name=database.name + SUFFIX, url="").sqlalchemy_url
    if args.if_reachable and not reachable(url):
        return 0
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
