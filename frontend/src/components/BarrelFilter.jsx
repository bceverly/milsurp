/**
 * The barrel filter: a length or a range of lengths, and whether it is threaded.
 *
 * Asked for on 2026-10-13: "search on barrel length in a range or with a
 * specific number that can be a decimal". One box rather than two, because the
 * two questions are typed the same way somebody says them: "4.5", "4-5",
 * "16+", "-5". A single length is matched to within a twentieth of an inch on
 * the server, so 4.5 finds a Glock 17's 4.49 (app/services/search.py). The
 * lengths and the threading are read from each listing's own words
 * (app/services/barrels.py); a listing that states neither is in no range.
 */
import { useEffect, useState } from "react";

const THREADED = [
  { value: "", label: "Any" },
  { value: "yes", label: "Threaded" },
  { value: "no", label: "Not threaded" },
];

const NUMBER = String.raw`(\d+(?:\.\d+)?|\.\d+)`;

/**
 * Read what was typed into a range: { min, max }, either null, or null for
 * text that is not a length. "4.5" is one length (min and max the same);
 * "4-5", "4 to 5" a range; "16+" and "-5" open at one end.
 */
export function parseBarrel(text) {
  const typed = (text || "").trim().replace(/["”″]|\binch(es)?\b|\bin\b/gi, "");
  if (!typed) return { min: null, max: null };
  let found = typed.match(new RegExp(`^${NUMBER}\\s*(?:-|–|—|to)\\s*${NUMBER}$`, "i"));
  if (found) {
    const [a, b] = [Number(found[1]), Number(found[2])];
    return { min: Math.min(a, b), max: Math.max(a, b) };
  }
  found =
    typed.match(new RegExp(`^${NUMBER}\\s*\\+$`)) ||
    typed.match(new RegExp(`^(?:>=?|≥)\\s*${NUMBER}$`));
  if (found) return { min: Number(found[1]), max: null };
  found = typed.match(new RegExp(`^(?:-|–|<=?|≤|up to)\\s*${NUMBER}$`, "i"));
  if (found) return { min: null, max: Number(found[1]) };
  found = typed.match(new RegExp(`^${NUMBER}$`));
  if (found) return { min: Number(found[1]), max: Number(found[1]) };
  return null;
}

/** The text for a stored range, the way it would be typed back in. */
export function barrelText(min, max) {
  if (min == null && max == null) return "";
  if (min != null && max != null) return min === max ? `${min}` : `${min}-${max}`;
  if (min != null) return `${min}+`;
  return `-${max}`;
}

export default function BarrelFilter({ min, max, threaded, onChange }) {
  const [text, setText] = useState(barrelText(min, max));
  const [invalid, setInvalid] = useState(false);

  // A chip cleared or a saved search opened changes the range from outside.
  useEffect(() => {
    setText(barrelText(min, max));
    setInvalid(false);
  }, [min, max]);

  const apply = () => {
    const range = parseBarrel(text);
    if (range === null) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (range.min !== min || range.max !== max) onChange({ ...range, threaded });
  };

  return (
    <div className="barrel-filter">
      <label className="barrel-filter__label" htmlFor="barrel-length">
        Length, in inches
      </label>
      <input
        id="barrel-length"
        className={`input input--sm ${invalid ? "input--invalid" : ""}`}
        type="text"
        inputMode="decimal"
        placeholder="e.g. 4.5, 4-5, 16+"
        value={text}
        aria-invalid={invalid || undefined}
        aria-describedby="barrel-length-hint"
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
        id="barrel-length-hint"
        className={`barrel-filter__hint ${invalid ? "error" : ""}`}
      >
        {invalid
          ? "A length (4.5), a range (4-5), or one end (16+, -5)."
          : "Only listings that state a length."}
      </div>
      {THREADED.map((option) => (
        <label className="facet__option" key={option.value || "any"}>
          <input
            type="radio"
            name="threaded"
            checked={(threaded || "") === option.value}
            onChange={() => onChange({ min, max, threaded: option.value || null })}
          />
          <span className="facet__option-label">{option.label}</span>
        </label>
      ))}
    </div>
  );
}
