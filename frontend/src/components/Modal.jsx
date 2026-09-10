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

/**
 * How many dialogs are open, and what the page scrolled like before the first
 * of them. Module scope on purpose: the lock is a property of the *page*, and
 * every dialog reading and restoring its own idea of it is what broke.
 *
 * Two ways it broke, and only one of them needed two dialogs:
 *
 * - **Stacked.** The armory's edit dialog opens the primary-name dialog on top
 *   of it. The second captured "hidden" — set by the first — as the value to
 *   go back to, so closing both left the page unscrollable.
 * - **One dialog, re-rendered.** The effect depended on `onClose`, which is an
 *   inline arrow at every call site and therefore new on every render. So the
 *   effect tore down and set up again whenever the dialog re-rendered, and any
 *   re-render while open (typing in a field, choosing from a select) captured
 *   its own "hidden" and restored that on close.
 *
 * Counting fixes both: the value is captured when the count goes to one and
 * restored when it comes back to zero, whatever happens in between.
 */
let openDialogs = 0;
let restoreOverflowTo = "";

export default function Modal({ title, onClose, children, footer, labelledBy }) {
  const panelRef = useRef(null);

  // Deliberately no dependencies. This runs once per mounted dialog, and must:
  // see the note above.
  useEffect(() => {
    if (openDialogs === 0) restoreOverflowTo = document.body.style.overflow;
    openDialogs += 1;
    document.body.style.overflow = "hidden";
    // Move focus into the dialog so keyboard and screen-reader users are not
    // left behind on the page underneath.
    panelRef.current?.focus();
    return () => {
      openDialogs = Math.max(0, openDialogs - 1);
      if (openDialogs === 0) document.body.style.overflow = restoreOverflowTo;
    };
  }, []);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
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
