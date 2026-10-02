"""MITRE's "Lucky 13": the vulnerabilities too basic to ship.

Steve Christey, "Unforgivable Vulnerabilities", The MITRE Corporation, Black
Hat USA 2007 (https://cwe.mitre.org/documents/unforgivable_vulns/). A
vulnerability is *unforgivable* when many have made the mistake before, it is
well documented, and -- the test that matters here -- it can be "found within
five minutes of limited, typically manual testing or code review". The paper
names thirteen, roughly in order of how often they appeared in CVE.

One class per item, numbered as the paper numbers them, each doing the
five-minute test for real: long strings of "A", a well-formed SCRIPT tag, a
quote in the login, "../..", an "authenticated=1" cookie, every admin route
asked for anonymously. Several items were written about C programs and Windows
desktops; for those the class tests the nearest thing this application can
get wrong and says why, rather than marking it not applicable.

Run on its own with ``make lucky13``; it is also part of ``make test-backend``
and so of CI, and ``make security`` runs it. Three findings were fixed when it
was written (2026-10-02): two-factor secrets were sealed with a home-made
HMAC keystream (item 8), the scan-alert email put an administrator-editable
shop name into HTML unescaped (item 2), and lint wrote a fixed /tmp path
(item 10).
"""

from __future__ import annotations

import ast
import re
import stat
from collections.abc import Iterator
from pathlib import Path

import jwt
import pytest
from fastapi.routing import APIRoute

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"
SCRIPTS = ROOT / "scripts"
FRONTEND_SRC = ROOT / "frontend" / "src"
DEPLOY = ROOT / "deploy"

A_LOT = "A" * 100_000


# ---------------------------------------------------------------------------
# Helpers for the code-review half
# ---------------------------------------------------------------------------
def python_files(*roots: Path) -> Iterator[Path]:
    for root in roots:
        yield from (p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts)


def parsed(*roots: Path) -> Iterator[tuple[Path, ast.Module]]:
    for path in python_files(*roots):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def dotted(node: ast.AST) -> str:
    """``a.b.c`` for a Name/Attribute chain, else ''."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = dotted(node.value)
        return f"{inner}.{node.attr}" if inner else node.attr
    return ""


def calls(tree: ast.AST) -> Iterator[ast.Call]:
    yield from (node for node in ast.walk(tree) if isinstance(node, ast.Call))


def where(path: Path, node: ast.AST) -> str:
    return f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}"


def built_string(node: ast.AST) -> bool:
    """An f-string, a ``%`` or ``+`` on strings, or a ``.format()`` call."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(part, ast.FormattedValue) for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return any(
            isinstance(side, ast.JoinedStr)
            or (isinstance(side, ast.Constant) and isinstance(side.value, str))
            for side in (node.left, node.right)
        )
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    )


