/**
 * The Armory's Serial tables tab: the published serial-to-date tables, a
 * range to a row (models.SerialRange, 2026-10-19).
 *
 * A listing whose serial falls in a range is dated by it, ahead of the
 * estimate from other listings (app/services/serials.py), and every change
 * here re-dates the model's listings at once. Each range names where it was
 * read, and must: a table typed from memory is worse than none, because it is
 * believed.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import Field from "./Field.jsx";
import Modal from "./Modal.jsx";
import { Plus, Trash } from "./Icons.jsx";

const EMPTY = {
  model: "",
  maker: "",
  prefix: "",
  suffix: "",
  serial_low: "",
  serial_high: "",
  year_from: "",
  year_to: "",
  source: "",
  note: "",
};

function yearsText(from, to) {
  return from === to ? String(from) : `${from}–${to}`;
}

function serialText({ prefix, suffix, serial_low: low, serial_high: high }) {
  const one = (n) => `${prefix || ""}${n.toLocaleString()}${suffix || ""}`;
  return `${one(low)} – ${one(high)}`;
}

/** A source as a link where it is an address, as text where it is a book. */
function Source({ text }) {
  if (!/^https?:\/\//i.test(text)) return text;
  let where = text;
  try {
    where = new URL(text).hostname.replace(/^www\./, "");
  } catch {
    // Not an address after all: shown as written.
  }
  return (
    <a href={text} target="_blank" rel="noopener noreferrer" title={text}>
      {where}
    </a>
  );
}

export default function SerialTables({ search, models, makers, onChanged }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);
  const [editing, setEditing] = useState(null);
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(async () => {
    const params = {};
    if (search.trim()) params.search = search.trim();
    setRows(await api.serialRanges(params));
  }, [search]);

  useEffect(() => {
    setRows(null);
    load().catch((err) => setError(err.message));
  }, [load]);

  const modelIds = useMemo(
    () => new Map(models.map((m) => [m.name.toLowerCase(), m.id])),
    [models],
  );
  const makerIds = useMemo(
    () => new Map(makers.map((m) => [m.name.toLowerCase(), m.id])),
    [makers],
  );

  const open = (row) => {
    setFormError("");
    setEditing(
      row
        ? {
            id: row.id,
            model: row.model_name,
            maker: row.maker || "",
            prefix: row.prefix || "",
            suffix: row.suffix || "",
            serial_low: String(row.serial_low),
            serial_high: String(row.serial_high),
            year_from: String(row.year_from),
            year_to: String(row.year_to),
            source: row.source,
            note: row.note || "",
          }
        : { ...EMPTY },
    );
  };

  const save = async (event) => {
    event.preventDefault();
    const modelId = modelIds.get(editing.model.trim().toLowerCase());
    if (!modelId) {
      setFormError(`No model called "${editing.model.trim()}".`);
      return;
    }
    let makerId = null;
    if (editing.maker.trim()) {
      makerId = makerIds.get(editing.maker.trim().toLowerCase());
      if (!makerId) {
        setFormError(`No manufacturer called "${editing.maker.trim()}".`);
        return;
      }
    }
    const number = (text) => Number(String(text).replace(/,/g, ""));
    const yearTo = editing.year_to.trim() ? editing.year_to : editing.year_from;
    const body = {
      model_id: modelId,
      manufacturer_id: makerId,
      prefix: editing.prefix.trim().toUpperCase(),
      suffix: editing.suffix.trim().toUpperCase(),
      serial_low: number(editing.serial_low),
      serial_high: number(editing.serial_high),
      year_from: number(editing.year_from),
      year_to: number(yearTo),
      source: editing.source.trim(),
      note: editing.note.trim() || null,
    };
    setBusy(true);
    setFormError("");
    try {
      if (editing.id) await api.updateSerialRange(editing.id, body);
      else await api.addSerialRange(body);
      setMessage(editing.id ? "Range saved." : "Range added.");
      setEditing(null);
      await load();
      onChanged?.();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row) => {
    setDeleting(null);
    setBusy(true);
    setError(null);
    try {
      await api.deleteSerialRange(row.id);
      setMessage("Range deleted.");
      await load();
      onChanged?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const set = (name) => (event) => setEditing({ ...editing, [name]: event.target.value });

  return (
    <div data-testid="serials-tab">
      <div className="armory-count-row">
        <h2 className="armory-count">
          Serial ranges
          {search.trim() && <> matching “{search.trim()}”</>} (
          {rows ? rows.length.toLocaleString() : "…"})
        </h2>
        <button type="button" className="btn btn--primary btn--sm" onClick={() => open()}>
          <Plus /> Add a range
        </button>
      </div>
      <p className="muted">
        A listing whose serial falls in a range is dated by it. Every range names where it
        was read.
      </p>
      {message && <p className="alert alert--success">{message}</p>}
      {error && <p className="alert alert--error">{error}</p>}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Maker</th>
              <th>Serials</th>
              <th>Made</th>
              <th>Source</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows === null && (
              <tr>
                <td colSpan={6} className="loading-row">
                  <span className="spinner" aria-label="Loading" />
                </td>
              </tr>
            )}
            {rows &&
              rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.model_name}</td>
                  <td>{row.maker || "—"}</td>
                  <td>
                    {serialText(row)}
                    {row.note && <div className="muted">{row.note}</div>}
                  </td>
                  <td>{yearsText(row.year_from, row.year_to)}</td>
                  <td>
                    <Source text={row.source} />
                  </td>
                  <td className="table__actions">
                    <button
                      type="button"
                      className="btn btn--secondary btn--sm"
                      aria-label={`Edit ${row.model_name} ${row.serial_low}`}
                      onClick={() => open(row)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      aria-label={`Delete ${row.model_name} ${row.serial_low}`}
                      disabled={busy}
                      onClick={() => setDeleting(row)}
                    >
                      <Trash />
                    </button>
                  </td>
                </tr>
              ))}
            {rows && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="loading-row">
                  No serial ranges{search.trim() ? " match the search" : ""}.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {deleting && (
        <Modal title="Delete this range?" onClose={() => setDeleting(null)}>
          <p>
            {deleting.model_name}
            {deleting.maker ? `, ${deleting.maker}` : ""}, {serialText(deleting)}, made{" "}
            {yearsText(deleting.year_from, deleting.year_to)}. Its listings are dated
            again without it.
          </p>
          <div className="page-head__actions">
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => setDeleting(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn--danger"
              disabled={busy}
              onClick={() => remove(deleting)}
            >
              Delete
            </button>
          </div>
        </Modal>
      )}

      {editing && (
        <Modal
          title={editing.id ? "Edit a serial range" : "Add a serial range"}
          onClose={() => setEditing(null)}
        >
          <form onSubmit={save}>
            {formError && <p className="alert alert--error">{formError}</p>}
            <div className="form-row form-row--2">
              <Field label="Model">
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="input"
                    list="serial-models"
                    required
                    value={editing.model}
                    onChange={set("model")}
                  />
                )}
              </Field>
              <Field label="Maker" hint="Blank when only one maker numbered the model.">
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="input"
                    list="serial-makers"
                    value={editing.maker}
                    onChange={set("maker")}
                  />
                )}
              </Field>
            </div>
            <datalist id="serial-models">
              {models.map((m) => (
                <option key={m.id} value={m.name} />
              ))}
            </datalist>
            <datalist id="serial-makers">
              {makers.map((m) => (
                <option key={m.id} value={m.name} />
              ))}
            </datalist>
            <div className="form-row form-row--3">
              <Field label="Prefix" hint="Letters before the number, if any.">
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="input"
                    value={editing.prefix}
                    onChange={set("prefix")}
                  />
                )}
              </Field>
              <Field label="First serial">
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="input"
                    inputMode="numeric"
                    required
                    value={editing.serial_low}
                    onChange={set("serial_low")}
                  />
                )}
              </Field>
              <Field label="Last serial">
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="input"
                    inputMode="numeric"
                    required
                    value={editing.serial_high}
                    onChange={set("serial_high")}
                  />
                )}
              </Field>
            </div>
            <div className="form-row form-row--3">
              <Field label="Suffix" hint="Letters after the number, if any.">
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="input"
                    value={editing.suffix}
                    onChange={set("suffix")}
                  />
                )}
              </Field>
              <Field label="Made from">
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="input"
                    inputMode="numeric"
                    required
                    value={editing.year_from}
                    onChange={set("year_from")}
                  />
                )}
              </Field>
              <Field label="Made to" hint="Blank for the same year.">
                {(id, describedBy) => (
                  <input
                    id={id}
                    aria-describedby={describedBy}
                    className="input"
                    inputMode="numeric"
                    value={editing.year_to}
                    onChange={set("year_to")}
                  />
                )}
              </Field>
            </div>
            <Field
              label="Source"
              hint="Where this was read: a page's address, or a book and its page."
            >
              {(id, describedBy) => (
                <input
                  id={id}
                  aria-describedby={describedBy}
                  className="input"
                  required
                  value={editing.source}
                  onChange={set("source")}
                />
              )}
            </Field>
            <Field label="Note">
              {(id, describedBy) => (
                <input
                  id={id}
                  aria-describedby={describedBy}
                  className="input"
                  value={editing.note}
                  onChange={set("note")}
                />
              )}
            </Field>
            <div className="page-head__actions">
              <button
                type="button"
                className="btn btn--secondary"
                onClick={() => setEditing(null)}
              >
                Cancel
              </button>
              <button type="submit" className="btn btn--primary" disabled={busy}>
                {editing.id ? "Save" : "Add"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
