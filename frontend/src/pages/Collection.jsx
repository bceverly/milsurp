/**
 * Your collection: what you own, what you paid, and what it is worth now.
 *
 * Everything else here is about buying; this is about having bought. Each gun
 * is matched to an armory model from its title, the way a listing is, and
 * valued against that model's listings -- what they were asking when they left
 * the shelf where there is a sample of that, what they are asking now where
 * there is not. See services/collection.py.
 *
 * The worth is always said with its basis beside it. "About $450" means
 * nothing without "what K31s were asking when they left the shelf", and a gun
 * the market cannot price says so rather than showing a number.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatDate, formatMoney } from "../format.js";
import Modal from "../components/Modal.jsx";
import Field from "../components/Field.jsx";
import { Box, Download, Plus, Trash } from "../components/Icons.jsx";

const GRADES = [
  { value: "", label: "Not graded" },
  { value: "like_new", label: "Like new" },
  { value: "excellent", label: "Excellent" },
  { value: "very_good", label: "Very good" },
  { value: "good", label: "Good" },
  { value: "fair", label: "Fair" },
  { value: "poor", label: "Poor" },
];

const EMPTY = {
  title: "",
  caliber: "",
  manufacturer: "",
  condition_grade: "",
  acquired_on: "",
  paid: "",
  acquired_from: "",
  notes: "",
};

/** The form's strings as the API wants them: blanks become nulls. */
function payloadOf(form) {
  const text = (value) => (value.trim() === "" ? null : value.trim());
  return {
    title: form.title.trim(),
    caliber: text(form.caliber),
    manufacturer: text(form.manufacturer),
    condition_grade: form.condition_grade || null,
    acquired_on: form.acquired_on || null,
    paid: form.paid === "" ? null : Number(form.paid),
    acquired_from: text(form.acquired_from),
    notes: text(form.notes),
  };
}

function formOf(row) {
  return Object.fromEntries(
    Object.keys(EMPTY).map((key) => [key, row[key] == null ? "" : String(row[key])]),
  );
}

/** What the worth figure was worked out from, in words. */
function basisOf(valuation, model) {
  const like = valuation.like_for_like ? " in the same condition" : "";
  return valuation.basis === "left"
    ? `What ${model}s${like} were asking when they left the shelf`
    : `What ${model}s${like} are asking now`;
}

function Totals({ totals }) {
  if (!totals.count) return null;
  const change =
    totals.compared_count > 0 && totals.compared_paid > 0
      ? (totals.compared_value - totals.compared_paid) / totals.compared_paid
      : null;
  return (
    <div className="week-stats collection-totals" data-testid="collection-totals">
      <div className="week-stat">
        <span className="week-stat__value">{totals.count}</span>
        <span className="week-stat__label">{totals.count === 1 ? "gun" : "guns"}</span>
      </div>
      <div className="week-stat">
        <span className="week-stat__value">{formatMoney(totals.paid)}</span>
        <span className="week-stat__label">
          paid{totals.paid_count < totals.count ? ` (${totals.paid_count} say)` : ""}
        </span>
      </div>
      <div className="week-stat">
        <span className="week-stat__value">{formatMoney(totals.value)}</span>
        <span className="week-stat__label">
          worth about
          {totals.valued_count < totals.count
            ? ` (${totals.valued_count} the market can price)`
            : ""}
        </span>
      </div>
      {change !== null && (
        <div className="week-stat">
          <span className="week-stat__value">
            {change >= 0 ? "+" : "−"}
            {Math.abs(Math.round(change * 100))}%
          </span>
          <span className="week-stat__label">
            on what you paid, over the {totals.compared_count} with both
          </span>
        </div>
      )}
    </div>
  );
}