def every_route(app) -> Iterator:
    """Every API route, with its full path and its effective dependencies.

    FastAPI 0.141 keeps an included router as one lazy entry in
    ``app.routes`` rather than copying its routes up, so a walk of
    ``app.routes`` alone finds none of them -- which is how the first draft of
    this file passed item 7 having asked nothing.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "effective_route_contexts"):
            yield from route.effective_route_contexts()


def api_routes(app) -> Iterator[tuple[object, str, str]]:
    """Every API route and method, with each path parameter filled in."""
    for route in every_route(app):
        if route.path.startswith("/api"):
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            for method in sorted(set(route.methods) - {"HEAD", "OPTIONS"}):
                yield route, method, path


def depends_on(route, function) -> bool:
    pending = list(route.dependant.dependencies)
    while pending:
        dependant = pending.pop()
        if dependant.call is function:
            return True
        pending.extend(dependant.dependencies)
    return False


def _answered_cleanly(response) -> bool:
    """Below 500, or the one deliberate 503: a checkout whose frontend was
    never built (CI's security job) answers every page path with "the frontend
    has not been built", which is the app working, not breaking."""
    if response.status_code < 500:
        return True
    return response.status_code == 503 and "not been built" in response.text


# ---------------------------------------------------------------------------
# 1. Buffer overflow using long strings of "A"
# ---------------------------------------------------------------------------
class Test01LongStringsOfA:
    """In the username and password, a file name, and the common features.

    Python cannot overflow a buffer, so what a long "A" can still do here is
    raise, hang, or be stored whole. Each must be refused cleanly instead.
    """

    def test_in_the_username_and_password(self, client):
        response = client.post("/api/auth/login", json={"username": A_LOT, "password": A_LOT})
        assert response.status_code in (400, 401, 413, 422)

    def test_in_a_file_name(self, client):
        for path in (f"/assets/{A_LOT[:5000]}.js", f"/{A_LOT[:5000]}"):
            assert _answered_cleanly(client.get(path)), path

    def test_in_the_most_used_feature(self, client, admin_headers):
        """The inventory search, which caps its input rather than storing it."""
        response = client.get(f"/api/items?search={A_LOT[:5000]}", headers=admin_headers)
        assert response.status_code == 422
        response = client.get(f"/api/items?caliber={A_LOT[:5000]}", headers=admin_headers)
        assert response.status_code == 200

    def test_no_native_code_of_our_own(self):
        """The class needs C to happen. There is none in this tree to overflow."""
        native = [
            p
            for suffix in ("*.c", "*.cc", "*.cpp", "*.pyx", "*.h")
            for root in (APP, SCRIPTS)
            for p in root.rglob(suffix)
        ]
        assert native == []


# ---------------------------------------------------------------------------
# 2. XSS using well-formed SCRIPT tags
# ---------------------------------------------------------------------------
SCRIPT = "<script>alert(1)</script>"


class Test02ScriptTags:
    """In the username and password, and in the body or title of a message."""

    def test_in_the_login_is_not_reflected(self, client):
        response = client.post("/api/auth/login", json={"username": SCRIPT, "password": SCRIPT})
        assert "<script>" not in response.text
        assert response.headers["content-type"].startswith("application/json")

    def test_errors_are_json_not_html(self, client):
        response = client.get(f"/api/{SCRIPT}")
        assert response.headers["content-type"].startswith("application/json")

    def test_in_a_listing_title_in_the_email(self):
        """The digest and alerts are HTML, and a title is a vendor's words."""
        from app.models import Item
        from app.services import digest, wishlist
        from app.services.watchlist import News

        item = Item(id=1, title=SCRIPT, current_price=100.0, currency="USD")
        row = digest._watch_row(
            wishlist.Update(None, item, News.SOLD), "https://x.test", SCRIPT, None  # type: ignore[arg-type]
        )
        assert "<script>" not in row
        assert "&lt;script&gt;" in row

    def test_in_a_shop_name_in_the_scan_alert(self):
        """An administrator can rename a shop. Fixed when this was written."""
        from app.models import ScanRun, Site, utcnow
        from app.services import scanalerts

        site = Site(slug="s", name=SCRIPT, base_url="https://s.test/")
        run = ScanRun(error_message=SCRIPT, items_found=1, items_new=0)
        for _subject, html in (
            scanalerts._broken_message(site, run, 1, utcnow()),
            scanalerts._recovered_message(site, run),
        ):
            assert "<script>" not in html

    def test_the_frontend_never_writes_raw_html(self):
        """React escapes everything it renders unless told not to."""
        sinks = re.compile(
            r"dangerouslySetInnerHTML\s*=|\.innerHTML\s*=|\.outerHTML\s*=|document\.write\(|"
            r"insertAdjacentHTML\(|\beval\(|new Function\("
        )
        found = []
        for path in sorted(FRONTEND_SRC.rglob("*.js*")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("*", "//", "/*")):
                    continue
                if sinks.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}")
        assert found == []

    def test_every_site_config_forbids_inline_script(self):
        """And if one ever got through, the browser would refuse to run it."""
        for conf in sorted((DEPLOY / "nginx").glob("*.conf")):
            for policy in re.findall(r'Content-Security-Policy\s+"([^"]+)"', conf.read_text()):
                script = re.search(r"script-src ([^;]+)", policy)
                assert script and "'unsafe-inline'" not in script.group(1), conf.name


