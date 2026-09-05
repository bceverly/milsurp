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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class SchedulerConfig:
    enabled: bool = True
    # How often the scheduler wakes up to look for sites that are due.
    tick_seconds: int = 60
    # How often it looks for users whose email digest is due.
    digest_tick_seconds: int = 300
    max_concurrent_scans: int = 2
    # Refuse to start a scan if one for the same site has been running longer
    # than this; the previous run is marked failed and reaped.
    scan_timeout_minutes: int = 120


@dataclass(frozen=True)
class ScrapingConfig:
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
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


@dataclass(frozen=True)
class Config:
    mode: str
    source_path: Path | None
    database_path: Path
    images_path: Path
    security: SecurityConfig
    admin: AdminSeedConfig
    email: EmailConfig
    server: ServerConfig
    scheduler: SchedulerConfig
    scraping: ScrapingConfig
    recaptcha: RecaptchaConfig
    access_requests: AccessRequestConfig
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_dev(self) -> bool:
        return self.mode == "dev"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def host(self) -> str:
        return self.server.dev_host if self.is_dev else self.server.prod_host

    def ensure_directories(self) -> None:
        """Create the database and image directories with safe permissions."""
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


def load_config(path: Path | None = None, mode: str | None = None) -> Config:
    """Read the config file (if any) and merge it over the defaults."""
    mode = mode or _env_mode()
    source = path or find_config_file()
    data = _load_yaml(source) if source else {}

    state_dir = _default_state_dir(mode)

    db_section = _section(data, "database")
    db_path = db_section.get("path")
    if db_path:
        database_path = _resolve_path(db_path, ROOT_DIR)
    else:
        database_path = state_dir / "milsurp.db"

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
        max_concurrent_scans=int(sch.get("max_concurrent_scans", 2)),
        scan_timeout_minutes=int(sch.get("scan_timeout_minutes", 120)),
    )

    scr = _section(data, "scraping")
    sel = _section(scr, "selenium")
    defaults = ScrapingConfig()
    scraping = ScrapingConfig(
        user_agent=str(scr.get("user_agent", defaults.user_agent)),
        request_timeout=int(scr.get("request_timeout", 30)),
        request_delay=float(scr.get("request_delay", 1.0)),
        max_retries=int(scr.get("max_retries", 4)),
        download_images=bool(scr.get("download_images", True)),
        headless=bool(sel.get("headless", True)),
        chrome_binary=(sel.get("chrome_binary") or None),
        chromedriver_path=(sel.get("chromedriver_path") or None),
        max_pages=int(scr.get("max_pages", 60)),
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
        database_path=database_path,
        images_path=images_path,
        security=security,
        admin=admin,
        email=email,
        server=server,
        scheduler=scheduler,
        scraping=scraping,
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
