/**
 * The capacity filter: a number of rounds, or a range of them.
 *
 * Asked for on 2026-10-16, with the barrel filter as its pattern: one box,
 * typed the way somebody says it -- "15", "10-17", "15+", "-8". A listing's
 * capacity is what it states, or else its model's standard capacity from the
 * armory (app/services/capacity.py); one with neither is in no range.
 */
import { useEffect, useState } from "react";
import { barrelText } from "./BarrelFilter.jsx";

/**
 * What was typed, as { min, max } -- either null -- or null for text that is
 * not a number of rounds. Whole numbers only: nobody holds 15.5 rounds.
 */
export function parseCapacity(text) {
  const typed = (text || "")
    .trim()
    .replace(/\b(rounds?|rds?)\b/gi, "")
    .trim();
  if (!typed) return { min: null, max: null };
  let found = typed.match(/^(\d+)\s*(?:-|–|—|to)\s*(\d+)$/i);
  if (found) {
    const [a, b] = [Number(found[1]), Number(found[2])];
    return { min: Math.min(a, b), max: Math.max(a, b) };
  }
  found = typed.match(/^(\d+)\s*\+$/) || typed.match(/^(?:>=?|≥)\s*(\d+)$/);
  if (found) return { min: Number(found[1]), max: null };
  found = typed.match(/^(?:-|–|<=?|≤|up to)\s*(\d+)$/i);
  if (found) return { min: null, max: Number(found[1]) };
  found = typed.match(/^(\d+)$/);
  if (found) return { min: Number(found[1]), max: Number(found[1]) };
  return null;
}

/** The text for a stored range, typed back in: "15", "10-17", "15+", "-8". */
export const capacityText = barrelText;

export default function CapacityFilter({ min, max, onChange }) {
  const [text, setText] = useState(capacityText(min, max));
  const [invalid, setInvalid] = useState(false);

  // A chip cleared or a saved search opened changes the range from outside.
  useEffect(() => {
    setText(capacityText(min, max));
    setInvalid(false);
  }, [min, max]);

  const apply = () => {
    const range = parseCapacity(text);
    if (range === null) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (range.min !== min || range.max !== max) onChange(range);
  };

  return (
    <div className="barrel-filter">
      <label className="barrel-filter__label" htmlFor="capacity-rounds">
        Rounds
      </label>
      <input
        id="capacity-rounds"
        className={`input input--sm ${invalid ? "input--invalid" : ""}`}
        type="text"
        inputMode="numeric"
        placeholder="e.g. 15, 10-17, 15+"
        value={text}
        aria-invalid={invalid || undefined}
        aria-describedby="capacity-rounds-hint"
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
        id="capacity-rounds-hint"
        className={`barrel-filter__hint ${invalid ? "error" : ""}`}
      >
        {invalid
          ? "A number (15), a range (10-17), or one end (15+, -8)."
          : "Its stated capacity, or its model's standard one."}
      </div>
    </div>
  );
}
