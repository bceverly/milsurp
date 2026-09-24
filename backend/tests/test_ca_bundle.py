"""The scrape session trusts certifi's roots plus the intermediates some
vendors fail to send -- and nothing about verification is relaxed."""

from __future__ import annotations

from pathlib import Path

import certifi

from app.scrapers import ScrapeContext
from app.scrapers.base import EXTRA_INTERMEDIATES, ca_bundle


def test_the_bundle_is_the_roots_plus_the_intermediates():
    bundle = Path(ca_bundle()).read_bytes()
    assert Path(certifi.where()).read_bytes() in bundle
    assert EXTRA_INTERMEDIATES.read_bytes() in bundle


def test_the_intermediate_clyde_armory_leaves_out_is_there():
    text = EXTRA_INTERMEDIATES.read_text()
    assert "Sectigo Public Server Authentication CA DV R36" in text
    assert text.count("BEGIN CERTIFICATE") == 1


def test_the_session_verifies_against_it(app_config):
    ctx = ScrapeContext(app_config)
    try:
        # A path, never False: verification stays on for every site.
        assert ctx.session.verify == ca_bundle()
    finally:
        ctx.close()
