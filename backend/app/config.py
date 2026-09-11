"""Configuration loading.

Configuration comes from a single YAML file. The file is searched for in this
order, and the first one that exists wins:

  1. ``$MILSURP_CONFIG``                  (explicit override, any path)
  2. ``<repo root>/config.yaml``          (development convenience)
  3. ``/etc/milsurp/config.yaml``         (the production location)

Anything not named in the file falls back to a built-in default. Defaults for
on-disk state depend on the run mode (``$MILSURP_ENV``): in ``dev`` the database
and image store live inside the repository, in ``production`` they live under
``/etc/milsurp``. Either can always be overridden in the YAML file.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import yaml

# backend/app/config.py -> backend/app -> backend -> repo root
ROOT_DIR = Path(__file__).resolve().parents[2]

ETC_DIR = Path("/etc/milsurp")
CONFIG_FILENAME = "config.yaml"

#: Directory permissions for the image store: owner-only (rwx------).
SECURE_DIR_MODE = 0o700


class ConfigError(RuntimeError):
    """Raised when the configuration file is present but unusable."""


def _env_mode() -> str:
    mode = os.environ.get("MILSURP_ENV", "production").strip().lower()
    return "dev" if mode in ("dev", "development", "local") else "production"


def config_search_path() -> list[Path]:
    """Every location that is checked for a config file, in priority order."""
    paths: list[Path] = []
    override = os.environ.get("MILSURP_CONFIG")
    if override:
        paths.append(Path(override).expanduser())
    paths.append(ROOT_DIR / CONFIG_FILENAME)
    paths.append(ETC_DIR / CONFIG_FILENAME)
    return paths


def find_config_file() -> Path | None:
    for path in config_search_path():
        if path.is_file():
            return path
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return data


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"config section '{name}' must be a mapping")
    return value


@dataclass(frozen=True)
class SecurityConfig:
    # A server-side secret mixed into every password before hashing ("pepper").
    # Argon2 already generates a unique random salt per password; the pepper is
    # the extra secret that lives in the config file rather than the database,
    # so a stolen database alone cannot be attacked offline.
    password_pepper: str = ""
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 720
    # Argon2id cost parameters. The defaults follow the OWASP recommendation of
    # 19 MiB of memory, 2 iterations and 1 degree of parallelism.
    argon2_time_cost: int = 2
    argon2_memory_cost: int = 19456
    argon2_parallelism: int = 1
    #: Minimum accepted password length. Length dominates resistance to offline
    #: attack, so this is the policy's main lever. Read fresh on every start, so
    #: raising it takes effect at the next restart without a code change.
    #: Existing passwords are not re-validated — the rule applies when a
    #: password is set or changed.
    min_password_length: int = 12
    #: Character-class requirements. Each is applied only when true, so the
    #: complexity rules are derived from whichever are switched on. All default
    #: to false: length is what actually resists offline attack, and forcing
    #: classes tends to produce predictable substitutions (P@ssw0rd!) rather
    #: than stronger secrets.
    require_uppercase: bool = False
    require_lowercase: bool = False
    require_numeric: bool = False
    require_special: bool = False


@dataclass(frozen=True)
class AdminSeedConfig:
    username: str = "admin"
    email: str = "admin@example.com"
    password: str = ""


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool = False
    #: Where "request access" messages are delivered. Falls back to the
    #: from/username address when unset.
    support_email: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    # "starttls" (587), "ssl" (465) or "none".
    smtp_security: str = "starttls"
    username: str = ""
    password: str = ""
    from_address: str = ""
    from_name: str = "Milsurp Watch"
    timeout_seconds: int = 30

    @property
    def sender(self) -> str:
        address = self.from_address or self.username
        return f"{self.from_name} <{address}>" if self.from_name else address

    @property
    def support_address(self) -> str:
        return self.support_email or self.from_address or self.username


@dataclass(frozen=True)
class RecaptchaConfig:
    """Google reCAPTCHA, used only on the public "request access" form.

    That form is the one unauthenticated, email-sending endpoint in the
    application, so it is the one place a bot could burn the SMTP quota or use
    the server to relay junk. Everything else already requires a session.
    """

    enabled: bool = False
    site_key: str = ""  # public; rendered into the page
    secret_key: str = ""  # private; used server-side to verify
    # v3 returns a 0.0-1.0 score instead of a pass/fail; below this is rejected.
    minimum_score: float = 0.5
    verify_url: str = "https://www.google.com/recaptcha/api/siteverify"


@dataclass(frozen=True)
class AccessRequestConfig:
    """The public "request access" form (production only)."""

    enabled: bool = True
    #: Per-IP submissions allowed per hour.
    rate_limit_per_hour: int = 3


@dataclass(frozen=True)
class ServerConfig:
    dev_host: str = "127.0.0.1"
    dev_preferred_port: int = 8730
    dev_port_range: tuple[int, int] = (8730, 8799)
    prod_host: str = "127.0.0.1"
    # The port nginx terminates TLS on. Port 80 redirects here with a 301.
    prod_port: int = 443
    prod_http_redirect_port: int = 80
    # The port the Python app itself binds behind nginx.
    prod_app_port: int = 8730
    public_url: str = "https://localhost"


#: Concurrent scans, per engine.
#:
#: Two on SQLite because it has one writer. A scan commits after every listing
#: -- it must, or it would hold the write lock across a twenty-second fetch --
#: so more scan threads means more contention for that one lock, and every
#: write the web application attempts waits behind them.
#:
#: Six on PostgreSQL because that constraint is gone: concurrent writers do not
#: block each other, and the real ceiling becomes the connection pool. A scan
#: holds one connection for its whole duration, which for a large vendor is
#: hours, so six leaves comfortable headroom in a pool of fifteen for the API
#: and the photo worker. It is not a throughput claim: these scans are bounded
#: by vendor rate limits, not by the database, so the win is in how many
#: *different* sites can be in flight, not in how fast any one of them runs.
CONCURRENT_SCANS = {"sqlite": 2, "postgresql": 6}

#: Connections kept beyond the scans, for the API, the scheduler and the photo
#: worker. The pool's default size is derived from the scan concurrency plus
#: this, so raising one does not quietly starve the other.
POOL_HEADROOM = 6


@dataclass(frozen=True)
class SchedulerConfig:
    enabled: bool = True
    # How often the scheduler wakes up to look for sites that are due.
    tick_seconds: int = 60
    # How often it looks for users whose email digest is due.
    digest_tick_seconds: int = 300
    # How often it works through the photo download queue between scans. A scan
    # caps its own image downloads so a first pass over a large catalog cannot
    # run for hours; without this the remainder would drain one scan at a time,
    # which on a daily cadence is days of listings with no pictures.
    photo_tick_seconds: int = 180
    #: How many sites are scanned at once. **The default depends on the
    #: database engine** -- see CONCURRENT_SCANS. Naming it in config.yaml
    #: overrides that, whichever engine is in use.
    max_concurrent_scans: int = 2
    # Refuse to start a scan if one for the same site has been running longer
    # than this; the previous run is marked failed and reaped.
    scan_timeout_minutes: int = 120


@dataclass(frozen=True)
class DatabaseConfig:
    """Which database to talk to, and how to reach it.

    Two engines are supported and both are first-class: SQLite, which is what a
    development checkout and the test suite use, and PostgreSQL, which is what
    a deployment that has outgrown one writer should use. **Every schema change
    in this project has to work on both** -- see the rule in README.md under
    "Two engines, one schema".

    Under ``sqlite`` only :attr:`path` is read. Under ``postgresql`` the
    connection is assembled from the host/port/name/user/password fields, or
    taken verbatim from :attr:`url` when that is set -- the escape hatch for a
    connection string that needs something this dataclass does not model (a
    Unix socket directory, a client certificate, a connection pooler).
    """

    engine: str = "sqlite"
    #: The SQLite file. Kept meaningful under PostgreSQL too, because it is
    #: where the importer reads from and what the backup service snapshots.
    path: Path = Path("milsurp.db")
    host: str = "localhost"
    port: int = 5432
    name: str = "milsurp"
    user: str = "milsurp"
    password: str = ""
    #: libpq's ``sslmode``. Blank leaves libpq's own default in place, which is
    #: ``prefer``; a deployment reaching across a network should say ``require``
    #: or stronger.
    sslmode: str = ""
    #: A complete SQLAlchemy URL, used as-is when present.
    url: str = ""
    #: Connection pool. Ignored under SQLite, which uses one file handle.
    pool_size: int = 5
    max_overflow: int = 10
    #: Recycle a pooled connection after this long. Below the idle timeout of
    #: whatever sits between the app and the server -- pgbouncer, a firewall --
    #: so a connection is never handed out after the far end has dropped it.
    pool_recycle_seconds: int = 1800

    @property
    def is_sqlite(self) -> bool:
        return self.engine == "sqlite"

    @property
    def is_postgres(self) -> bool:
        return self.engine == "postgresql"

    @property
    def sqlalchemy_url(self) -> str:
        if self.url:
            return self.url
        if self.is_postgres:
            auth = quote(self.user, safe="")
            if self.password:
                auth += ":" + quote(self.password, safe="")
            query = f"?sslmode={quote(self.sslmode, safe='')}" if self.sslmode else ""
            return (
                f"postgresql+psycopg://{auth}@{self.host}:{self.port}/"
                f"{quote(self.name, safe='')}{query}"
            )
        return f"sqlite:///{self.path}"

    def describe(self) -> str:
        """What to show a human. Never includes the password."""
        if self.is_postgres:
            return f"postgresql://{self.user}@{self.host}:{self.port}/{self.name}"
        return str(self.path)


@dataclass(frozen=True)
class BackupConfig:
    """Rolling snapshots of the database. See :mod:`app.services.backup`."""

    enabled: bool = True
    directory: Path = Path("backups")
    #: How many to keep. Ten daily snapshots is a bit over a week, which is
    #: long enough to notice that something went wrong and still have the
    #: state from before it.
    keep: int = 10
    interval_hours: int = 24


@dataclass(frozen=True)
class RobotsException:
    """One narrow, deliberate exception to a host's robots.txt.

    ``obey_robots`` already exists and is all-or-nothing: switching it off
    turns every restriction off everywhere, which is a far bigger decision than
    the one anybody actually wants to make. This is the small version -- one
    host, named paths, and a reason that has to be written down.

    **The reason is required, and it is the point of the dataclass.** An
    exception with no stated reason is indistinguishable next year from a
    mistake, so a blank one is refused at load time rather than accepted
    quietly. Every use is logged, once per scan, with that reason attached.

    Joe Salter is the case this was built for: their robots.txt disallows
    ``/image``, and every product photograph OpenCart serves lives under it, so
    the choice was pictures or nothing.
    """

    #: Exact host, matched case-insensitively. No wildcards: an exception that
    #: can spread to hosts nobody listed is not a narrow one.
    host: str
    #: Path prefixes this exception covers, e.g. ``("/image/",)``. Never "/".
    prefixes: tuple[str, ...]
    #: Why this exists and who decided. Required.
    reason: str

    def covers(self, url: str) -> bool:
        parts = urlparse(url)
        if parts.netloc.lower() != self.host.lower():
            return False
        path = parts.path or "/"
        return any(path.startswith(prefix) for prefix in self.prefixes)


@dataclass(frozen=True)
class ScrapingConfig:
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    # Honor robots.txt: its Disallow rules and its Crawl-delay. On by default
    # and meant to stay on. It is here as a setting because a vendor may give a
    # deployment explicit permission to ignore their rules, and because a test
    # needs to be able to turn it off without a network.
    obey_robots: bool = True
    request_timeout: int = 30
    # Politeness delay between requests to the same host, in seconds.
    request_delay: float = 1.0
    max_retries: int = 4
    download_images: bool = True
    headless: bool = True
    chrome_binary: str | None = None
    chromedriver_path: str | None = None
    # Hard ceiling on pages/scroll iterations, so a misbehaving site cannot
    # make a scan run forever.
    max_pages: int = 60
    # Photos fetched per scan. A first scan of a large catalog can queue
    # thousands; downloading them all in one run would stretch it for hours, so
    # the remainder is carried to the next scan. Raise it to drain a backlog
    # faster, at the cost of a longer run and more traffic in one burst.
    max_photo_downloads_per_scan: int = 400
    # Narrow, deliberate exceptions to individual hosts' robots.txt. Empty by
    # default and meant to stay that way; see RobotsException.
    robots_exceptions: tuple[RobotsException, ...] = ()


@dataclass(frozen=True)
class Config:
    mode: str
    source_path: Path | None
    database: DatabaseConfig
    images_path: Path
    security: SecurityConfig
    admin: AdminSeedConfig
    email: EmailConfig
    server: ServerConfig
    scheduler: SchedulerConfig
    scraping: ScrapingConfig
    backups: BackupConfig
    recaptcha: RecaptchaConfig
    access_requests: AccessRequestConfig
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_dev(self) -> bool:
        return self.mode == "dev"

    @property
    def database_path(self) -> Path:
        """The SQLite file. Still resolved under PostgreSQL: it is what the
        importer reads from and what a pre-migration snapshot is taken of."""
        return self.database.path

    @property
    def database_url(self) -> str:
        return self.database.sqlalchemy_url

    @property
    def host(self) -> str:
        return self.server.dev_host if self.is_dev else self.server.prod_host

    def ensure_directories(self) -> None:
        """Create the database and image directories with safe permissions."""
        # A PostgreSQL server owns its own storage; there is no local directory
        # to make, and on a production box the SQLite default path may well sit
        # somewhere this account cannot write.
        if self.database.is_sqlite:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.images_path.mkdir(parents=True, exist_ok=True)
        # The image store holds downloaded photos and is not served by nginx;
        # keep it readable only by the account that runs the app.
        # Someone else may own the directory (a shared deployment); leave
        # whatever policy the operator already set in place.
        with contextlib.suppress(PermissionError):
            self.images_path.chmod(SECURE_DIR_MODE)


def _default_state_dir(mode: str) -> Path:
    """Where the database and images live when the YAML file is silent."""
    return ROOT_DIR if mode == "dev" else ETC_DIR


def _resolve_path(value: Any, base: Path) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (base / path)


#: The engines this application knows how to talk to. Aliases are accepted
#: because "postgres" and "psql" are what people type.
_ENGINE_ALIASES = {
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "psql": "postgresql",
    "pg": "postgresql",
}


def _database(section: dict[str, Any], state_dir: Path) -> DatabaseConfig:
    """Read the ``database:`` block.

    The engine is inferred rather than required: a file that only says ``path``
    is the shape every existing deployment already has, and it must keep
    meaning SQLite. Naming any PostgreSQL field -- or a ``url:`` that starts
    with ``postgres`` -- is taken as asking for PostgreSQL, so the smallest
    working block is four lines and no ``engine:`` key.
    """
    url = str(section.get("url", "") or "").strip()
    declared = str(section.get("engine", "") or "").strip().lower()
    if declared:
        engine = _ENGINE_ALIASES.get(declared)
        if engine is None:
            raise ConfigError(f"database.engine '{declared}' is not one of: sqlite, postgresql")
    elif url:
        engine = "postgresql" if url.startswith(("postgres://", "postgresql")) else "sqlite"
    elif any(key in section for key in ("host", "name", "user", "password", "port")):
        engine = "postgresql"
    else:
        engine = "sqlite"

    db_path = section.get("path")
    path = _resolve_path(db_path, ROOT_DIR) if db_path else state_dir / "milsurp.db"

    if engine == "sqlite":
        return DatabaseConfig(engine="sqlite", path=path, url=url)

    # psycopg is the driver this project uses; an operator who pastes the URL
    # libpq prints ("postgresql://...") should not have to know that.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    try:
        port = int(section.get("port", 5432))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"database.port must be a number: {section.get('port')!r}") from exc

    return DatabaseConfig(
        engine="postgresql",
        path=path,
        host=str(section.get("host", "localhost") or "localhost"),
        port=port,
        name=str(section.get("name", "milsurp") or "milsurp"),
        user=str(section.get("user", "milsurp") or "milsurp"),
        password=str(section.get("password", "") or ""),
        sslmode=str(section.get("sslmode", "") or ""),
        url=url,
        pool_size=int(section.get("pool_size", 5)),
        max_overflow=int(section.get("max_overflow", 10)),
        pool_recycle_seconds=int(section.get("pool_recycle_seconds", 1800)),
    )


def _robots_exceptions(raw: Any) -> tuple[RobotsException, ...]:
    """Parse ``scraping.robots_exceptions`` from the config file.

    Strict on purpose. Every failure here is refused rather than skipped,
    because the quiet failure mode -- an exception that silently does not apply
    -- is the one that gets debugged by turning ``obey_robots`` off.
    """
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("scraping.robots_exceptions must be a list")
    found: list[RobotsException] = []
    for index, entry in enumerate(raw):
        where = f"scraping.robots_exceptions[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} must be a mapping")
        host = str(entry.get("host", "")).strip()
        reason = str(entry.get("reason", "")).strip()
        prefixes = entry.get("prefixes") or []
        if not host or "/" in host:
            raise ConfigError(f"{where}.host must be a bare hostname")
        if not reason:
            # The whole design rests on this. An exception nobody explained is
            # indistinguishable from a mistake once the person who made it has
            # moved on.
            raise ConfigError(f"{where}.reason is required: say why this exception exists")
        if not isinstance(prefixes, list) or not prefixes:
            raise ConfigError(f"{where}.prefixes must be a non-empty list of path prefixes")
        clean: list[str] = []
        for prefix in prefixes:
            text = str(prefix).strip()
            if not text.startswith("/"):
                raise ConfigError(f"{where}.prefixes entries must start with '/': {text!r}")
            if text == "/":
                # "/" is not an exception, it is obey_robots: false wearing a
                # disguise -- and one that would not be obvious in a review.
                raise ConfigError(
                    f"{where}.prefixes may not be '/': that is the whole site, "
                    "which is scraping.obey_robots, not an exception"
                )
            clean.append(text)
        found.append(RobotsException(host=host, prefixes=tuple(clean), reason=reason))
    return tuple(found)


def _size_the_pool(
    database: DatabaseConfig, section: dict[str, Any], scheduler: SchedulerConfig
) -> DatabaseConfig:
    """Make sure the pool can hold every scan plus everything else.

    A scan holds one connection for as long as it runs, which for a large
    vendor is hours. Raising ``max_concurrent_scans`` without raising the pool
    would leave the API waiting on a checkout that only finishes when a scan
    does -- the same starvation the move off SQLite was meant to end, one layer
    down.

    Only ever raises, and only when the file did not name ``pool_size``: an
    operator who set a size meant it.
    """
    if not database.is_postgres or "pool_size" in section:
        return database
    wanted = scheduler.max_concurrent_scans + POOL_HEADROOM
    if wanted <= database.pool_size:
        return database
    return replace(database, pool_size=wanted)


def load_config(path: Path | None = None, mode: str | None = None) -> Config:
    """Read the config file (if any) and merge it over the defaults."""
    mode = mode or _env_mode()
    source = path or find_config_file()
    data = _load_yaml(source) if source else {}

    state_dir = _default_state_dir(mode)

    database = _database(_section(data, "database"), state_dir)

    img_section = _section(data, "images")
    img_path = img_section.get("path")
    if img_path:
        images_path = _resolve_path(img_path, ROOT_DIR)
    elif mode == "dev":
        # Under data/ rather than the repository root: the root-level images/
        # directory holds committed documentation screenshots, and mixing a
        # gitignored photo store into it would be a trap.
        images_path = ROOT_DIR / "data" / "images"
    else:
        images_path = state_dir / "images"

    sec = _section(data, "security")
    security = SecurityConfig(
        password_pepper=str(sec.get("password_pepper", "") or ""),
        jwt_secret=str(sec.get("jwt_secret", "") or ""),
        jwt_algorithm=str(sec.get("jwt_algorithm", "HS256")),
        access_token_minutes=int(sec.get("access_token_minutes", 720)),
        argon2_time_cost=int(sec.get("argon2_time_cost", 2)),
        argon2_memory_cost=int(sec.get("argon2_memory_cost", 19456)),
        argon2_parallelism=int(sec.get("argon2_parallelism", 1)),
        min_password_length=int(sec.get("min_password_length", 12)),
        require_uppercase=bool(sec.get("require_uppercase", False)),
        require_lowercase=bool(sec.get("require_lowercase", False)),
        require_numeric=bool(sec.get("require_numeric", False)),
        require_special=bool(sec.get("require_special", False)),
    )

    adm = _section(data, "admin")
    admin = AdminSeedConfig(
        username=str(adm.get("username", "admin")),
        email=str(adm.get("email", "admin@example.com")),
        password=str(adm.get("password", "") or ""),
    )

    mail = _section(data, "email")
    email = EmailConfig(
        enabled=bool(mail.get("enabled", False)),
        support_email=str(mail.get("support_email", "") or ""),
        smtp_host=str(mail.get("smtp_host", "smtp.gmail.com")),
        smtp_port=int(mail.get("smtp_port", 587)),
        smtp_security=str(mail.get("smtp_security", "starttls")).lower(),
        username=str(mail.get("username", "") or ""),
        password=str(mail.get("password", "") or ""),
        from_address=str(mail.get("from_address", "") or ""),
        from_name=str(mail.get("from_name", "Milsurp Watch")),
        timeout_seconds=int(mail.get("timeout_seconds", 30)),
    )

    srv = _section(data, "server")
    dev_srv = _section(srv, "dev")
    prod_srv = _section(srv, "production")
    port_range = dev_srv.get("port_range", [8730, 8799])
    if not (isinstance(port_range, (list, tuple)) and len(port_range) == 2):
        raise ConfigError("server.dev.port_range must be a two-element list [low, high]")
    server = ServerConfig(
        dev_host=str(dev_srv.get("host", "127.0.0.1")),
        dev_preferred_port=int(dev_srv.get("preferred_port", 8730)),
        dev_port_range=(int(port_range[0]), int(port_range[1])),
        prod_host=str(prod_srv.get("host", "127.0.0.1")),
        prod_port=int(prod_srv.get("port", 443)),
        prod_http_redirect_port=int(prod_srv.get("http_redirect_port", 80)),
        prod_app_port=int(prod_srv.get("app_port", 8730)),
        public_url=str(prod_srv.get("public_url", "https://localhost")).rstrip("/"),
    )

    sch = _section(data, "scheduler")
    scheduler = SchedulerConfig(
        enabled=bool(sch.get("enabled", True)),
        tick_seconds=int(sch.get("tick_seconds", 60)),
        digest_tick_seconds=int(sch.get("digest_tick_seconds", 300)),
        max_concurrent_scans=int(
            sch.get("max_concurrent_scans", CONCURRENT_SCANS[database.engine])
        ),
        scan_timeout_minutes=int(sch.get("scan_timeout_minutes", 120)),
    )
    database = _size_the_pool(database, _section(data, "database"), scheduler)

    scr = _section(data, "scraping")
    sel = _section(scr, "selenium")
    defaults = ScrapingConfig()
    scraping = ScrapingConfig(
        user_agent=str(scr.get("user_agent", defaults.user_agent)),
        obey_robots=bool(scr.get("obey_robots", True)),
        request_timeout=int(scr.get("request_timeout", 30)),
        request_delay=float(scr.get("request_delay", 1.0)),
        max_retries=int(scr.get("max_retries", 4)),
        download_images=bool(scr.get("download_images", True)),
        headless=bool(sel.get("headless", True)),
        chrome_binary=(sel.get("chrome_binary") or None),
        chromedriver_path=(sel.get("chromedriver_path") or None),
        max_pages=int(scr.get("max_pages", 60)),
        robots_exceptions=_robots_exceptions(scr.get("robots_exceptions")),
    )

    bak = _section(data, "backups")
    backup_defaults = BackupConfig()
    backup_path = bak.get("directory")
    backups = BackupConfig(
        # Off in development whatever the file says: the flag exists so a
        # production deployment can turn it off deliberately, and is.enabled()
        # is what actually decides.
        enabled=bool(bak.get("enabled", True)),
        directory=(
            _resolve_path(backup_path, ROOT_DIR)
            if backup_path
            else (ROOT_DIR / "backups" if mode == "dev" else state_dir / "backups")
        ),
        keep=int(bak.get("keep", backup_defaults.keep)),
        interval_hours=int(bak.get("interval_hours", backup_defaults.interval_hours)),
    )

    cap = _section(data, "recaptcha")
    recaptcha = RecaptchaConfig(
        enabled=bool(cap.get("enabled", False)),
        site_key=str(cap.get("site_key", "") or ""),
        secret_key=str(cap.get("secret_key", "") or ""),
        minimum_score=float(cap.get("minimum_score", 0.5)),
        verify_url=str(cap.get("verify_url", "https://www.google.com/recaptcha/api/siteverify")),
    )

    acc = _section(data, "access_requests")
    access_requests = AccessRequestConfig(
        enabled=bool(acc.get("enabled", True)),
        rate_limit_per_hour=int(acc.get("rate_limit_per_hour", 3)),
    )

    return Config(
        mode=mode,
        source_path=source,
        database=database,
        images_path=images_path,
        security=security,
        admin=admin,
        email=email,
        server=server,
        scheduler=scheduler,
        scraping=scraping,
        backups=backups,
        recaptcha=recaptcha,
        access_requests=access_requests,
        raw=data,
    )


_cached: Config | None = None


def get_config(reload: bool = False) -> Config:
    """Return the process-wide configuration, loading it on first use."""
    global _cached
    if _cached is None or reload:
        _cached = load_config()
    return _cached


def generate_secret() -> str:
    """A fresh value suitable for ``jwt_secret`` / ``password_pepper``."""
    return secrets.token_urlsafe(48)
