import { useEffect, useState } from "react";
import { useDebounced } from "../hooks.js";

/**
 * A text box that offers the armory's spellings as you type.
 *
 * For the Maker and Caliber of a collection row, and of a saved search made
 * from scratch (2026-10-15). Free text still stands --
 * the armory does not know every maker -- but picking its spelling is what the
 * catalog files listings under, so "6.5x52mm Carcano" finds the ammunition
 * that "6.5 carcano" would have to be read and normalized to find.
 *
 * The list shows while the box has focus and something typed, closes on a
 * pick, on Escape and on leaving the box. A pick is taken on mouse-down,
 * before the box loses focus and the list with it.
 */
export default function ArmoryInput({
  id,
  label,
  value,
  onChange,
  lookup,
  hint,
  maxLength,
}) {
  const [open, setOpen] = useState(false);
  const [choices, setChoices] = useState([]);
  const term = useDebounced(value, 200);

  useEffect(() => {
    if (!open || !term.trim()) {
      setChoices([]);
      return undefined;
    }
    let live = true;
    lookup(term)
      .then((rows) => live && setChoices(rows))
      .catch(() => live && setChoices([]));
    return () => {
      live = false;
    };
  }, [open, term, lookup]);

  const shown = choices.filter(
    (choice) => choice.name.toLowerCase() !== value.trim().toLowerCase(),
  );
  return (
    <div className="field armory-input">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        value={value}
        maxLength={maxLength}
        autoComplete="off"
        aria-describedby={hint ? `${id}-hint` : undefined}
        role="combobox"
        aria-autocomplete="list"
        aria-controls={`${id}-choices`}
        aria-expanded={open && shown.length > 0}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && open) {
            event.stopPropagation();
            setOpen(false);
          }
        }}
      />
      {open && shown.length > 0 && (
        <ul
          id={`${id}-choices`}
          className="armory-input__choices"
          role="listbox"
          aria-label={`${label} suggestions`}
        >
          {shown.slice(0, 8).map((choice) => (
            <li key={choice.name} role="option" aria-selected="false">
              <button
                type="button"
                className="model-picker__choice"
                onMouseDown={(event) => {
                  event.preventDefault();
                  onChange(choice.name);
                  setOpen(false);
                }}
              >
                {choice.name}
                {choice.country && <span className="muted"> · {choice.country}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {hint && (
        <p className="field__hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
    </div>
  );
}
