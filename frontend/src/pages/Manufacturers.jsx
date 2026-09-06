/**
 * The maker list, editable.
 *
 * This list used to be a tuple of regular expressions in the backend, which
 * meant that teaching the site about one more maker was a commit and a deploy
 * — for a fact about the surplus market that whoever runs the site knows and
 * the programmer does not.
 *
 * Two things about it are worth knowing at the keyboard, and the page says
 * both rather than leaving them to be discovered:
 *
 * - Order decides ties. "Mosin-Nagant" has to be tried before "Nagant" or
 *   every Mosin-Nagant ends up filed under Nagant.
 * - Saving rewrites listings. The count that comes back is how many, which is
 *   the only honest way to show what an edit to one row just did.
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import Modal from "../components/Modal.jsx";
import Field from "../components/Field.jsx";
import { Plus, Refresh, Trash } from "../components/Icons.jsx";

const EMPTY = { name: "", aliases: "", position: 1000, enabled: true, notes: "" };

function countLabel(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function MakerForm({ maker, onSubmit, error }) {
  const editing = Boolean(maker);
  const [form, setForm] = useState(
    editing
      ? { ...EMPTY, ...maker, aliases: maker.aliases || "", notes: maker.notes || "" }
      : EMPTY,
  );

  const set = (key) => (event) => {
    const value =
      event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((current) => ({ ...current, [key]: value }));
  };

  function submit(event) {
    event.preventDefault();
    onSubmit({
      name: form.name.trim(),
      aliases: form.aliases.trim() || null,
      position: Number(form.position) || 0,
      enabled: form.enabled,
      notes: form.notes.trim() || null,
    });
  }

  return (
    <form onSubmit={submit} id="maker-form">
      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}

      <Field
        label="Name"
        hint="What gets written onto a listing, and what the filter shows."
      >
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            value={form.name}
            onChange={set("name")}
            required
            maxLength={128}
          />
        )}
      </Field>

      <Field
        label="Other spellings (optional)"
        hint="One per line — “S&W”, “Smith and Wesson”. Matched as plain text on whole words, not as patterns, so punctuation is taken literally."
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={4}
            value={form.aliases}
            onChange={set("aliases")}
            spellCheck={false}
          />
        )}
      </Field>

      <div className="form-row form-row--2">
        <Field
          label="Order"
          hint="Lower is tried first. A name that contains another maker’s name needs to come before it."
        >
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="number"
              min={0}
              max={100000}
              value={form.position}
              onChange={set("position")}
            />
          )}
        </Field>

        <label className="field">
          <span className="field__label">Status</span>
          <label className="checkbox" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={form.enabled} onChange={set("enabled")} />
            <span>Use this rule</span>
          </label>
        </label>
      </div>

      <Field label="Notes (optional)" hint="For whoever edits this next.">
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={2}
            value={form.notes}
            onChange={set("notes")}
          />
        )}
      </Field>
    </form>
  );
}

export default function ManufacturersPage() {
  useTitle("Makers");
  const [makers, setMakers] = useState(null);
  const [error, setError] = useState(null);
  const [formError, setFormError] = useState(null);
  const [editing, setEditing] = useState(null); // maker object, or "new"
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const load = useCallback(() => {
    api
      .manufacturers()
      .then(setMakers)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  /** Report what an edit did to the catalog, since it is not visible here. */
  function report(action, response) {
    const changed = response?.listings_changed ?? 0;
    setResult(
      changed === 0
        ? `${action}. No listing changed maker.`
        : `${action}. ${countLabel(changed, "listing", "listings")} re-filed.`,
    );
  }

  async function save(payload) {
    setBusy(true);
    setFormError(null);
    try {
      const response =
        editing === "new"
          ? await api.createManufacturer(payload)
          : await api.updateManufacturer(editing.id, payload);
      report(
        editing === "new" ? `Added ${payload.name}` : `Saved ${payload.name}`,
        response,
      );
      setEditing(null);
      load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(maker) {
    setBusy(true);
    try {
      const response = await api.deleteManufacturer(maker.id);
      report(`Deleted ${maker.name}`, response);
      setConfirmDelete(null);
      load();
    } catch (err) {
      setError(err.message);
      setConfirmDelete(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Makers</h1>
          <p>
            The names the scanner looks for when it works out who made a listing. Rules
            are tried in order and the first match wins, so a name that contains another —
            “Mosin-Nagant” and “Nagant” — has to come first. Saving re-files every listing
            the change reaches.
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--secondary" onClick={load}>
            <Refresh size={16} />
            Refresh
          </button>
          <button
            className="btn btn--primary"
            onClick={() => {
              setFormError(null);
              setEditing("new");
            }}
          >
            <Plus size={16} />
            Add maker
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}

      {result && (
        <div className="alert alert--success" role="status">
          {result}
        </div>
      )}

      <div className="panel">
        {!makers && (
          <div className="loading-row" style={{ padding: 20 }}>
            <div className="spinner" />
            Loading makers…
          </div>
        )}

        {makers && makers.length === 0 && (
          <p style={{ padding: 20, margin: 0, color: "var(--ink-400)" }}>
            No makers yet. The built-in list seeds this table the first time the
            application starts against an empty database.
          </p>
        )}

        {makers && makers.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 80 }}>Order</th>
                  <th>Name</th>
                  <th>Other spellings</th>
                  <th>Listings</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {makers.map((maker) => (
                  <tr key={maker.id}>
                    <td style={{ color: "var(--ink-400)" }}>{maker.position}</td>
                    <td>
                      <strong>{maker.name}</strong>
                      {maker.notes && (
                        <div style={{ fontSize: 12, color: "var(--ink-400)" }}>
                          {maker.notes}
                        </div>
                      )}
                    </td>
                    <td style={{ fontSize: 13, color: "var(--ink-400)" }}>
                      {maker.aliases
                        ? maker.aliases
                            .split("\n")
                            .map((line) => line.trim())
                            .filter(Boolean)
                            .join(", ")
                        : "—"}
                    </td>
                    <td>{maker.item_count}</td>
                    <td>
                      <span
                        className={`chip ${maker.enabled ? "chip--success" : "chip--neutral"}`}
                      >
                        {maker.enabled ? "In use" : "Off"}
                      </span>
                    </td>
                    <td className="table__actions">
                      <button
                        className="btn btn--ghost btn--sm"
                        onClick={() => {
                          setFormError(null);
                          setEditing(maker);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="btn btn--ghost btn--sm"
                        style={{ color: "var(--red-600)" }}
                        title="Delete maker"
                        onClick={() => setConfirmDelete(maker)}
                      >
                        <Trash size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && (
        <Modal
          title={editing === "new" ? "Add maker" : `Edit ${editing.name}`}
          onClose={() => setEditing(null)}
          footer={
            <>
              <button className="btn btn--secondary" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button
                className="btn btn--primary"
                type="submit"
                form="maker-form"
                disabled={busy}
              >
                {busy ? "Saving…" : "Save"}
              </button>
            </>
          }
        >
          <MakerForm
            maker={editing === "new" ? null : editing}
            onSubmit={save}
            error={formError}
          />
        </Modal>
      )}

      {confirmDelete && (
        <Modal
          title="Delete maker"
          onClose={() => setConfirmDelete(null)}
          footer={
            <>
              <button
                className="btn btn--secondary"
                onClick={() => setConfirmDelete(null)}
              >
                Cancel
              </button>
              <button
                className="btn btn--danger"
                onClick={() => remove(confirmDelete)}
                disabled={busy}
              >
                Delete and re-file
              </button>
            </>
          }
        >
          <p style={{ margin: 0 }}>
            Delete <strong>{confirmDelete.name}</strong>? The{" "}
            {countLabel(confirmDelete.item_count, "listing", "listings")} filed under it
            will be re-checked against the remaining rules, and any that match nothing
            else will have no maker. Listings themselves are not deleted.
          </p>
        </Modal>
      )}
    </div>
  );
}