# ---------------------------------------------------------------------------
# 3. SQL injection using '
# ---------------------------------------------------------------------------
class Test03QuoteInSql:
    """In the username and password, an "id" field, and a numeric field."""

    def test_in_the_login(self, client, admin_headers):
        for username in ("admin' --", "' OR '1'='1", "admin'/*"):
            response = client.post(
                "/api/auth/login", json={"username": username, "password": "' OR '1'='1"}
            )
            assert response.status_code == 401, username

    def test_in_an_id(self, client, admin_headers):
        assert client.get("/api/items/1'", headers=admin_headers).status_code == 422
        assert client.get("/api/items/1 OR 1=1", headers=admin_headers).status_code == 422

    def test_in_a_numeric_field(self, client, admin_headers):
        response = client.get("/api/items?min_price=1' OR '1'='1", headers=admin_headers)
        assert response.status_code == 422

    def test_in_text_it_is_only_text(self, client, admin_headers):
        for value in ("'", "' OR '1'='1", "'; DROP TABLE items; --"):
            response = client.get(f"/api/items?search={value}", headers=admin_headers)
            assert response.status_code == 200, value
            response = client.get(f"/api/items?caliber={value}", headers=admin_headers)
            assert response.json()["total"] == 0, value

    def test_no_sql_is_built_from_strings(self):
        """Every query goes through bound parameters. A string assembled with an
        f-string, ``%``, ``+`` or ``.format()`` and handed to ``text()``,
        ``execute()`` or ``exec_driver_sql()`` is how a quote gets in."""
        sinks = {"text", "execute", "exec_driver_sql", "executescript"}
        found = [
            where(path, call)
            for path, tree in parsed(APP)
            for call in calls(tree)
            if dotted(call.func).rsplit(".", 1)[-1] in sinks
            and call.args
            and built_string(call.args[0])
        ]
        assert found == []

    def test_migrations_build_sql_only_from_constants(self):
        """A migration has no input, so one f-string there is reviewed by hand."""
        reviewed = {
            # DROP TRIGGER for each suffix in a constant tuple of three.
            "backend/alembic/versions/0034_search_index.py",
        }
        found = {
            str(path.relative_to(ROOT))
            for path, tree in parsed(ROOT / "backend" / "alembic")
            for call in calls(tree)
            if dotted(call.func).rsplit(".", 1)[-1] in {"execute", "text"}
            and call.args
            and built_string(call.args[0])
        }
        assert found <= reviewed, found - reviewed


# ---------------------------------------------------------------------------
# 4. Remote file inclusion from direct input
# ---------------------------------------------------------------------------
class Test04RemoteInclusion:
    """``include($_GET['dir'] . "/config.inc")``: running code a request names.

    Python's equivalents are eval, exec, a dynamic import, and deserializing
    something that can construct objects. None of them is used at all, so
    none of them can be fed.
    """

    DANGEROUS = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "importlib.import_module",
        "pickle.load",
        "pickle.loads",
        "marshal.load",
        "marshal.loads",
        "shelve.open",
        "yaml.load",
        "yaml.unsafe_load",
        "runpy.run_path",
        "runpy.run_module",
    }

    def test_no_code_is_loaded_from_data(self):
        found = [
            f"{where(path, call)} {dotted(call.func)}"
            for path, tree in parsed(APP, SCRIPTS)
            for call in calls(tree)
            if dotted(call.func) in self.DANGEROUS
        ]
        assert found == []

    def test_the_frontend_imports_only_named_modules(self):
        dynamic = re.compile(r"\bimport\(\s*[^\"'`\s)]")
        found = [
            str(path.relative_to(ROOT))
            for path in sorted(FRONTEND_SRC.rglob("*.js*"))
            if dynamic.search(path.read_text(encoding="utf-8"))
        ]
        assert found == []


