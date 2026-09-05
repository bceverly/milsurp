/**
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

export default function Insignia({ size = 30, className }) {
  return (
    <svg
      width={size}
      height={(size * 62) / 100}
      viewBox="0 0 100 62"
      className={className}
      role="img"
      aria-label="Milsurp Monitor"
    >
      <defs>
        <clipPath id="insignia-wings">
          <polygon points="2.00,1.45 56.00,32.61 44.00,53.39 2.00,29.15" />
          <polygon points="98.00,1.45 44.00,32.61 56.00,53.39 98.00,29.15" />
        </clipPath>
      </defs>

      {/* Drawn twice: stroked, then plain on top, so the three overlapping
          shapes read as one silhouette. */}
      <g>
        <circle
          cx="50.0"
          cy="43.0"
          r="15.0"
          fill="#12294A"
          stroke="#0A2240"
          strokeWidth="3"
          strokeLinejoin="round"
        />
        <polygon
          points="2.00,1.45 56.00,32.61 44.00,53.39 2.00,29.15"
          fill="#12294A"
          stroke="#0A2240"
          strokeWidth="3"
          strokeLinejoin="round"
        />
        <polygon
          points="98.00,1.45 44.00,32.61 56.00,53.39 98.00,29.15"
          fill="#12294A"
          stroke="#0A2240"
          strokeWidth="3"
          strokeLinejoin="round"
        />
      </g>
      <g>
        <circle cx="50.0" cy="43.0" r="15.0" fill="#12294A" />
        <polygon points="2.00,1.45 56.00,32.61 44.00,53.39 2.00,29.15" fill="#12294A" />
        <polygon points="98.00,1.45 44.00,32.61 56.00,53.39 98.00,29.15" fill="#12294A" />
      </g>

      <g clipPath="url(#insignia-wings)">
        <g stroke="#E8EDF5" strokeWidth="5.5">
          <line x1="-8.00" y1="0.29" x2="62.66" y2="41.07" />
          <line x1="-8.00" y1="9.53" x2="58.66" y2="48.00" />
          <line x1="-8.00" y1="18.77" x2="54.66" y2="54.93" />
          <line x1="108.00" y1="0.29" x2="37.34" y2="41.07" />
          <line x1="108.00" y1="9.53" x2="41.34" y2="48.00" />
          <line x1="108.00" y1="18.77" x2="45.34" y2="54.93" />
        </g>
      </g>

      {/* The hub is drawn over the stripes, so they stop at its edge. */}
      <circle cx="50.0" cy="43.0" r="15.0" fill="#12294A" />

      {/* Blue on blue, outlined in a lighter metallic blue. */}
      <polygon
        points="50.00,33.40 52.35,39.76 59.13,40.03 53.80,44.24 55.64,50.77 50.00,47.00 44.36,50.77 46.20,44.24 40.87,40.03 47.65,39.76"
        fill="none"
        stroke="#4E7FB8"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}
