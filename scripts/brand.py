#!/usr/bin/env python3
"""Generate the Milsurp Monitor brand assets.

One generator, several outputs, so the mark can never drift between the
marketing folder, the browser tab and the app header:

    marketing/images/logo.svg          full mark, with the blue field
    marketing/images/favicon.svg       heavier devices, for 16px rendering
    frontend/public/favicon.svg        build input for Vite
    frontend/src/components/Insignia.jsx   the in-app header mark

The mark is the US Air Force **Senior Airman (E-4)** insignia.

Its actual construction, which is not a stack of chevrons and not a shield:

  * A **circular hub** in the center. Its lower edge *is* the rounded bottom of
    the patch.
  * Two **constant-width striped wings** coming off that hub, angling up and
    out to blunt tips. Each wing carries **three stripes** running parallel to
    the wing.
  * A **five-pointed star** inside the hub, in the field color with a
    **darker blue outline** — it is blue on blue, not a white device.

    python scripts/brand.py
"""

from __future__ import annotations

import math
import subprocess  # nosec B404
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKETING = REPO_ROOT / "marketing" / "images"
FRONTEND_PUBLIC = REPO_ROOT / "frontend" / "public"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src" / "components"
#: The bitmap the digest attaches. Lives with the backend because that is
#: what reads it at send time.
EMAIL_MARK = REPO_ROOT / "backend" / "app" / "assets" / "insignia-email.png"

# Dress palette.
FIELD = "#1B3A66"
FIELD_DARK = "#12294A"
BORDER = "#0A2240"
SILVER = "#E8EDF5"
#: The star is outlined in a metallic blue: darker than a highlight, but
#: clearly lighter than the field so it still reads against it. Never white.
STAR_OUTLINE = "#4E7FB8"
#: A touch brighter for the favicon, which loses contrast at 16px.
STAR_OUTLINE_HI = "#6E9BCE"

# --- Geometry, in a 100 x 60 space -----------------------------------------
# Construction, which is what makes this read as the real insignia:
#
#   * A dark circular HUB in the center, sitting at the TOP of the z-order.
#   * Two wings, each a constant-width band whose CENTRE LINE runs through the
#     hub center. The three stripes are centered on that line, so the band of
#     stripes is slightly narrower than the hub's diameter and the stripes
#     appear to run behind the hub and out the other side.
#   * A five-pointed star at the exact center of the hub, in the field color
#     with a lighter metallic blue outline.
HUB_CENTER = (50.0, 43.0)
HUB_RADIUS = 15.0

#: A point on each wing's center line, out toward the tip. Only its direction
#: from the hub matters — the tip itself is cut at TIP_X below. Chosen to give
#: a 30-degree rake, and positioned so the band's upper edge clears the top of
#: the viewBox once it is offset outward.
WING_OUTER = (2.0, 15.3)
#: The wings are cut off by a VERTICAL edge, parallel to the sides of the
#: frame, rather than square to the wing. That flat outer end is what the real
#: patch has; a perpendicular cut leaves the tips looking sheared.
TIP_X = 2.0
#: Half the band width, measured perpendicular to the center line.
BAND_HALF = 12.0

#: Stripe offsets from the wing's center line: one on it, one either side. The
#: band they span (21.5) is deliberately a little less than the hub diameter
#: (30), so the stripes meet the circle rather than the circle floating on top
#: of a wider field.
STRIPE_OFFSETS = (-8.0, 0.0, 8.0)
STRIPE_WIDTH = 5.5
#: Overshoot both ends; the clip trims the outer end and the hub covers the
#: inner end.
OVERSHOOT = 10.0

STAR_OUTER = 9.6
STAR_INNER = 4.0


def _mirror(point: tuple[float, float]) -> tuple[float, float]:
    """Reflect a point across the vertical center line."""
    return (100.0 - point[0], point[1])