# ---------------------------------------------------------------------------
# 5. Directory traversal using "../.."
# ---------------------------------------------------------------------------
TRAVERSALS = (
    "../../../../etc/passwd",
    "..%2f..%2f..%2f..%2fetc%2fpasswd",
    "%2e%2e/%2e%2e/%2e%2e/etc/passwd",
    "....//....//etc/passwd",
    "assets/../../config.yaml",
    "/etc/passwd",
)


class Test05DotDot:
    """In the GET of the most used file-sharing function: here, the static
    files the browser loads, and the listing photographs."""

    def test_the_static_files(self, client):
        for path in TRAVERSALS:
            for prefix in ("/", "/assets/"):
                response = client.get(prefix + path)
                assert "root:" not in response.text, prefix + path
                assert "jwt_secret" not in response.text, prefix + path

    def test_the_static_file_resolver(self):
        from app.main import _asset_path

        for path in TRAVERSALS:
            assert _asset_path(path) is None, path

    def test_the_photograph_store(self, tmp_path, app_config):
        """A stored path is resolved and refused outside the image root, and a
        symlink inside the root that points out of it is refused too."""
        import dataclasses

        from app.services.image_store import ImageStore, ImageStoreError

        root = tmp_path / "images"
        root.mkdir()
        (tmp_path / "secret.txt").write_text("nope")
        (root / "escape").symlink_to(tmp_path / "secret.txt")
        config = dataclasses.replace(app_config, images_path=root)
        store = ImageStore(config)
        # Only the real escapes: "....//" and "%2e%2e" are odd file names
        # inside the root here, since nothing decodes a stored path.
        escapes = ("../../../../etc/passwd", "assets/../../config.yaml", "/etc/passwd", "escape")
        for path in escapes:
            with pytest.raises(ImageStoreError):
                store.absolute_path(path)

    def test_the_photograph_route_takes_numbers_only(self, client, admin_headers):
        response = client.get("/api/items/1/photos/..%2f..%2fetc%2fpasswd", headers=admin_headers)
        assert response.status_code in (404, 422)


# ---------------------------------------------------------------------------
# 6. World-writable critical files
# ---------------------------------------------------------------------------
class Test06WorldWritable:
    """Executables, libraries and configuration files."""

    def test_nothing_shipped_is_world_writable(self):
        roots = [APP, ROOT / "backend" / "alembic", SCRIPTS, DEPLOY, FRONTEND_SRC]
        loose = [ROOT / name for name in ("Makefile", "config.yaml.sample", "pyproject.toml")]
        found = [
            str(path.relative_to(ROOT))
            for path in [*loose, *(p for root in roots for p in root.rglob("*"))]
            if path.exists() and not path.is_symlink() and path.stat().st_mode & stat.S_IWOTH
        ]
        assert found == []

    def test_no_code_grants_world_write(self):
        """No chmod, mkdir or open with a mode that lets anybody write."""
        found = []
        for path, tree in parsed(APP, SCRIPTS):
            for call in calls(tree):
                name = dotted(call.func).rsplit(".", 1)[-1]
                if name not in {"chmod", "mkdir", "makedirs", "open", "fchmod", "touch"}:
                    continue
                modes = [kw.value for kw in call.keywords if kw.arg == "mode"]
                if name in {"chmod", "fchmod"} and len(call.args) > 1:
                    modes.append(call.args[1])
                found.extend(
                    where(path, call)
                    for mode in modes
                    if isinstance(mode, ast.Constant)
                    and isinstance(mode.value, int)
                    and mode.value & stat.S_IWOTH
                )
        assert found == []

    def test_the_local_configuration_is_private(self):
        """config.yaml holds the secrets; make security checks its mode too."""
        config = ROOT / "config.yaml"
        if config.exists():
            assert not config.stat().st_mode & (stat.S_IRWXO | stat.S_IWGRP)


