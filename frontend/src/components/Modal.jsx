/**
 * A modal dialog.
 *
 * Closes on Escape and on a backdrop click, and locks body scroll while open so
 * a phone does not scroll the page behind the sheet. On narrow screens it
 * presents as a bottom sheet (see .modal in layout.css), which is both easier to
 * reach one-handed and the platform convention.
 */
import React, { useEffect, useRef } from "react";
import { X } from "./Icons.jsx";

export default function Modal({ title, onClose, children, footer, labelledBy }) {
  const panelRef = useRef(null);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Move focus into the dialog so keyboard and screen-reader users are not
    // left behind on the page underneath.
    panelRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div
      className="modal-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy || "modal-title"}
        ref={panelRef}
        tabIndex={-1}
      >
        <div className="modal__head">
          <h2 id={labelledBy || "modal-title"}>{title}</h2>
          <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__foot">{footer}</div>}
      </div>
    </div>
  );
}
