/**
 * Your FFL dealers: who will receive a gun for you, and what each charges.
 *
 * Asked for in place of the one transfer fee, so somebody with a shop down the
 * road, one by work and a kitchen-table FFL can keep all three. Every
 * delivered price -- on a listing, on the wishlist -- is worked out at the
 * cheapest of them, and the table marks which that is.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatMoney } from "../format.js";
import Modal from "../components/Modal.jsx";
import Field from "../components/Field.jsx";
import { External, MapPin, Plus, Trash } from "../components/Icons.jsx";

const BLANK = { name: "", address: "", url: "", transfer_fee: "" };

function Editor({ dealer, onClose, onSaved }) {
  const [form, setForm] = useState(
    dealer
      ? {
          name: dealer.name,
          address: dealer.address || "",
          url: dealer.url || "",
          transfer_fee: String(dealer.transfer_fee),
        }
      : BLANK,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key) => (event) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const save = async (event) => {
    event.preventDefault();
    setError("");
    const fee = Number(form.transfer_fee);
    if (form.transfer_fee.trim() === "" || Number.isNaN(fee) || fee < 0) {
      setError("The transfer fee is a dollar amount: 0 if they charge nothing.");
      return;
    }
    const payload = {
      name: form.name,
      address: form.address,
      url: form.url,
      transfer_fee: fee,
    };
    setBusy(true);
    try {
      const rows = dealer
        ? await api.updateDealer(dealer.id, payload)
        : await api.addDealer(payload);
      onSaved(rows);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  const input = (key, label, props = {}, hint) => (
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
      title={dealer ? `Edit ${dealer.name}` : "Add an FFL dealer"}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn--primary"
            type="submit"
            form="dealer-form"
            disabled={busy || !form.name.trim()}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <form id="dealer-form" onSubmit={save}>
        {error && <p className="alert alert--error">{error}</p>}
        {input("name", "Name", { autoFocus: true, maxLength: 200 })}
        <Field label="Address">
          {(id, describedBy) => (
            <textarea
              id={id}
              aria-describedby={describedBy}
              className="input"
              rows={2}
              maxLength={500}
              value={form.address}
              onChange={set("address")}
            />
          )}
        </Field>
        {input("url", "Website", { maxLength: 500, placeholder: "https://" })}
        {input(
          "transfer_fee",
          "Transfer fee",
          { inputMode: "decimal", placeholder: "$" },
          "What they charge to receive one gun for you. Delivered prices use the lowest fee on your list.",
        )}
      </form>
    </Modal>
  );
}

export default function Dealers() {
  useTitle("FFL dealers");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);
  const [confirming, setConfirming] = useState(null);

  const load = useCallback(() => {
    api
      .dealers()
      .then(setRows)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const remove = async (dealer) => {
    setConfirming(null);
    try {
      setRows(await api.deleteDealer(dealer.id));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>FFL dealers</h1>
          <p>
            The dealers who will receive a gun for you, and what each charges. Every
            delivered price is worked out at the lowest transfer fee here.
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--primary" onClick={() => setEditing("new")}>
            <Plus size={15} /> Add a dealer
          </button>
        </div>
      </div>

      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      {rows === null && !error && <p className="muted">Loading…</p>}

      {rows !== null && rows.length === 0 && (
        <div className="empty">
          <MapPin size={28} />
          <h3>No dealers yet</h3>
          <p>
            Add the dealer you use, and each listing shows what it costs delivered to
            them, transfer included.
          </p>
        </div>
      )}

      {rows !== null && rows.length > 0 && (
        <div className="panel">
          <div className="table-wrap">
            <table className="table" data-testid="dealers-table">
              <thead>
                <tr>
                  <th>Dealer</th>
                  <th>Address</th>
                  <th>Transfer fee</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {rows.map((dealer) => (
                  <tr key={dealer.id}>
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setEditing(dealer)}
                      >
                        {dealer.name}
                      </button>
                      {dealer.url && (
                        <div className="muted collection-sub">
                          <a href={dealer.url} target="_blank" rel="noopener noreferrer">
                            {dealer.url.replace(/^https?:\/\//, "")}{" "}
                            <External size={12} />
                          </a>
                        </div>
                      )}
                    </td>
                    <td className="dealers__address">{dealer.address || "—"}</td>
                    <td>
                      {formatMoney(dealer.transfer_fee)}
                      {dealer.lowest && rows.length > 1 && (
                        <span className="chip chip--success dealers__lowest">Lowest</span>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        aria-label={`Remove ${dealer.name}`}
                        onClick={() => setConfirming(dealer)}
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
      )}

      {editing && (
        <Editor
          dealer={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(next) => {
            setRows(next);
            setEditing(null);
          }}
        />
      )}

      {confirming && (
        <Modal
          title={`Remove ${confirming.name}?`}
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
          <p>It comes off your list, and delivered prices use the lowest fee left.</p>
        </Modal>
      )}
    </section>
  );
}