# ---------------------------------------------------------------------------
# 7. Direct requests of administrator scripts
# ---------------------------------------------------------------------------
#: The only routes that answer somebody who is not signed in, each on purpose.
PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/policy"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/reset/1"),
    ("POST", "/api/auth/reset"),
    ("GET", "/api/access-request/config"),
    ("POST", "/api/access-request"),
}


class Test07AdminScriptsAskedForDirectly:
    """Every route is asked anonymously, and every administrator route is asked
    by an ordinary account. Walked from the application itself, so a route
    added tomorrow is checked tomorrow."""

    def test_nothing_answers_a_stranger_except_the_public_few(self, client):
        answered = []
        asked = 0
        for _route, method, path in api_routes(client.app):
            asked += 1
            if (method, path) in PUBLIC:
                continue
            response = client.request(method, path)
            if response.status_code < 400 or response.status_code >= 500:
                answered.append(f"{method} {path} -> {response.status_code}")
        # Asked of every route, not of none: see every_route.
        assert asked > 100
        assert answered == []

    def test_no_admin_route_answers_an_ordinary_account(self, client, normal_user):
        from app.deps import require_admin

        answered = []
        admin_routes = 0
        for route, method, path in api_routes(client.app):
            if not depends_on(route, require_admin):
                continue
            admin_routes += 1
            response = client.request(method, path, headers=normal_user["headers"])
            if response.status_code != 403:
                answered.append(f"{method} {path} -> {response.status_code}")
        assert admin_routes > 20
        assert answered == []

    def test_the_public_list_is_not_stale(self, client):
        routes = {(method, path) for _route, method, path in api_routes(client.app)}
        assert routes >= PUBLIC, PUBLIC - routes


# ---------------------------------------------------------------------------
# 8. Grow-your-own crypto
# ---------------------------------------------------------------------------
class Test08HomeMadeCrypto:
    """Fixed when this was written: two-factor secrets were sealed with an
    HMAC keystream built in totp.py. They are now AES-256-GCM."""

    def test_passwords_are_argon2id(self, app_config):
        from app.security import hash_password

        assert hash_password("a long enough passphrase", app_config).startswith("$argon2id$")

    def test_two_factor_secrets_are_aes_gcm(self, app_config):
        from app import totp

        assert totp.seal(totp.new_secret(), app_config).startswith("v3:")

    def test_no_weak_or_home_made_primitives(self):
        """No random module for anything (secrets is the module for that), no
        MD5 or SHA-1 called directly, no PyCrypto and its relatives."""
        found = []
        banned_imports = ("random", "Crypto", "Cryptodome", "pyDes", "rc4", "simplecrypt")
        for path, tree in parsed(APP):
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                if any(name.split(".")[0] in banned_imports for name in names):
                    found.append(f"{where(path, node)} imports {names}")
            for call in calls(tree):
                if dotted(call.func) in {"hashlib.md5", "hashlib.sha1"}:
                    found.append(f"{where(path, call)} {dotted(call.func)}")
                if dotted(call.func) == "hashlib.new" and call.args:
                    first = call.args[0]
                    if isinstance(first, ast.Constant) and str(first.value).lower() in {
                        "md5",
                        "sha1",
                    }:
                        found.append(where(path, call))
        assert found == []

    def test_tokens_pin_their_algorithm(self, app_config):
        """A token claiming "alg: none" is not a token."""
        from app.security import TokenError, decode_access_token

        forged = jwt.encode({"sub": "1"}, key="", algorithm="none")
        with pytest.raises(TokenError):
            decode_access_token(forged, app_config)