function Editor({ row, onClose, onSaved }) {
  const [form, setForm] = useState(row ? formOf(row) : EMPTY);
  const [declined, setDeclined] = useState(row?.model_declined || false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = payloadOf(form);
      const saved = row
        ? await api.updateCollectionItem(row.id, { ...body, model_declined: declined })
        : await api.addToCollection(body);
      onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const input = (key, label, props = {}, hint = undefined) => (
    <Field label={label} hint={hint}>
      {(id, describedBy) => (
        <input
          id={id}
          aria-describedby={describedBy}
          className="input"
          value={form[key]}
          onChange={set(key)}
          {...props}
        />
      )}
    </Field>
  );

  return (
    <Modal
      title={row ? `Edit ${row.title}` : "Add a gun"}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn--primary"
            type="submit"
            form="collection-form"
            disabled={busy || !form.title.trim()}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <form id="collection-form" onSubmit={save}>
        {error && <p className="alert alert--error">{error}</p>}
        {input(
          "title",
          "What it is",
          { autoFocus: true, maxLength: 200, placeholder: "Swiss K31, 1943" },
          "Written the way a dealer would title it. The model is matched from this.",
        )}
        {row?.model && !declined && (
          <p className="muted collection-match">
            Matched to <strong>{row.model}</strong>.{" "}
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setDeclined(true)}
            >
              That is not it
            </button>
          </p>
        )}
        {row && declined && (
          <p className="muted collection-match">
            Not matched to a model, so it cannot be valued.{" "}
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => setDeclined(false)}
            >
              Match it again
            </button>
          </p>
        )}
        <div className="collection-form__row">
          {input("manufacturer", "Maker", { maxLength: 128 })}
          {input("caliber", "Caliber", { maxLength: 64 })}
        </div>
        <Field
          label="Condition"
          hint="Your own grade. The value is compared against guns in the same condition where there are enough."
        >
          {(id, describedBy) => (
            <select
              id={id}
              aria-describedby={describedBy}
              className="select"
              value={form.condition_grade}
              onChange={set("condition_grade")}
            >
              {GRADES.map((grade) => (
                <option key={grade.value} value={grade.value}>
                  {grade.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <div className="collection-form__row">
          {input("paid", "Paid", { inputMode: "decimal", placeholder: "$" })}
          {input("acquired_on", "When", { type: "date" })}
        </div>
        {input("acquired_from", "Where from", { maxLength: 128 })}
        <Field
          label="Notes"
          hint="Anything you want to keep with it. There is deliberately no serial number field."
        >
          {(id, describedBy) => (
            <textarea
              id={id}
              aria-describedby={describedBy}
              className="input"
              rows={3}
              maxLength={4000}
              value={form.notes}
              onChange={set("notes")}
            />
          )}
        </Field>
      </form>
    </Modal>
  );
}

export default function Collection() {
  useTitle("Collection");
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [confirming, setConfirming] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setState(await api.collection());
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function remove(row) {
    await api.removeFromCollection(row.id);
    setConfirming(null);
    load();
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Collection</h1>
          <p>
            What you own, what you paid, and what the market says each is worth — valued
            against the same model&rsquo;s listings, and in the same condition where there
            are enough. Use &ldquo;I bought this&rdquo; on a listing to add one from here.
          </p>
        </div>
        <div className="page-head__actions">
          {state?.items?.length > 0 && (
            <a className="btn btn--secondary" href={api.collectionExportUrl()} download>
              <Download size={15} /> Download
            </a>
          )}
          <button className="btn btn--primary" onClick={() => setEditing("new")}>
            <Plus size={15} /> Add a gun
          </button>
        </div>
      </div>

      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      {!state && !error && <p className="muted">Loading…</p>}

      {state && state.items.length === 0 && (
        <div className="empty">
          <Box size={28} />
          <h3>Nothing here yet</h3>
          <p>
            Add a gun you own, or choose &ldquo;I bought this&rdquo; on a{" "}
            <Link to="/">listing</Link> you bought.
          </p>
        </div>
      )}

      {state && state.items.length > 0 && (
        <>
          <Totals totals={state.totals} />
          <div className="panel">
            <div className="table-wrap">
              <table className="table" data-testid="collection-table">
                <thead>
                  <tr>
                    <th>Gun</th>
                    <th>Condition</th>
                    <th>Acquired</th>
                    <th>Paid</th>
                    <th>Worth about</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {state.items.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => setEditing(row)}
                        >
                          {row.title}
                        </button>
                        <div className="muted collection-sub">
                          {[row.model, row.manufacturer, row.caliber]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      </td>
                      <td>{row.condition_grade_label || "—"}</td>
                      <td>
                        {row.acquired_on ? formatDate(row.acquired_on) : "—"}
                        {row.acquired_from && (
                          <div className="muted collection-sub">{row.acquired_from}</div>
                        )}
                      </td>
                      <td>{row.paid != null ? formatMoney(row.paid) : "—"}</td>
                      <td>
                        {row.valuation ? (
                          <>
                            <strong>{formatMoney(row.valuation.estimate)}</strong>
                            <div className="muted collection-sub">
                              {basisOf(row.valuation, row.model)}
                            </div>
                          </>
                        ) : (
                          <span className="muted">
                            {row.model
                              ? "Too few listings to say"
                              : "Not matched to a model"}
                          </span>
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          aria-label={`Remove ${row.title}`}
                          onClick={() => setConfirming(row)}
                        >
                          <Trash size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {editing && (
        <Editor
          row={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}

      {confirming && (
        <Modal
          title={`Remove ${confirming.title}?`}
          onClose={() => setConfirming(null)}
          footer={
            <>
              <button className="btn btn--secondary" onClick={() => setConfirming(null)}>
                Keep it
              </button>
              <button className="btn btn--danger" onClick={() => remove(confirming)}>
                Remove
              </button>
            </>
          }
        >
          <p>
            It comes off your collection and out of the totals. This cannot be undone.
          </p>
        </Modal>
      )}
    </section>
  );
}