def _unit(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


def _center_line(right: bool = False) -> tuple[tuple[float, float], tuple[float, float]]:
    """A wing's center line, from the outer tip to the hub center."""
    outer = _mirror(WING_OUTER) if right else WING_OUTER
    return outer, HUB_CENTER


def _normal(right: bool = False) -> tuple[float, float]:
    """Unit normal to a wing's center line, pointing downward."""
    outer, inner = _center_line(right)
    ux, uy = _unit(outer, inner)
    nx, ny = -uy, ux
    return (nx, ny) if ny > 0 else (-nx, -ny)


def _extend_to_x(
    point: tuple[float, float], direction: tuple[float, float], target_x: float
) -> tuple[float, float]:
    """Follow ``direction`` from ``point`` until x reaches ``target_x``."""
    ux, uy = direction
    if abs(ux) < 1e-9:  # pragma: no cover - the wings are never vertical
        return point
    t = (target_x - point[0]) / ux
    return (target_x, point[1] + t * uy)


def wing_points(right: bool = False) -> list[tuple[float, float]]:
    """The wing as a quadrilateral with a vertical outer edge.

    The two long edges are offset either side of the center line; the outer end
    is where each of them crosses the vertical line at TIP_X, so the tip is cut
    parallel to the frame rather than square to the wing.
    """
    outer, inner = _center_line(right)
    ux, uy = _unit(outer, inner)
    nx, ny = _normal(right)
    tip_x = 100.0 - TIP_X if right else TIP_X

    inner_top = (inner[0] - nx * BAND_HALF, inner[1] - ny * BAND_HALF)
    inner_bottom = (inner[0] + nx * BAND_HALF, inner[1] + ny * BAND_HALF)
    # Walk back along the wing (negative u) to the vertical cut.
    tip_top = _extend_to_x(inner_top, (-ux, -uy), tip_x)
    tip_bottom = _extend_to_x(inner_bottom, (-ux, -uy), tip_x)

    return [tip_top, inner_top, inner_bottom, tip_bottom]


def _polygon(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def left_wing() -> str:
    return _polygon(wing_points())


def right_wing() -> str:
    return _polygon(wing_points(right=True))


def stripe_lines() -> list[tuple[float, float, float, float]]:
    """Six stripes: three per wing, centered on that wing's center line."""
    lines: list[tuple[float, float, float, float]] = []

    for right in (False, True):
        outer, inner = _center_line(right)
        ux, uy = _unit(outer, inner)
        nx, ny = _normal(right)

        tip_x = 100.0 - TIP_X if right else TIP_X
        for offset in STRIPE_OFFSETS:
            # Start beyond the vertical cut; the clip path trims it flush.
            start = _extend_to_x(
                (inner[0] + nx * offset, inner[1] + ny * offset),
                (-ux, -uy),
                tip_x + (OVERSHOOT if right else -OVERSHOOT),
            )
            x1, y1 = start
            x2 = inner[0] + ux * OVERSHOOT + nx * offset
            y2 = inner[1] + uy * OVERSHOOT + ny * offset
            lines.append((x1, y1, x2, y2))

    return lines


def star_points(cx: float, cy: float, outer: float, inner: float) -> str:
    """A five-pointed star, point up."""
    coords = []
    for index in range(10):
        radius = outer if index % 2 == 0 else inner
        angle = math.radians(-90 + index * 36)
        coords.append(f"{cx + radius * math.cos(angle):.2f},{cy + radius * math.sin(angle):.2f}")
    return " ".join(coords)


def _shapes(attrs: str) -> str:
    """The three shapes that make up the silhouette, with shared attributes."""
    return (
        f'    <circle cx="{HUB_CENTER[0]}" cy="{HUB_CENTER[1]}" r="{HUB_RADIUS}" {attrs}/>\n'
        f'    <polygon points="{left_wing()}" {attrs}/>\n'
        f'    <polygon points="{right_wing()}" {attrs}/>'
    )


def _silhouette(fill: str, border: str, width: float) -> str:
    """Hub plus wings, drawn as one apparent shape.

    Drawn twice: once stroked, then again unstroked on top. The second pass
    covers the parts of the outline that fall *inside* the union, which is what
    makes three overlapping shapes read as a single silhouette without needing
    real boolean geometry.
    """
    stroked_attrs = (
        f'fill="{fill}" stroke="{border}" stroke-width="{width}" stroke-linejoin="round"'
    )
    plain_attrs = f'fill="{fill}"'
    return (
        "  <g>\n"
        + _shapes(stroked_attrs)
        + "\n  </g>\n"
        + "  <g>\n"
        + _shapes(plain_attrs)
        + "\n  </g>"
    )


def _devices(
    stripe_width: float,
    star_stroke: float,
    stripe_color: str,
    star_color: str,
    hub_fill: str,
) -> str:
    """Stripes, then the hub over them, then the star.

    The hub is redrawn *after* the stripes rather than clipped out of them:
    that is what gives the clean circular edge where the stripes stop, which is
    the defining feature of this insignia.
    """
    stripes = "\n".join(
        f'      <line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>'
        for x1, y1, x2, y2 in stripe_lines()
    )
    return f"""  <g clip-path="url(#ms-wings)">
    <g stroke="{stripe_color}" stroke-width="{stripe_width}" stroke-linecap="butt">
{stripes}
    </g>
  </g>
  <!-- The hub, over the stripes: they stop at its circumference. -->
  <circle cx="{HUB_CENTER[0]}" cy="{HUB_CENTER[1]}" r="{HUB_RADIUS}" fill="{hub_fill}"/>
  <!-- Blue on blue: the field color, outlined in a lighter metallic blue. -->
  <polygon points="{star_points(*HUB_CENTER, STAR_OUTER, STAR_INNER)}"
           fill="none" stroke="{star_color}" stroke-width="{star_stroke}"
           stroke-linejoin="round"/>"""


def _defs() -> str:
    """Stripes are clipped to the wings only, so they stop at the hub."""
    return f"""  <defs>
    <clipPath id="ms-wings">
      <polygon points="{left_wing()}"/>
      <polygon points="{right_wing()}"/>
    </clipPath>
  </defs>"""


def build_logo() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 62" role="img"
     aria-label="Milsurp Monitor">
  <title>Milsurp Monitor</title>
  <desc>US Air Force Senior Airman insignia: a central hub bearing an outlined
        star, with three-striped wings either side.</desc>
{_defs()}
{_silhouette(FIELD_DARK, BORDER, 3.0)}
{_devices(STRIPE_WIDTH, 1.8, SILVER, STAR_OUTLINE, FIELD_DARK)}
</svg>
"""


def build_favicon() -> str:
    # Flat fill and heavier devices: thin strokes vanish at 16px.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 62">
{_defs()}
{_silhouette(FIELD_DARK, FIELD_DARK, 2.0)}
{_devices(5.4, 2.4, "#FFFFFF", STAR_OUTLINE_HI, FIELD_DARK)}
</svg>
"""


def build_react_component() -> str:
    """The header mark as a React component.

    Generated rather than hand-copied so the inline version cannot drift from
    the SVG files.
    """
    stripes = "\n".join(
        f'            <line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" />'
        for x1, y1, x2, y2 in stripe_lines()
    )
    shape_attrs = f'fill="{FIELD_DARK}" stroke="{BORDER}" strokeWidth="3" strokeLinejoin="round"'
    stroked = (
        f'        <circle cx="{HUB_CENTER[0]}" cy="{HUB_CENTER[1]}" r="{HUB_RADIUS}" {shape_attrs} />\n'
        f'        <polygon points="{left_wing()}" {shape_attrs} />\n'
        f'        <polygon points="{right_wing()}" {shape_attrs} />'
    )
    plain = (
        f'        <circle cx="{HUB_CENTER[0]}" cy="{HUB_CENTER[1]}" r="{HUB_RADIUS}" fill="{FIELD_DARK}" />\n'
        f'        <polygon points="{left_wing()}" fill="{FIELD_DARK}" />\n'
        f'        <polygon points="{right_wing()}" fill="{FIELD_DARK}" />'
    )
    return f"""/**
 * The Milsurp Monitor mark: the US Air Force Senior Airman (E-4) insignia.
 *
 * A central hub carrying an outlined star, with three-striped wings either
 * side. The star is blue on blue with a darker outline, not a white device.
 *
 * GENERATED FILE — do not edit by hand. Run `python scripts/brand.py`, which
 * writes this alongside marketing/images/logo.svg and the favicon from the
 * same geometry.
 */
import React from "react";

export default function Insignia({{ size = 30, className }}) {{
  return (
    <svg
      width={{size}}
      height={{(size * 62) / 100}}
      viewBox="0 0 100 62"
      className={{className}}
      role="img"
      aria-label="Milsurp Monitor"
    >
      <defs>
        <clipPath id="insignia-wings">
          <polygon points="{left_wing()}" />
          <polygon points="{right_wing()}" />
        </clipPath>
      </defs>

      {{/* Drawn twice: stroked, then plain on top, so the three overlapping
          shapes read as one silhouette. */}}
      <g>
{stroked}
      </g>
      <g>
{plain}
      </g>

      <g clipPath="url(#insignia-wings)">
        <g stroke="{SILVER}" strokeWidth="{STRIPE_WIDTH}">
{stripes}
        </g>
      </g>

      {{/* The hub is drawn over the stripes, so they stop at its edge. */}}
      <circle cx="{HUB_CENTER[0]}" cy="{HUB_CENTER[1]}" r="{HUB_RADIUS}" fill="{FIELD_DARK}" />

      {{/* Blue on blue, outlined in a lighter metallic blue. */}}
      <polygon
        points="{star_points(*HUB_CENTER, STAR_OUTER, STAR_INNER)}"
        fill="none"
        stroke="{STAR_OUTLINE}"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}}
"""


def _format_jsx(path: Path) -> None:
    """Run prettier over the generated component.

    Insignia.jsx is committed, imported by the app and read by people, so it is
    held to the same formatting as any other source file — and `make lint`
    checks it. Emitting prettier-clean JSX by hand would mean hand-wrapping
    every attribute list and re-guessing the rules whenever prettier changes,
    so the generator formats its own output instead. Without this, running this
    script is enough on its own to make the lint gate fail.

    This is the only ``subprocess`` use in the project (hence the ``# nosec
    B404`` on the import): one fixed argv, an absolute executable, no shell,
    and the only variable part is a path this module computed itself.
    """
    frontend = REPO_ROOT / "frontend"
    # The binary is invoked by absolute path rather than through npx: nothing
    # is resolved from PATH, so the command cannot be hijacked by a stray
    # executable earlier in it.
    prettier = frontend / "node_modules" / ".bin" / "prettier"
    if not prettier.exists():
        print("  ! prettier not installed — Insignia.jsx left unformatted")
        print("    run 'cd frontend && npm install', then 'make lint-fix'")
        return
    # Fixed argv, absolute executable, no shell, and the only variable part is
    # a path this module computed itself. Nothing here comes from outside.
    result = subprocess.run(  # nosec B603
        [str(prettier), "--write", str(path.relative_to(frontend))],
        cwd=frontend,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print(f"  formatted {path.relative_to(REPO_ROOT)}")
    else:
        print(f"  ! prettier failed on {path.relative_to(REPO_ROOT)}: {result.stderr.strip()}")


#: The mark as a bitmap, for email.
#:
#: An email client will not render an inline SVG and blocks remote images by
#: default, so the digest attaches this and references it by Content-ID. It is
#: drawn from the same geometry as everything above rather than exported by
#: hand, which is the whole point of this script: the mark has one definition.
#:
#: Twice the display size, for the same reason a thumbnail is: every mail
#: client on a phone is a high-density display.
EMAIL_MARK_WIDTH = 132
EMAIL_SCALE = 2
#: The navy the digest header is painted in. Kept beside the other colors here
#: rather than imported from the backend: this script has no dependency on the
#: application, and the two are checked against each other by a test.
EMAIL_HEADER_BG = "#0A2240"


def build_email_png() -> bytes:
    """The insignia as a PNG on the navy header, ready to attach to a message."""
    from io import BytesIO

    from PIL import Image, ImageDraw

    scale = EMAIL_MARK_WIDTH * EMAIL_SCALE / 100.0
    width = round(100 * scale)
    height = round(62 * scale)

    def at(point: tuple[float, float]) -> tuple[float, float]:
        return (point[0] * scale, point[1] * scale)

    # Drawn on the header's own navy rather than on transparency: a client that
    # ignores the alpha channel would otherwise put the mark on black.
    image = Image.new("RGB", (width, height), EMAIL_HEADER_BG)
    draw = ImageDraw.Draw(image)

    wings = [[at(point) for point in wing_points(right)] for right in (False, True)]
    cx, cy = HUB_CENTER
    hub = [
        at((cx - HUB_RADIUS, cy - HUB_RADIUS)),
        at((cx + HUB_RADIUS, cy + HUB_RADIUS)),
    ]

    for wing in wings:
        draw.polygon(wing, fill=FIELD_DARK)
    draw.ellipse(hub, fill=FIELD_DARK)

    # The stripes are clipped to the wings, the way the SVG clips them.
    stripes = Image.new("RGB", (width, height), FIELD_DARK)
    stripe_draw = ImageDraw.Draw(stripes)
    for x1, y1, x2, y2 in stripe_lines():
        stripe_draw.line(
            [at((x1, y1)), at((x2, y2))], fill=SILVER, width=max(1, round(STRIPE_WIDTH * scale))
        )
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    for wing in wings:
        mask_draw.polygon(wing, fill=255)
    image.paste(stripes, (0, 0), mask)

    # The hub goes over the stripes so they stop at its edge, then the star.
    draw = ImageDraw.Draw(image)
    draw.ellipse(hub, fill=FIELD_DARK)
    star = [
        at((float(x), float(y)))
        for x, y in (
            tuple(float(n) for n in pair.split(","))
            for pair in star_points(cx, cy, STAR_OUTER, STAR_INNER).split()
        )
    ]
    draw.line([*star, star[0]], fill=STAR_OUTLINE, width=max(1, round(1.8 * scale)), joint="curve")

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> int:
    for directory in (MARKETING, FRONTEND_PUBLIC, FRONTEND_SRC):
        directory.mkdir(parents=True, exist_ok=True)

    outputs = {
        MARKETING / "logo.svg": build_logo(),
        MARKETING / "favicon.svg": build_favicon(),
        FRONTEND_PUBLIC / "favicon.svg": build_favicon(),
        FRONTEND_SRC / "Insignia.jsx": build_react_component(),
    }
    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
        print(f"  wrote {path.relative_to(REPO_ROOT)}")

    _format_jsx(FRONTEND_SRC / "Insignia.jsx")

    png = build_email_png()
    EMAIL_MARK.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_MARK.write_bytes(png)
    print(f"  wrote {EMAIL_MARK.relative_to(REPO_ROOT)} ({len(png):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