# ---------------------------------------------------------------------------
# 9. Authentication bypass using "authenticated=1"
# ---------------------------------------------------------------------------
class Test09AuthenticatedEqualsOne:
    """A cookie, a form field or a header that claims to be signed in."""

    CLAIMS = {"authenticated": "1", "admin": "1", "is_admin": "true", "role": "admin"}

    def test_cookies_claiming_it(self, client):
        client.cookies.update({**self.CLAIMS, "milsurp_session": "1", "user": "admin"})
        try:
            assert client.get("/api/auth/me").status_code == 401
            assert client.get("/api/users").status_code == 401
        finally:
            client.cookies.clear()

    def test_headers_and_fields_claiming_it(self, client):
        headers = {
            "X-Authenticated": "1",
            "X-User": "admin",
            "X-Forwarded-User": "admin",
            "X-Remote-User": "admin",
            "Authorization": "Bearer 1",
        }
        assert client.get("/api/auth/me?authenticated=1&admin=1", headers=headers).status_code in (
            401,
            403,
        )
        response = client.post("/api/users", json={**self.CLAIMS, "username": "x"})
        assert response.status_code in (401, 403)

    def test_a_token_signed_with_another_key(self, client, app_config):
        forged = jwt.encode(
            {"sub": "1", "ver": 0}, "not-our-secret-but-long-enough-to-sign", algorithm="HS256"
        )
        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 10. Turtle race condition: symlinks
# ---------------------------------------------------------------------------
class Test10SymlinkRace:
    """Opening a predictable file without checking it first. Fixed when this
    was written: lint wrote its log to a fixed /tmp path."""

    #: /tmp inside a throwaway container, where nobody else can plant a link.
    REVIEWED_SHELL = {"scripts/test-installer.sh"}

    def test_no_fixed_temporary_paths_in_python(self):
        found = []
        for path, tree in parsed(APP, SCRIPTS):
            found.extend(
                where(path, node)
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.match(r"^/(var/)?tmp/", node.value)
            )
            found.extend(
                where(path, call)
                for call in calls(tree)
                if dotted(call.func) in {"tempfile.mktemp", "os.tmpnam", "os.tempnam"}
            )
        assert found == []

    def test_no_fixed_temporary_paths_in_shell(self):
        found = [
            str(path.relative_to(ROOT))
            for path in sorted(SCRIPTS.glob("*.sh"))
            if re.search(r"(?<![\w$])/tmp/\w", path.read_text())
            and str(path.relative_to(ROOT)) not in self.REVIEWED_SHELL
        ]
        assert found == []

    def test_the_photograph_store_will_not_follow_a_link_out(self):
        """Covered under item 5: absolute_path resolves links before it checks."""
        from app.services import image_store

        assert ".resolve()" in Path(image_store.__file__).read_text()


# ---------------------------------------------------------------------------
# 11. Privilege escalation launching "help" (Windows)
# ---------------------------------------------------------------------------
class Test11PrivilegesNotDropped:
    """The paper's point is a program that never gives up privileges it does
    not need, so a harmless feature becomes a way to them. There is no Help
    window here; the equivalent is the service running as root, or able to
    regain it, or handing a string to a shell."""

    def test_every_service_runs_unprivileged_and_cannot_regain_it(self):
        for unit in sorted((DEPLOY / "systemd").glob("*.service")):
            text = unit.read_text()
            user = re.search(r"^User=(\S+)", text, re.MULTILINE)
            assert user and user.group(1) not in {"root", "0"}, unit.name
            assert re.search(r"^NoNewPrivileges=true", text, re.MULTILINE), unit.name

    def test_no_shell_is_ever_handed_a_string(self):
        found = []
        for path, tree in parsed(APP, SCRIPTS):
            for call in calls(tree):
                name = dotted(call.func)
                if name in {"os.system", "os.popen", "commands.getoutput"}:
                    found.append(f"{where(path, call)} {name}")
                if name.startswith("subprocess.") and any(
                    kw.arg == "shell"
                    and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
                    for kw in call.keywords
                ):
                    found.append(f"{where(path, call)} shell=True")
        assert found == []


# ---------------------------------------------------------------------------
# 12. Hard-coded or undocumented account/password
# ---------------------------------------------------------------------------
SECRET_NAME = re.compile(
    r"(^|_)(password|passwd|pwd|secret|api_key|apikey|private_key|token_secret|pepper)$",
    re.IGNORECASE,
)


