"""Where runtime state is allowed to land, and one directory that proved it.

Nothing here is about the application at run time. It is about what a directory
created *beside pyproject.toml* does to the tools that read this repository,
which is a thing a path default quietly gets to decide and nobody thinks to
check.

The driver cache is the one that taught it. Selenium Manager downloads a
chromedriver when the machine's own has fallen behind its browser, and the
cache defaulted to ``<state dir>/selenium`` -- the repository root, in dev. A
directory named ``selenium`` beside pyproject.toml is not inert: ruff's isort
decides what is first-party by looking for a matching directory under its
``src`` roots, so the moment the cache existed the real ``selenium`` package
was reclassified and every ``from selenium import ...`` block in the tree was
reordered. Locally that reads as a lint failure in a file nobody edited; in CI,
where the cache does not exist, the file "fixed" to satisfy it fails the
opposite way. Two green checkmarks that cannot both be earned.

Any directory sharing a name with an installed top-level package does the same,
so what is pinned here is the general rule rather than the one name.
"""

from __future__ import annotations

import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

from app.config import ROOT_DIR, load_config

#: `backups/` predates all of this, is named in .gitignore, and shadows no
#: importable package. It is the exception the rule is stated around rather
#: than a counter-example to it.
GRANDFATHERED = {"backups"}


@pytest.fixture
def dev_paths(tmp_path: Path) -> dict[str, Path]:
    """Every on-disk location dev mode makes up for itself.

    Read from an empty config file rather than whatever this machine happens
    to have, so the answer is the default and not the developer's.
    """
    empty = tmp_path / "config.yaml"
    empty.write_text("{}\n", encoding="utf-8")
    config = load_config(empty, mode="dev")
    return {
        "images": config.images_path,
        "driver cache": Path(config.scraping.driver_cache_path or ""),
        "backups": config.backups.directory,
    }


class TestRuntimeStateStaysOutOfTheRepositoryRoot:
    def test_nothing_new_is_created_beside_pyproject(self, dev_paths):
        offenders = {
            name: path
            for name, path in dev_paths.items()
            if path.parent == ROOT_DIR and path.name not in GRANDFATHERED
        }
        assert not offenders, f"these would appear in the repository root: {offenders}"

    def test_and_nothing_at_all_shadows_an_importable_package(self, dev_paths):
        """The half that actually broke CI, and the half `backups` is exempt
        from nothing on: a root-level directory whose name matches a package
        changes how that package's imports are classified, everywhere in the
        tree at once.

        Asked of the installed distributions and the standard library rather
        than of ``find_spec``, which would answer yes to the directory being
        tested -- the repository root is on ``sys.path``, so anything created
        there is importable by definition and the check would be circular.
        """
        taken = set(packages_distributions()) | set(sys.stdlib_module_names)
        for name, path in dev_paths.items():
            if path.parent != ROOT_DIR:
                continue
            assert path.name not in taken, (
                f"{name} would put {path.name}/ in the repository root, where it "
                f"shadows the installed package of that name"
            )

    def test_the_driver_cache_is_under_data(self, dev_paths):
        """Named rather than merely implied: data/ is gitignored at any depth
        and is where the image store already lives for the same reason."""
        assert dev_paths["driver cache"] == ROOT_DIR / "data" / "selenium"

    def test_but_production_keeps_the_plain_name(self, tmp_path):
        """Nothing imports anything from /etc/milsurp, so the trap is not
        there and the obvious name is the right one."""
        empty = tmp_path / "config.yaml"
        empty.write_text("{}\n", encoding="utf-8")
        config = load_config(empty, mode="production")
        assert config.scraping.driver_cache_path == Path("/etc/milsurp/selenium")

    def test_a_configured_cache_is_used_as_given(self, tmp_path):
        written = tmp_path / "config.yaml"
        written.write_text(
            f"scraping:\n  selenium:\n    driver_cache: {tmp_path / 'drivers'}\n",
            encoding="utf-8",
        )
        assert load_config(written, mode="dev").scraping.driver_cache_path == tmp_path / "drivers"

    def test_a_relative_one_is_resolved_against_the_state_directory(self, tmp_path):
        written = tmp_path / "config.yaml"
        written.write_text("scraping:\n  selenium:\n    driver_cache: drivers\n", encoding="utf-8")
        assert load_config(written, mode="dev").scraping.driver_cache_path == ROOT_DIR / "drivers"
