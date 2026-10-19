/**
 * The year made filter: a year, or a range of them.
 *
 * Asked for on 2026-10-17, with the capacity filter as its pattern: one box,
 * typed the way a collector says it -- "1943", "1940-1945", "1950+", "-1898",
 * "pre-1899", "after 1945". A listing's year is the one its page shows: the
 * year it states, the one its serial places, or else the C&R reader's. One
 * made over a span ("1943-1944", "circa 1920s") is in any range the span
 * touches; one with no year is in none.
 */
import { useEffect, useState } from "react";

const YEAR = String.raw`(1[5-9]\d\d|20\d\d)`;

/**
 * What was typed, as { min, max } -- either null -- or null for text that is
 * not a year.
 */
export function parseYearMade(text) {
  const typed = (text || "").trim();
  if (!typed) return { min: null, max: null };
  let found = typed.match(new RegExp(`^${YEAR}\\s*(?:-|–|—|to)\\s*${YEAR}$`, "i"));
  if (found) {
    const [a, b] = [Number(found[1]), Number(found[2])];
    return { min: Math.min(a, b), max: Math.max(a, b) };
  }
  // "pre-1899" and "before 1899" leave the year out: antique means made
  // before 1899, so 1898 is the last of it. "after 1945" likewise.
  found = typed.match(new RegExp(`^(?:pre|before)[\\s-]*${YEAR}$`, "i"));
  if (found) return { min: null, max: Number(found[1]) - 1 };
  found = typed.match(new RegExp(`^(?:post|after)[\\s-]*${YEAR}$`, "i"));
  if (found) return { min: Number(found[1]) + 1, max: null };
  found =
    typed.match(new RegExp(`^${YEAR}\\s*(?:\\+|or later|and later)$`, "i")) ||
    typed.match(new RegExp(`^(?:>=?|≥|since)\\s*${YEAR}$`, "i"));
  if (found) return { min: Number(found[1]), max: null };
  found =
    typed.match(new RegExp(`^(?:-|–|<=?|≤|up to|until)\\s*${YEAR}$`, "i")) ||
    typed.match(new RegExp(`^${YEAR}\\s*(?:or earlier|and earlier)$`, "i"));
  if (found) return { min: null, max: Number(found[1]) };
  found = typed.match(new RegExp(`^${YEAR}$`));
  if (found) return { min: Number(found[1]), max: Number(found[1]) };
  return null;
}

/** A stored range, in words: "1943", "1940–1945", "1950 or later". */
export function yearMadeText(min, max) {
  if (min === null && max === null) return "";
  if (min === max) return String(min);
  if (min === null) return `${max} or earlier`;
  if (max === null) return `${min} or later`;
  return `${min}–${max}`;
}

export default function YearMadeFilter({ min, max, onChange }) {
  const [text, setText] = useState(yearMadeText(min, max));
  const [invalid, setInvalid] = useState(false);

  // A chip cleared or a saved search opened changes the range from outside.
  useEffect(() => {
    setText(yearMadeText(min, max));
    setInvalid(false);
  }, [min, max]);

  const apply = () => {
    const range = parseYearMade(text);
    if (range === null) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (range.min !== min || range.max !== max) onChange(range);
  };

  return (
    <div className="barrel-filter">
      <label className="barrel-filter__label" htmlFor="year-made">
        Years
      </label>
      <input
        id="year-made"
        className={`input input--sm ${invalid ? "input--invalid" : ""}`}
        type="text"
        placeholder="e.g. 1943, 1940-1945, pre-1899"
        value={text}
        aria-invalid={invalid || undefined}
        aria-describedby="year-made-hint"
        onChange={(event) => setText(event.target.value)}
        onBlur={apply}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            apply();
          }
        }}
      />
      <div
        id="year-made-hint"
        className={`barrel-filter__hint ${invalid ? "error" : ""}`}
      >
        {invalid
          ? "A year (1943), a range (1940-1945), or one end (1950+, pre-1899)."
          : "The year it states, or its serial places."}
      </div>
    </div>
  );
}
