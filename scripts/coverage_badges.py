#!/usr/bin/env python3
"""Generate the README coverage badges.

Reads the coverage reports the test runs produce and writes self-contained SVG
badges to marketing/images/. The badges are committed and referenced by relative
path from the README, so they render on GitHub without a shields.io round trip
and without leaking repository activity to a third party on every page view.

Colors follow the project's floor: red below 65%, amber up to 80%, green above.

    python scripts/coverage_badges.py                 # both
    python scripts/coverage_badges.py --backend-only
    python scripts/coverage_badges.py --frontend-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BADGE_DIR = REPO_ROOT / "marketing" / "images"

BACKEND_JSON = REPO_ROOT / "coverage-backend.json"
FRONTEND_JSON = REPO_ROOT / "frontend" / "coverage" / "coverage-summary.json"

#: The floor `make test` enforces. Below it, the badge is red.
MINIMUM = 65.0
#: Above this, the badge is green; in between it is amber.
GOOD = 80.0

COLORS = {
    "red": "#c9302c",
    "amber": "#c08a00",
    "green": "#1e7a46",
    "gray": "#7c8697",
}


def color_for(percent: float | None) -> str:
    if percent is None:
        return COLORS["gray"]
    if percent < MINIMUM:
        return COLORS["red"]
    if percent < GOOD:
        return COLORS["amber"]
    return COLORS["green"]


def _text_width(text: str) -> int:
    """Approximate rendered width of DejaVu Sans at 11px.

    Badges are laid out by hand rather than measured by a font engine, so a
    per-character estimate is used: digits and lowercase are narrow, uppercase
    and wide letters are not.
    """
    width = 0.0
    for char in text:
        if char in "iljtfrI.,:;'":
            width += 3.4
        elif char in "mwMW%":
            width += 9.6
        elif char.isupper():
            width += 7.6
        else:
            width += 6.4
    return int(width + 0.5)


def render_badge(label: str, value: str, color: str) -> str:
    """A shields.io-style badge, generated locally with no external request."""
    pad = 10
    label_width = _text_width(label) + pad * 2
    value_width = _text_width(value) + pad * 2
    total = label_width + value_width

    # Text is drawn twice: once in near-black at 10% opacity one pixel low (the
    # engraved shadow every badge has), then in white on top.
    label_x = label_width / 2
    value_x = label_width + value_width / 2

    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{total}" height="20" role="img" aria-label="{label}: {value}">
  <title>{label}: {value}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#3f4650"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle"
     font-family="Verdana,DejaVu Sans,Geneva,sans-serif" font-size="11">
    <text x="{label_x:.1f}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_x:.1f}" y="14">{label}</text>
    <text x="{value_x:.1f}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{value_x:.1f}" y="14">{value}</text>
  </g>
</svg>
"""


def read_backend_coverage() -> float | None:
    """Total line coverage from pytest-cov's JSON report."""
    if not BACKEND_JSON.is_file():
        return None
    try:
        data = json.loads(BACKEND_JSON.read_text(encoding="utf-8"))
        return round(float(data["totals"]["percent_covered"]), 1)
    except (ValueError, KeyError, OSError):
        return None


def read_frontend_coverage() -> float | None:
    """Total line coverage from nyc's json-summary report."""
    if not FRONTEND_JSON.is_file():
        return None
    try:
        data = json.loads(FRONTEND_JSON.read_text(encoding="utf-8"))
        return round(float(data["total"]["lines"]["pct"]), 1)
    except (ValueError, KeyError, TypeError, OSError):
        return None


def write_badge(name: str, label: str, percent: float | None, quiet: bool) -> None:
    value = f"{percent:.1f}%" if percent is not None else "unknown"
    svg = render_badge(label, value, color_for(percent))
    BADGE_DIR.mkdir(parents=True, exist_ok=True)
    path = BADGE_DIR / f"{name}.svg"
    path.write_text(svg, encoding="utf-8")
    if not quiet:
        state = (
            "no data"
            if percent is None
            else "below the 65% floor" if percent < MINIMUM else "ok" if percent < GOOD else "good"
        )
        print(f"  {label:<18} {value:>7}  ({state})  -> {path.relative_to(REPO_ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate README coverage badges.")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if either side is below the minimum (for CI).",
    )
    args = parser.parse_args(argv)

    do_backend = not args.frontend_only
    do_frontend = not args.backend_only

    if not args.quiet:
        print("\nCoverage badges")

    backend = frontend = None
    if do_backend:
        backend = read_backend_coverage()
        write_badge("coverage-backend", "backend coverage", backend, args.quiet)
    if do_frontend:
        frontend = read_frontend_coverage()
        write_badge("coverage-frontend", "frontend coverage", frontend, args.quiet)

    if not args.quiet:
        print()

    if args.check:
        failed = [
            name
            for name, value in (("backend", backend), ("frontend", frontend))
            if value is not None and value < MINIMUM
        ]
        missing = [
            name
            for name, value, wanted in (
                ("backend", backend, do_backend),
                ("frontend", frontend, do_frontend),
            )
            if wanted and value is None
        ]
        if missing:
            print(f"No coverage data for: {', '.join(missing)}. Run 'make test'.", file=sys.stderr)
            return 1
        if failed:
            print(
                f"Coverage below the {MINIMUM:.0f}% floor: {', '.join(failed)}.",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
