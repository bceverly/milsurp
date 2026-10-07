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
    assert "Sectigo Public Server Authentication CA DV R36" in EXTRA_INTERMEDIATES.read_text()


def test_the_intermediate_what_a_country_leaves_out_is_there():
    """Its certificate renewed on 2026-10-06 came without its intermediate, and
    the next scan could not read robots.txt."""
    assert "GeoTrust TLS RSA CA G1" in EXTRA_INTERMEDIATES.read_text()


def test_every_intermediate_says_which_site_needs_it():
    """The file's own rule: add one only for a named site. A certificate with
    no note above it is one nobody can later tell is safe to remove."""
    text = EXTRA_INTERMEDIATES.read_text()
    assert text.count("BEGIN CERTIFICATE") == text.count("#   needed by:") == 2


def test_the_session_verifies_against_it(app_config):
    ctx = ScrapeContext(app_config)
    try:
        # A path, never False: verification stays on for every site.
        assert ctx.session.verify == ca_bundle()
    finally:
        ctx.close()
