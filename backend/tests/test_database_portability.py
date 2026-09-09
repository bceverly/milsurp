"""The schema has to work on SQLite *and* PostgreSQL.

The project's rule, written down in README.md under "Two engines, one schema":

  1. Every schema change works on both engines.
  2. Every migration is idempotent -- running it twice is running it once.

Both halves are things that can be checked rather than remembered, so they are
checked here.

The dialect half is checked two ways. Statically, over the migration files, for
the mistake that has actually been made -- a numeric ``server_default`` on a
boolean column, which SQLite takes and PostgreSQL refuses outright. And, when a
PostgreSQL server is available, dynamically: the whole chain is run up, down to
base and up again against a real server. Set ``MILSURP_TEST_POSTGRES_URL`` to a
database this suite may **drop every table in** and the dynamic tests run; leave
it unset and they skip.

CI sets it. A laptop usually does not, which is why the static check exists at
all: it is the part that runs everywhere.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest
import sqlalchemy as sa

from app import config as config_module
from app.config import DatabaseConfig, load_config

BACKEND_DIR = Path(__file__).resolve().parents[1]
VERSIONS_DIR = BACKEND_DIR / "alembic" / "versions"

MIGRATIONS = sorted(VERSIONS_DIR.glob("0*.py"))


class TestTheDatabaseBlockIsReadCorrectly:
    """``database:`` in config.yaml, and what each shape of it means."""

    def read(self, block: dict) -> DatabaseConfig:
        return config_module._database(block, Path("/var/lib/milsurp"))

    def test_a_file_that_says_nothing_is_sqlite_where_the_mode_puts_it(self):
        database = self.read({})
        assert database.engine == "sqlite"
        assert database.sqlalchemy_url == "sqlite:////var/lib/milsurp/milsurp.db"

    def test_the_shape_every_existing_deployment_has_still_means_sqlite(self):
        """A block with only a path predates PostgreSQL support and must not
        change meaning under it."""
        database = self.read({"path": "/etc/milsurp/milsurp.db"})
        assert database.engine == "sqlite"
        assert database.sqlalchemy_url == "sqlite:////etc/milsurp/milsurp.db"

    def test_naming_a_host_is_enough_to_mean_postgresql(self):
        """Without this, the commonest paste -- host/name/user/password and no
        `engine:` -- would silently keep using SQLite and look like the move
        had simply done nothing."""
        database = self.read({"host": "db.internal", "name": "milsurp", "user": "milsurp"})
        assert database.is_postgres
        assert database.sqlalchemy_url.startswith("postgresql+psycopg://milsurp@db.internal:5432/")

    def test_the_driver_is_psycopg_whichever_scheme_was_pasted(self):
        for pasted in ("postgres://u:p@h/db", "postgresql://u:p@h/db"):
            assert self.read({"url": pasted}).sqlalchemy_url == "postgresql+psycopg://u:p@h/db"

    def test_a_password_with_punctuation_in_it_survives(self):
        """A generated password contains "/", "@" and "#" often enough that
        this is not a theoretical case: unescaped, each of them cuts the URL in
        a different wrong place."""
        database = self.read(
            {"host": "h", "name": "milsurp", "user": "mil surp", "password": "p@ss/w#rd"}
        )
        url = sa.engine.make_url(database.sqlalchemy_url)
        assert url.username == "mil surp"
        assert url.password == "p@ss/w#rd"
        assert url.host == "h"
        assert url.database == "milsurp"

    def test_sslmode_is_passed_through_when_asked_for(self):
        database = self.read({"host": "h", "name": "n", "user": "u", "sslmode": "require"})
        assert sa.engine.make_url(database.sqlalchemy_url).query["sslmode"] == "require"

    def test_the_aliases_people_type_are_accepted(self):
        for spelling in ("postgres", "PostgreSQL", "pg", "psql"):
            assert self.read({"engine": spelling, "name": "n"}).engine == "postgresql"

    def test_an_engine_nobody_supports_is_refused_at_load(self):
        """Rather than at the first query, which is a psycopg traceback in a
        scheduler thread at three in the morning."""
        from app.config import ConfigError

        with pytest.raises(ConfigError, match="mysql"):
            self.read({"engine": "mysql"})

    def test_what_is_shown_to_a_human_never_carries_the_password(self):
        database = self.read({"host": "h", "name": "n", "user": "u", "password": "hunter2"})
        assert "hunter2" not in database.describe()
        assert database.describe() == "postgresql://u@h:5432/n"

    def test_the_sqlite_path_is_still_resolved_under_postgresql(self):
        """It is what the importer reads from and what a last snapshot before
        the move is taken of."""
        database = self.read({"engine": "postgresql", "name": "n", "path": "/etc/milsurp/old.db"})
        assert database.path == Path("/etc/milsurp/old.db")


class TestTheEngineIsBuiltForTheDatabaseItIsTalkingTo:
    def test_sqlite_keeps_its_pragmas_and_its_thread_setting(self, app_config):
        """The scheduler's scan threads share one engine, which SQLite's DBAPI
        refuses by default."""
        from app.database import get_engine

        engine = get_engine()
        assert engine.dialect.name == "sqlite"
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1

    def test_postgresql_gets_a_pool_and_not_check_same_thread(self, monkeypatch, tmp_path):
        """check_same_thread is a SQLite DBAPI argument; psycopg rejects it,
        and passing it would make the very first connection fail."""
        import app.database as database_module

        captured: dict = {}

        def fake_create_engine(url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return object()

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "database:\n  engine: postgresql\n  host: h\n  name: n\n  user: u\n"
            f"images:\n  path: {tmp_path / 'images'}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(database_module, "create_engine", fake_create_engine)
        monkeypatch.setattr(database_module, "get_config", lambda: load_config(config_path))
        monkeypatch.setattr(database_module, "_engine", None)

        database_module.get_engine()

        assert captured["url"].startswith("postgresql+psycopg://")
        assert "connect_args" not in captured["kwargs"]
        assert captured["kwargs"]["pool_pre_ping"] is True
        # Sized from the scan concurrency rather than fixed -- see
        # TestThePoolIsBigEnoughForTheScans.
        assert captured["kwargs"]["pool_size"] == 6 + 6


class TestNoMigrationWritesADialectSpecificDefault:
    """The mistake this catches, in the words of the server that catches it:

        column "email_enabled" is of type boolean but default expression is of
        type integer

    ``server_default=sa.text("0")`` is fine on SQLite, which has no boolean,
    and is refused by PostgreSQL. ``sa.false()`` means the same thing on both,
    because it is rendered by the dialect rather than by the author. Three
    migrations had the first form and were changed to the second; this is here
    so a fourth cannot be written.
    """

    #: What a boolean default may be spelled as.
    ALLOWED = {"sa.true()", "sa.false()", "sa.null()"}

    def boolean_defaults(self, path: Path) -> list[tuple[int, str]]:
        """Every ``server_default=`` on a ``sa.Boolean()`` column in a file."""
        found = []
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if ast.unparse(node.func) not in ("sa.Column", "Column"):
                continue
            arguments = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            positional = [ast.unparse(a) for a in node.args]
            typed = "sa.Boolean()" in positional or (
                "type_" in arguments and ast.unparse(arguments["type_"]) == "sa.Boolean()"
            )
            if typed and "server_default" in arguments:
                found.append((node.lineno, ast.unparse(arguments["server_default"])))
        return found

    def test_there_are_migrations_to_check(self):
        """A glob that quietly matches nothing would pass every test below."""
        assert len(MIGRATIONS) >= 14

    @pytest.mark.parametrize("path", MIGRATIONS, ids=lambda p: p.stem)
    def test_every_boolean_default_is_written_for_both_engines(self, path):
        offenders = [
            (line, default)
            for line, default in self.boolean_defaults(path)
            if default not in self.ALLOWED
        ]
        assert not offenders, (
            f"{path.name}: boolean server_default must be sa.true()/sa.false(), "
            f"which each dialect renders itself. Found {offenders}."
        )

    def test_the_check_would_notice_the_mistake_it_is_here_for(self, tmp_path):
        """A test that cannot fail is not a test."""
        bad = tmp_path / "0099_bad.py"
        bad.write_text(
            "import sqlalchemy as sa\n"
            'op.create_table("t", sa.Column("f", sa.Boolean(), '
            'server_default=sa.text("0")))\n',
            encoding="utf-8",
        )
        assert self.boolean_defaults(bad) == [(2, "sa.text('0')")]


class TestEveryMigrationIsIdempotent:
    """Running the chain twice is running it once.

    The application calls ``upgrade()`` on every start, ``make migrate`` is run
    by hand whenever anybody is unsure, and a production box gets both. So a
    revision that finds its own work already done has to shrug rather than
    raise, and each one asks the database what exists before changing it.

    This runs the whole chain forwards, backwards to base and forwards again on
    a throwaway SQLite file. The down-then-up leg is what catches a downgrade
    that does not undo what its upgrade did: the second pass fails on a table
    that is still there.
    """

    def chain(self, url: str):
        from alembic import command

        from app import migrations

        alembic_cfg = migrations.alembic_config()
        # env.py honors a URL the caller set, so this targets the temp file and
        # not the database the current mode configures. It did not always, and
        # the first version of this test ran the chain against the development
        # database instead.
        alembic_cfg.set_main_option("sqlalchemy.url", url)
        return command, alembic_cfg

    def tables(self, url: str) -> list[str]:
        engine = sa.create_engine(url)
        try:
            return sorted(sa.inspect(engine).get_table_names())
        finally:
            engine.dispose()

    def test_up_then_up_again_changes_nothing_and_raises_nothing(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'chain.db'}"
        command, alembic_cfg = self.chain(url)
        command.upgrade(alembic_cfg, "head")
        before = self.tables(url)
        command.upgrade(alembic_cfg, "head")
        assert self.tables(url) == before

    def test_up_down_up_arrives_at_the_same_schema(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'roundtrip.db'}"
        command, alembic_cfg = self.chain(url)
        command.upgrade(alembic_cfg, "head")
        first = self.tables(url)
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")
        assert self.tables(url) == first


#: A PostgreSQL database this suite may drop every table in. CI sets it.
POSTGRES_URL = os.environ.get("MILSURP_TEST_POSTGRES_URL", "")

#: The name has to say it is a test database, and this is not decoration.
#:
#: These tests run ``DROP SCHEMA public CASCADE``. On the machine this was
#: written on, the production database is ``milsurp`` and the test database is
#: ``milsurp_test`` -- five characters apart, on the same server, reached with
#: the same credentials. A typo in a shell variable should not be able to
#: destroy the first one, so the destructive tests refuse to run against any
#: database that is not named as a test database.
_TEST_DATABASE_NAME = re.compile(r"(^|[^a-z])test([^a-z]|$)", re.I)


def _refuse_unsafe_target(url: str) -> None:
    """Stop the whole run if the URL points somewhere it must not.

    A hard stop rather than a skip: a skip would hide the typo, and the next
    person would think the PostgreSQL half had run.
    """
    if not url:
        return
    name = sa.engine.make_url(url).database or ""
    if not _TEST_DATABASE_NAME.search(name):
        raise pytest.UsageError(
            f"MILSURP_TEST_POSTGRES_URL names the database {name!r}, which is not "
            f"marked as a test database. These tests DROP SCHEMA public CASCADE, so "
            f"they refuse to touch it. Point them at something like "
            f"'{name}_test' -- and create it first, so nothing else is at risk."
        )


def _refuse_unreachable_target(url: str) -> None:
    """Stop the run, once, if the server will not answer.

    Without this every one of the six PostgreSQL tests fails in its fixture and
    prints its own two-hundred-line SQLAlchemy traceback, so a wrong password
    produces twelve hundred lines saying one thing. One line is more useful,
    and a UsageError stops before any of them run.
    """
    if not url:
        return
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    # Broad on purpose: a refused password, a missing database and a server
    # that is not listening all get the same advice, and none of them should
    # reach the caller as a traceback.
    except Exception as exc:
        shown = sa.engine.make_url(url).render_as_string(hide_password=True)
        raise pytest.UsageError(
            f"MILSURP_TEST_POSTGRES_URL points at {shown}, which will not answer:\n"
            f"    {str(getattr(exc, 'orig', exc)).strip().splitlines()[0]}\n"
            f"Check the password is the real one and not a placeholder, and that the "
            f"database exists:\n"
            f'    sudo -u postgres psql -c "CREATE DATABASE milsurp_test OWNER milsurp;"\n'
            f"    sudo -u postgres psql -d milsurp_test "
            f'-c "GRANT ALL ON SCHEMA public TO milsurp;"'
        ) from None
    finally:
        engine.dispose()


_refuse_unsafe_target(POSTGRES_URL)
_refuse_unreachable_target(POSTGRES_URL)

needs_postgres = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="MILSURP_TEST_POSTGRES_URL is not set (a database this suite may empty)",
)


@needs_postgres
class TestTheChainRunsOnPostgreSQLToo:
    """The static checks above are a proxy; this is the thing itself."""

    @pytest.fixture
    def empty(self):
        engine = sa.create_engine(POSTGRES_URL)
        with engine.begin() as connection:
            connection.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        yield engine
        engine.dispose()

    def chain(self):
        from alembic import command

        from app import migrations

        alembic_cfg = migrations.alembic_config()
        alembic_cfg.set_main_option("sqlalchemy.url", POSTGRES_URL)
        return command, alembic_cfg

    def test_the_whole_chain_applies(self, empty):
        command, alembic_cfg = self.chain()
        command.upgrade(alembic_cfg, "head")
        tables = set(sa.inspect(empty).get_table_names())
        assert {"users", "sites", "items", "saved_searches", "alembic_version"} <= tables

    def test_and_is_idempotent_there_as_well(self, empty):
        command, alembic_cfg = self.chain()
        command.upgrade(alembic_cfg, "head")
        before = sorted(sa.inspect(empty).get_table_names())
        command.upgrade(alembic_cfg, "head")
        assert sorted(sa.inspect(empty).get_table_names()) == before

    def test_and_goes_back_down_and_up(self, empty):
        command, alembic_cfg = self.chain()
        command.upgrade(alembic_cfg, "head")
        first = sorted(sa.inspect(empty).get_table_names())
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")
        assert sorted(sa.inspect(empty).get_table_names()) == first

    def test_the_orm_and_the_migrations_agree_about_the_tables(self, empty):
        """Nothing in the models is missing a migration, and nothing in the
        migrations is a table the application has forgotten about."""
        from app.database import Base

        command, alembic_cfg = self.chain()
        command.upgrade(alembic_cfg, "head")
        built = set(sa.inspect(empty).get_table_names()) - {"alembic_version"}
        assert built == set(Base.metadata.tables)


def importer():
    """The SQLite -> PostgreSQL copier, loaded from scripts/."""
    import importlib.util

    path = BACKEND_DIR.parent / "scripts" / "sqlite-to-postgres.py"
    spec = importlib.util.spec_from_file_location("sqlite_to_postgres", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheImporterKnowsWhatItCannotInsertInOrder:
    """A table whose rows point at other rows of the same table.

    PostgreSQL checks a foreign key the moment the row lands, and nothing
    orders one row of a table against another, so a merged caliber whose
    ``merged_into_id`` names a row that has not been inserted yet is a
    ForeignKeyViolation. SQLite never noticed, because it does not enforce
    foreign keys unless asked to -- which is why this only appeared on the
    first real copy.
    """

    def test_it_finds_exactly_the_tables_that_reference_themselves(self):
        from app.database import Base

        module = importer()
        found = {
            table.name: module.self_references(table)
            for table in Base.metadata.sorted_tables
            if module.self_references(table)
        }
        assert found == {
            "calibers": ["merged_into_id"],
            "firearm_models": ["merged_into_id"],
            "manufacturers": ["merged_into_id"],
        }

    def test_a_table_with_no_self_reference_gets_the_normal_path(self):
        from app.database import Base

        module = importer()
        assert module.self_references(Base.metadata.tables["items"]) == []


@needs_postgres
class TestTheImporterCarriesEverythingAcross:
    """The copy itself, over a schema built by the migration chain on both
    sides -- which is the only way the column types line up."""

    @pytest.fixture
    def both(self, tmp_path):
        from alembic import command

        from app import migrations

        sqlite_url = f"sqlite:///{tmp_path / 'source.db'}"
        for url in (sqlite_url, POSTGRES_URL):
            if url == POSTGRES_URL:
                engine = sa.create_engine(url)
                with engine.begin() as connection:
                    connection.execute(sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
                engine.dispose()
            alembic_cfg = migrations.alembic_config()
            alembic_cfg.set_main_option("sqlalchemy.url", url)
            command.upgrade(alembic_cfg, "head")

        source = sa.create_engine(sqlite_url)
        target = sa.create_engine(POSTGRES_URL)
        yield source, target
        source.dispose()
        target.dispose()

    def test_booleans_datetimes_and_self_references_all_survive(self, both):
        from datetime import datetime

        from app.database import Base

        source, target = both
        module = importer()
        sites = Base.metadata.tables["sites"]
        calibers = Base.metadata.tables["calibers"]
        # Naive on purpose: every datetime in this schema is UTC stored
        # without a timezone, because SQLite has no type for one.
        stamp = datetime(2026, 3, 1, 12, 30, 45, 123456)  # noqa: DTZ001

        with source.begin() as connection:
            connection.execute(
                sites.insert(),
                [
                    {
                        "id": 7,
                        "slug": "a-shop",
                        "name": "A Shop",
                        "base_url": "https://a.test/",
                        # SQLite stores these as 0 and 1; PostgreSQL refuses an
                        # integer in a boolean column outright.
                        "enabled": True,
                        "requires_browser": False,
                        "is_available": True,
                        "scan_interval_minutes": 1440,
                        "created_at": stamp,
                        "updated_at": stamp,
                    }
                ],
            )
            connection.execute(
                calibers.insert(),
                [
                    # Deliberately in the order that breaks a naive copy: the
                    # row that points is inserted before the row pointed at.
                    {"id": 1, "name": ".303 Brit", "status": "MERGED", "merged_into_id": 2},
                    {"id": 2, "name": ".303 British", "status": "APPROVED", "merged_into_id": None},
                ],
            )

        for table in (sites, calibers):
            module.copy_table(source, target, table, quiet=True)

        with target.connect() as connection:
            site = connection.execute(sa.select(sites)).one()._mapping
            assert site["enabled"] is True
            assert site["requires_browser"] is False
            assert site["created_at"] == stamp
            merged = connection.execute(
                sa.select(calibers.c.merged_into_id).where(calibers.c.id == 1)
            ).scalar_one()
            assert merged == 2

    def test_the_next_insert_does_not_collide_with_a_carried_over_id(self, both):
        """Ids come across as they are -- they are in URLs and in emails that
        have already gone out -- so every sequence has to be wound past them."""
        from datetime import datetime

        from app.database import Base

        source, target = both
        module = importer()
        sites = Base.metadata.tables["sites"]
        stamp = datetime(2026, 3, 1, 12, 30, 45)  # noqa: DTZ001
        with source.begin() as connection:
            connection.execute(
                sites.insert(),
                [
                    {
                        "id": 500,
                        "slug": "s",
                        "name": "S",
                        "base_url": "https://s.test/",
                        "created_at": stamp,
                        "updated_at": stamp,
                    }
                ],
            )
        module.copy_table(source, target, sites, quiet=True)
        module.reset_sequences(target)

        with target.begin() as connection:
            fresh = connection.execute(
                sites.insert().returning(sites.c.id),
                {
                    "slug": "t",
                    "name": "T",
                    "base_url": "https://t.test/",
                    "created_at": stamp,
                    "updated_at": stamp,
                },
            ).scalar_one()
        assert fresh == 501


class TestDbupdateExplainsItselfWhenItCannotStart:
    """The failure that actually happened, and the message it deserves.

    `scripts/dbupdate.py` run bare on a development checkout is in *production*
    mode, so an unset `images:` resolves to /etc/milsurp/images -- which an
    ordinary account cannot create. Every path below it calls
    ensure_directories() (Alembic's config does, the engine does), so the
    PermissionError used to surface as whatever it happened to break: it was
    caught by the connection check and reported as

        error: cannot connect to postgresql://milsurp@localhost:5432/milsurp
               [Errno 13] Permission denied: '/etc/milsurp'

    which names the wrong subsystem entirely -- nothing had tried to connect.
    """

    def dbupdate(self):
        import importlib.util

        path = BACKEND_DIR.parent / "scripts" / "dbupdate.py"
        spec = importlib.util.spec_from_file_location("dbupdate", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def config_at(self, images: Path, tmp_path: Path):
        written = tmp_path / "config.yaml"
        written.write_text(
            f"database:\n  path: {tmp_path / 'x.db'}\nimages:\n  path: {images}\n",
            encoding="utf-8",
        )
        return load_config(written)

    def test_an_unwritable_image_directory_is_named_as_itself(self, tmp_path, capsys):
        locked = tmp_path / "locked"
        locked.mkdir(mode=0o500)
        try:
            config = self.config_at(locked / "images", tmp_path)
            assert self.dbupdate().check_directories(config) is False
        finally:
            locked.chmod(0o700)

        printed = capsys.readouterr().err
        assert "cannot create" in printed
        assert "images" in printed
        # The three remedies, because which one applies depends on the machine.
        assert "sudo install -d" in printed
        assert "images.path" in printed
        assert "MILSURP_ENV=dev" in printed

    def test_a_directory_it_can_make_is_simply_made(self, tmp_path):
        config = self.config_at(tmp_path / "images", tmp_path)
        assert self.dbupdate().check_directories(config) is True
        assert (tmp_path / "images").is_dir()

    def test_the_connection_check_does_not_touch_the_directories(self, tmp_path, capsys):
        """Which is what stopped it blaming the server for a mkdir. It reports
        a refused connection as a refused connection, and nothing else."""
        written = tmp_path / "config.yaml"
        written.write_text(
            "database:\n"
            "  engine: postgresql\n"
            "  host: 127.0.0.1\n"
            "  port: 1\n"  # nothing listens here
            "  name: milsurp\n"
            "  user: milsurp\n"
            "images:\n  path: /proc/cannot-create-this\n",
            encoding="utf-8",
        )
        config = load_config(written)

        assert self.dbupdate().check_reachable(config) is False

        printed = capsys.readouterr().err
        assert "cannot connect to postgresql://milsurp@127.0.0.1:1/milsurp" in printed
        assert "Permission denied" not in printed
        assert not Path("/proc/cannot-create-this").exists()


class TestTheScanConcurrencyFollowsTheEngine:
    """How many sites are scanned at once is a property of the database.

    Two on SQLite because it has one writer and a scan commits after every
    listing, so more scan threads means more contention for that one lock.
    Six on PostgreSQL because that constraint is gone and the ceiling becomes
    the connection pool instead — a scan holds one connection for its whole
    run, which for a large vendor is hours.

    The number is a default, not a rule: naming it in config.yaml wins on
    either engine, which is the point of it being config at all.
    """

    def config_for(self, tmp_path: Path, yaml_text: str):
        written = tmp_path / "config.yaml"
        written.write_text(yaml_text + f"images:\n  path: {tmp_path / 'images'}\n", "utf-8")
        return load_config(written, mode="dev")

    SQLITE = "database:\n  path: /tmp/x.db\n"
    POSTGRES = "database:\n  engine: postgresql\n  host: h\n  name: milsurp\n  user: u\n"

    def test_sqlite_stays_at_two(self, tmp_path):
        config = self.config_for(tmp_path, self.SQLITE)
        assert config.scheduler.max_concurrent_scans == 2

    def test_postgresql_gets_six(self, tmp_path):
        config = self.config_for(tmp_path, self.POSTGRES)
        assert config.scheduler.max_concurrent_scans == 6

    def test_a_file_that_names_it_wins_on_either_engine(self, tmp_path):
        named = "scheduler:\n  max_concurrent_scans: 3\n"
        assert self.config_for(tmp_path, self.SQLITE + named).scheduler.max_concurrent_scans == 3
        assert self.config_for(tmp_path, self.POSTGRES + named).scheduler.max_concurrent_scans == 3

    def test_the_two_defaults_are_the_ones_that_are_documented(self):
        """config.yaml.sample quotes these numbers; keep them honest."""
        from app.config import CONCURRENT_SCANS

        assert CONCURRENT_SCANS == {"sqlite": 2, "postgresql": 6}


class TestThePoolIsBigEnoughForTheScans:
    """Raising the scan count must not starve the API of connections.

    A scan holds one connection for as long as it runs. A pool that seats every
    scan and nothing else means a request waits on a checkout that only frees
    when a scan finishes — the same starvation the move off SQLite was meant to
    end, one layer down, and a miserable thing to diagnose because it only
    happens while scans are running.
    """

    def config_for(self, tmp_path: Path, yaml_text: str):
        written = tmp_path / "config.yaml"
        written.write_text(yaml_text + f"images:\n  path: {tmp_path / 'images'}\n", "utf-8")
        return load_config(written, mode="dev")

    BASE = "database:\n  engine: postgresql\n  host: h\n  name: milsurp\n  user: u\n"

    def test_the_default_pool_seats_the_default_scans_with_room_to_spare(self, tmp_path):
        from app.main import MIN_POOL_HEADROOM

        config = self.config_for(tmp_path, self.BASE)
        capacity = config.database.pool_size + config.database.max_overflow
        assert capacity - config.scheduler.max_concurrent_scans >= MIN_POOL_HEADROOM

    def test_raising_the_scans_raises_the_pool_with_them(self, tmp_path):
        config = self.config_for(tmp_path, self.BASE + "scheduler:\n  max_concurrent_scans: 12\n")
        assert config.database.pool_size == 18

    def test_but_a_pool_size_that_was_asked_for_is_left_alone(self, tmp_path):
        """An operator who set a number meant it; this only fills in a blank."""
        config = self.config_for(
            tmp_path,
            "database:\n  engine: postgresql\n  host: h\n  name: milsurp\n  user: u\n"
            "  pool_size: 4\nscheduler:\n  max_concurrent_scans: 12\n",
        )
        assert config.database.pool_size == 4

    def test_and_that_case_is_warned_about_at_startup(self, tmp_path):
        """Because it is the one shape the defaults cannot protect."""
        from app.main import pool_complaint

        config = self.config_for(
            tmp_path,
            "database:\n  engine: postgresql\n  host: h\n  name: milsurp\n  user: u\n"
            "  pool_size: 4\n  max_overflow: 0\nscheduler:\n  max_concurrent_scans: 12\n",
        )
        complaint = pool_complaint(config)
        assert complaint is not None
        assert "max_concurrent_scans is 12" in complaint
        assert "pool_size" in complaint

    def test_a_sane_pool_says_nothing(self, tmp_path):
        from app.main import pool_complaint

        assert pool_complaint(self.config_for(tmp_path, self.BASE)) is None

    def test_sqlite_has_no_pool_to_warn_about(self, tmp_path):
        from app.main import pool_complaint

        assert pool_complaint(self.config_for(tmp_path, "database:\n  path: /tmp/x.db\n")) is None