#: Not ours: each shop's public search key, which its own pages hand to every
#: visitor's browser. Reviewed 2026-10-02.
PUBLISHED_KEYS = {
    ("backend/app/scrapers/botach.py", "api_key"),
    ("backend/app/scrapers/sarco.py", "api_key"),
}


class Test12HardCodedAccounts:
    def test_no_account_or_secret_ships_with_a_value(self):
        from app.config import AdminSeedConfig, SecurityConfig

        assert AdminSeedConfig().password == ""
        assert SecurityConfig().jwt_secret == ""
        assert SecurityConfig().password_pepper == ""

    def test_no_secret_is_written_into_the_code(self):
        """Any name that reads like a secret, given a literal string."""
        found = []
        for path, tree in parsed(APP, SCRIPTS):
            for node in ast.walk(tree):
                pairs = []
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    pairs = [(dotted(target), node.value) for target in targets]
                elif isinstance(node, ast.keyword) and node.arg:
                    pairs = [(node.arg, node.value)]
                found.extend(
                    f"{where(path, node)} {name}"
                    for name, value in pairs
                    if SECRET_NAME.search(name.rsplit(".", 1)[-1])
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and value.value
                    and (str(path.relative_to(ROOT)), name) not in PUBLISHED_KEYS
                )
        assert found == []

    def test_no_migration_creates_an_account(self):
        found = [
            str(path.relative_to(ROOT))
            for path in python_files(ROOT / "backend" / "alembic")
            if re.search(r"insert\s+into\s+users\b", path.read_text(), re.IGNORECASE)
        ]
        assert found == []

    def test_no_password_means_no_admin_rather_than_a_default_one(self, clean_db, app_config):
        import dataclasses

        from app.models import User
        from app.services import bootstrap

        config = dataclasses.replace(
            app_config, admin=dataclasses.replace(app_config.admin, password="")
        )
        assert bootstrap.ensure_admin(clean_db, config) is None
        assert clean_db.query(User).count() == 0


# ---------------------------------------------------------------------------
# 13. Unchecked length/width/height/size values passed to malloc()
# ---------------------------------------------------------------------------
SIZE_PARAMS = {"limit", "per_page", "page_size", "size", "count", "top", "n", "days", "hours"}


def _numeric(field) -> bool:
    """An int or float parameter, optional or not -- not "size=thumb"."""
    import typing

    annotation = field.field_info.annotation
    return any(kind in (int, float) for kind in (annotation, *typing.get_args(annotation)))


class Test13UncheckedSizes:
    """No malloc here, but the same mistake: a size from outside, used as given.

    A per_page of a billion asks the database for every row; an image that
    says it is 100,000 pixels square asks for gigabytes to decode it.
    """

    def test_every_size_a_request_can_name_has_a_ceiling(self, client):
        unbounded = []
        checked = 0
        for route in every_route(client.app):
            for field in route.dependant.query_params:
                if field.name not in SIZE_PARAMS or not _numeric(field):
                    continue
                checked += 1
                metadata = getattr(field.field_info, "metadata", [])
                if not any(hasattr(m, "le") or hasattr(m, "lt") for m in metadata):
                    unbounded.append(f"{route.path}?{field.name}")
        assert checked >= 5
        assert unbounded == []

    def test_a_page_of_a_billion_is_refused(self, client, admin_headers):
        response = client.get("/api/items?per_page=1000000000", headers=admin_headers)
        assert response.status_code == 422

    def test_images_have_a_pixel_ceiling(self):
        from PIL import Image

        from app.services import image_store

        assert Image.MAX_IMAGE_PIXELS == image_store.MAX_IMAGE_PIXELS
        assert image_store.MAX_IMAGE_PIXELS is not None
        assert image_store.MAX_IMAGE_PIXELS <= 100_000_000

    def test_every_server_caps_the_request_body(self):
        for conf in sorted((DEPLOY / "nginx").glob("*.conf")):
            assert re.search(r"client_max_body_size\s+\d+[km]?;", conf.read_text()), conf.name
