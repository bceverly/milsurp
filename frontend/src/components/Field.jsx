/**
 * A labelled form field.
 *
 * Exists because of an accessibility trap: putting the hint text *inside* the
 * `<label>` element makes it part of the control's accessible name, so a screen
 * reader announces "Password At least 12 characters. Length matters far more
 * than punctuation…" as the field's name. The hint therefore lives outside the
 * label and is attached with `aria-describedby`, which is what that attribute
 * is for — it is announced after the name, as a description.
 *
 * Usage:
 *   <Field label="Password" hint="At least 12 characters." htmlFor="pw">
 *     {(id, describedBy) => (
 *       <input id={id} aria-describedby={describedBy} className="input" />
 *     )}
 *   </Field>
 */
import React, { useId } from "react";

export default function Field({ label, hint, error, children, className = "" }) {
  const generated = useId();
  const id = `${generated}-control`;
  const hintId = hint ? `${generated}-hint` : undefined;
  const errorId = error ? `${generated}-error` : undefined;
  // Both are announced after the name, error first so it is not buried.
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={`field ${className}`.trim()}>
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {children(id, describedBy)}
      {error && (
        <span className="field__hint field__hint--error" id={errorId} role="alert">
          {error}
        </span>
      )}
      {hint && (
        <span className="field__hint" id={hintId}>
          {hint}
        </span>
      )}
    </div>
  );
}
