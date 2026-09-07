/**
 * The armory: manufacturers, models, calibers, and who made what.
 *
 * Everything else in this application reads a listing and guesses. This page is
 * where somebody who knows the trade states the answers instead, and the
 * guesses defer to them.
 *
 * The organizing idea is the Status filter. A row is either *awaiting approval*
 * — proposed by a scan, or arrived in the shipped armory file — or it is
 * *production*, meaning somebody has looked at it and said yes. Only production
 * rows decide anything: filling in a missing caliber, saying what kind of gun a
 * designation names. Nothing pending can quietly start rewriting the armory,
 * which is what makes it safe for a scan to propose whatever it likes.
 *
 * Two things about the shape are worth knowing at the keyboard:
 *
 * - A model has *several* makers, not one. The M1 Carbine was built by nine
 *   firms and a listing may name any of them, or none. That is why the makers
 *   are checkboxes on one row rather than nine near-identical rows.
 * - A caliber's aliases are the whole point of that table. ".32 ACP" and
 *   "7.65mm Browning" are one cartridge written two ways, and until they are
 *   one row a filter on either shows half the listings.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import Modal from "../components/Modal.jsx";
import Field from "../components/Field.jsx";
import { Plus, Refresh, Trash } from "../components/Icons.jsx";

const TABS = [
  { key: "manufacturers", label: "Manufacturers" },
  { key: "models", label: "Models" },
  { key: "calibers", label: "Calibers" },
];

const STATUSES = [
  { value: "pending", label: "Awaiting approval" },
  { value: "approved", label: "Production" },
  { value: "merged", label: "Merged away" },
  { value: "", label: "Everything" },
];

const EMPTY_MODEL = {
  name: "",
  aliases: "",
  kind: "",
  caliber_ids: [],
  manufacturer_ids: [],
  wikipedia_url: "",
  position: 1000,
  enabled: true,
  notes: "",
};

const EMPTY_CALIBER = { name: "", aliases: "", notes: "" };

//: How many ids one promote or send-back request carries. The endpoint caps a
//: single call, and select-all on a grown armory would sail past it.
const BATCH = 200;

function SelectAllCell({ all, some, onToggle, disabled }) {
  // Indeterminate is a property, not an attribute, so it has to be set on the
  // node itself — React will not render it from JSX.
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (ref.current) ref.current.indeterminate = some && !all;
  }, [all, some]);
  return (
    <th>
      <input
        ref={ref}
        type="checkbox"
        checked={all}
        disabled={disabled}
        onChange={onToggle}
        aria-label={all ? "Clear selection" : "Select everything listed"}
        title={all ? "Clear selection" : "Select everything listed"}
      />
    </th>
  );
}

const SINGULAR = {
  manufacturers: "manufacturer",
  models: "model",
  calibers: "caliber",
};

function countLabel(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function statusChip(status) {
  if (status === "approved")
    return <span className="chip chip--success">Production</span>;
  if (status === "merged") return <span className="chip chip--neutral">Merged</span>;
  return <span className="chip chip--warning">Awaiting approval</span>;
}

function ModelForm({
  model,
  calibers,
  makers,
  kinds,
  onSubmit,
  onAddCaliber,
  startWithMaker,
  error,
}) {
  const editing = Boolean(model);
  const [adding, setAdding] = useState("");
  const [form, setForm] = useState(() =>
    editing
      ? {
          name: model.name,
          aliases: model.aliases || "",
          kind: model.kind || "",
          caliber_ids: model.caliber_ids || [],
          manufacturer_ids: model.manufacturer_ids || [],
          wikipedia_url: model.wikipedia_url || "",
          position: model.position,
          enabled: model.enabled,
          notes: model.notes || "",
        }
      : { ...EMPTY_MODEL, manufacturer_ids: startWithMaker ? [startWithMaker] : [] },
  );

  const set = (key) => (event) => {
    const target = event.target;
    setForm((prev) => ({
      ...prev,
      [key]: target.type === "checkbox" ? target.checked : target.value,
    }));
  };

  // Both lists toggle the same way, so they share one function.
  const toggle = (key) => (id) =>
    setForm((prev) => ({
      ...prev,
      [key]: prev[key].includes(id)
        ? prev[key].filter((value) => value !== id)
        : [...prev[key], id],
    }));
  const toggleMaker = toggle("manufacturer_ids");
  const toggleCaliber = toggle("caliber_ids");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          ...form,
          kind: form.kind || null,
          position: Number(form.position),
          wikipedia_url: form.wikipedia_url.trim() || null,
        });
      }}
    >
      <Field
        label="Name"
        hint="As the trade names it: “M1 Carbine”, “Model 1873 Trapdoor Carbine”."
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
        label="Also written as"
        hint="One per line. Matched as literal text on word boundaries, never as a pattern."
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={4}
            value={form.aliases}
            onChange={set("aliases")}
          />
        )}
      </Field>

      <div className="form-row form-row--2">
        <Field
          label="Kind"
          hint="A carbine is not a short rifle — a Trapdoor Carbine and a Trapdoor Rifle are different guns."
        >
          {(id, describedBy) => (
            <select
              id={id}
              aria-describedby={describedBy}
              className="input"
              value={form.kind}
              onChange={set("kind")}
            >
              <option value="">Not decided yet</option>
              {kinds.map((kind) => (
                <option key={kind.value} value={kind.value}>
                  {kind.label} — {kind.is_handgun ? "Handguns" : "Rifles"}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>

      <Field
        label="Chambered in"
        hint="More than one is normal — a Steyr M95 is 8x50mmR or 8x56mmR. With exactly one, a listing that states no caliber is filled in from it; with several it is left alone, because the model does not say which this one is."
      >
        {(id, describedBy) => (
          <div id={id} aria-describedby={describedBy}>
            <div className="armory-checkboxes">
              {calibers.map((caliber) => (
                <label key={caliber.id} className="checkbox">
                  <input
                    type="checkbox"
                    checked={form.caliber_ids.includes(caliber.id)}
                    onChange={() => toggleCaliber(caliber.id)}
                  />
                  <span>
                    {caliber.name}
                    {caliber.status !== "approved" ? " (awaiting approval)" : ""}
                  </span>
                </label>
              ))}
            </div>
            <div className="armory-inline-add">
              <input
                className="input"
                value={adding}
                placeholder="A cartridge not listed above"
                onChange={(event) => setAdding(event.target.value)}
              />
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                disabled={!adding.trim()}
                onClick={async () => {
                  const created = await onAddCaliber(adding.trim());
                  if (created) {
                    setForm((prev) => ({
                      ...prev,
                      caliber_ids: [...prev.caliber_ids, created.id],
                    }));
                    setAdding("");
                  }
                }}
              >
                <Plus /> Add caliber
              </button>
            </div>
          </div>
        )}
      </Field>

      <Field
        label="Made by"
        hint="Several is normal. The M1 Carbine had nine makers, and a listing may name any of them or none."
      >
        {(id, describedBy) => (
          <div id={id} aria-describedby={describedBy} className="armory-checkboxes">
            {makers.map((maker) => (
              <label key={maker.id} className="checkbox">
                <input
                  type="checkbox"
                  checked={form.manufacturer_ids.includes(maker.id)}
                  onChange={() => toggleMaker(maker.id)}
                />
                <span>{maker.name}</span>
              </label>
            ))}
          </div>
        )}
      </Field>

      <Field
        label="Reference link"
        hint="Wikipedia, or a collector's reference — whichever is better on this one."
      >
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            type="url"
            value={form.wikipedia_url}
            onChange={set("wikipedia_url")}
            maxLength={500}
            placeholder="https://en.wikipedia.org/wiki/…"
          />
        )}
      </Field>

      <div className="form-row form-row--2">
        <Field
          label="Order"
          hint="Lower is tried first. “Mosin-Nagant M44” before “M44”."
        >
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="number"
              value={form.position}
              onChange={set("position")}
              min={0}
            />
          )}
        </Field>
        <Field label="Enabled" hint="Off takes it out of matching without deleting it.">
          {(id, describedBy) => (
            <label className="checkbox">
              <input
                id={id}
                aria-describedby={describedBy}
                type="checkbox"
                checked={form.enabled}
                onChange={set("enabled")}
              />
              <span>In use</span>
            </label>
          )}
        </Field>
      </div>

      <Field label="Notes">
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

      {error && <p className="alert alert--error">{error}</p>}
      <div className="page-head__actions">
        <button type="submit" className="btn btn--primary">
          {editing ? "Save" : "Add, awaiting approval"}
        </button>
      </div>
    </form>
  );
}

function CaliberForm({ caliber, onSubmit, error }) {
  const editing = Boolean(caliber);
  const [form, setForm] = useState(() =>
    editing
      ? { name: caliber.name, aliases: caliber.aliases || "", notes: caliber.notes || "" }
      : EMPTY_CALIBER,
  );
  const set = (key) => (event) =>
    setForm((prev) => ({ ...prev, [key]: event.target.value }));

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(form);
      }}
    >
      <Field label="Name" hint="The spelling this application will use everywhere.">
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
        label="Also written as"
        hint="One per line. “7.65mm Browning” and “.32 ACP” are one cartridge; this is where that is said."
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={5}
            value={form.aliases}
            onChange={set("aliases")}
          />
        )}
      </Field>
      <Field label="Notes">
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
      {error && <p className="alert alert--error">{error}</p>}
      <div className="page-head__actions">
        <button type="submit" className="btn btn--primary">
          {editing ? "Save" : "Add, awaiting approval"}
        </button>
      </div>
    </form>
  );
}

const EMPTY_MAKER = { name: "", aliases: "", position: 1000, enabled: true, notes: "" };

function MakerForm({ maker, onSubmit, error }) {
  const editing = Boolean(maker);
  const [form, setForm] = useState(() =>
    editing
      ? {
          name: maker.name,
          aliases: maker.aliases || "",
          position: maker.position,
          enabled: maker.enabled,
          notes: maker.notes || "",
        }
      : EMPTY_MAKER,
  );
  const set = (key) => (event) => {
    const target = event.target;
    setForm((prev) => ({
      ...prev,
      [key]: target.type === "checkbox" ? target.checked : target.value,
    }));
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ ...form, position: Number(form.position) });
      }}
    >
      <Field
        label="Name"
        hint="The canonical spelling, written onto every listing it matches."
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
        label="Also written as"
        hint={
          "One per line — “S&W” for Smith & Wesson. Matched as literal text, never as a " +
          "pattern. The models this firm built are not listed here: they are rows under " +
          "Models, each carrying all of its makers."
        }
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={4}
            value={form.aliases}
            onChange={set("aliases")}
          />
        )}
      </Field>
      <div className="form-row form-row--2">
        <Field label="Order" hint="Lower is tried first. “Mosin-Nagant” before “Nagant”.">
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="number"
              value={form.position}
              onChange={set("position")}
              min={0}
            />
          )}
        </Field>
        <Field label="Enabled" hint="Off takes it out of matching without deleting it.">
          {(id, describedBy) => (
            <label className="checkbox">
              <input
                id={id}
                aria-describedby={describedBy}
                type="checkbox"
                checked={form.enabled}
                onChange={set("enabled")}
              />
              <span>In use</span>
            </label>
          )}
        </Field>
      </div>
      <Field label="Notes">
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
      {error && <p className="alert alert--error">{error}</p>}
      <div className="page-head__actions">
        <button type="submit" className="btn btn--primary">
          {editing ? "Save" : "Add manufacturer"}
        </button>
      </div>
    </form>
  );
}

function MergeForm({ row, rows, onSubmit, error }) {
  const [targetId, setTargetId] = useState("");
  const others = rows.filter((other) => other.id !== row.id && other.status !== "merged");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(Number(targetId));
      }}
    >
      <p className="alert alert--info">
        <strong>{row.name}</strong> is folded into whichever row you pick. Its spellings
        move across, so nothing it used to recognize stops being recognized, and every
        listing carrying its name is restamped. It stays in the list, marked, pointing at
        the row it went into.
      </p>
      <Field label="Merge into">
        {(id, describedBy) => (
          <select
            id={id}
            aria-describedby={describedBy}
            className="input"
            value={targetId}
            onChange={(event) => setTargetId(event.target.value)}
            required
          >
            <option value="">Choose a row…</option>
            {others.map((other) => (
              <option key={other.id} value={other.id}>
                {other.name}
              </option>
            ))}
          </select>
        )}
      </Field>
      {error && <p className="alert alert--error">{error}</p>}
      <div className="page-head__actions">
        <button type="submit" className="btn btn--danger" disabled={!targetId}>
          Merge
        </button>
      </div>
    </form>
  );
}

export default function Armory() {
  useTitle("Armory");
  const [tab, setTab] = useState("models");
  const [statusFilter, setStatusFilter] = useState("pending");
  const [search, setSearch] = useState("");

  const [models, setModels] = useState([]);
  // Every model regardless of the status filter, so the drill-down under a
  // maker shows what it built rather than what the filter happens to admit.
  const [allModels, setAllModels] = useState([]);
  const [calibers, setCalibers] = useState([]);
  const [allCalibers, setAllCalibers] = useState([]);
  const [makers, setMakers] = useState([]);
  // Which makers are expanded to show their models. A model with several
  // makers appears under each of them and is the SAME row: opening it from
  // any one of them edits the single record.
  const [opened, setOpened] = useState(() => new Set());
  const [kinds, setKinds] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);

  const [selected, setSelected] = useState(() => new Set());
  const [editing, setEditing] = useState(null);
  const [merging, setMerging] = useState(null);
  const [formError, setFormError] = useState("");
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  const rows = tab === "models" ? models : tab === "calibers" ? calibers : makers;

  const load = useCallback(async () => {
    const filters = {};
    if (statusFilter) filters.status = statusFilter;
    if (search.trim()) filters.search = search.trim();
    const [
      modelRows,
      caliberRows,
      everyCaliber,
      everyModel,
      makerRows,
      kindRows,
      counts,
    ] = await Promise.all([
      api.armoryModels(filters),
      api.armoryCalibers(filters),
      api.armoryCalibers(),
      api.armoryModels(),
      api.manufacturers(),
      api.armoryKinds(),
      api.armorySummary(),
    ]);
    setAllModels(everyModel);
    setModels(modelRows);
    setCalibers(caliberRows);
    setAllCalibers(everyCaliber);
    setMakers(makerRows);
    setKinds(kindRows);
    setSummary(counts);
    setSelected(new Set());
  }, [statusFilter, search]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load()
      .catch((error) => !cancelled && setFailure(error.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [load]);

  const act = async (run) => {
    setBusy(true);
    setFailure("");
    try {
      const result = await run();
      if (result?.message) setMessage(result.message);
      await load();
    } catch (error) {
      setFailure(error.message);
    } finally {
      setBusy(false);
    }
  };

  const ids = useMemo(() => [...selected], [selected]);
  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Every row currently listed — which is every row the Showing filter and the
  // search admit, not every row in the table. On the default view that is the
  // whole pending queue, which is the point: approve the lot in two clicks.
  const allShown = rows.length > 0 && rows.every((row) => selected.has(row.id));
  const someShown = rows.some((row) => selected.has(row.id));
  const toggleAll = () =>
    setSelected(allShown ? new Set() : new Set(rows.map((row) => row.id)));

  /** Send the ids in batches, because the endpoint bounds a single request.
   *
   * Select-all on a grown armory is exactly the case that outruns it, and a
   * button that works until the list gets long is worse than one that never
   * worked. The counts come back per batch and are added up. */
  const inBatches = async (send) => {
    let changed = 0;
    let last = "";
    for (let at = 0; at < ids.length; at += BATCH) {
      const result = await send(ids.slice(at, at + BATCH));
      changed += result?.changed ?? 0;
      last = result?.message || last;
    }
    return {
      message:
        ids.length > BATCH
          ? `${changed} row(s) moved, in ${Math.ceil(ids.length / BATCH)} batches.`
          : last,
    };
  };

  const save = async (payload) => {
    setFormError("");
    try {
      if (tab === "manufacturers") {
        // The makers keep their own endpoint: an edit there re-derives the
        // listings it can reach and reports how many, which is a different
        // shape of answer from the armory's own writes.
        if (editing?.id) await api.updateManufacturer(editing.id, payload);
        else await api.createManufacturer(payload);
      } else if (editing?.id) {
        await api.updateArmoryRow(tab, editing.id, payload);
      } else {
        await api.createArmoryRow(tab, payload);
      }
      setEditing(null);
      await load();
    } catch (error) {
      setFormError(error.message);
    }
  };

  /** Create a caliber from inside the model dialog and hand it back.
   *
   * The alternative is closing the dialog, switching tabs, adding the
   * cartridge, coming back and starting the model again -- which is how a
   * model ends up with no caliber on it.
   */
  const addCaliber = async (name) => {
    try {
      const created = await api.createArmoryRow("calibers", { name });
      setAllCalibers((prev) =>
        [...prev, created].sort((a, b) => a.name.localeCompare(b.name)),
      );
      return created;
    } catch (failure) {
      setFormError(failure.message);
      return null;
    }
  };

  /** Open the model dialog with this maker already checked. */
  const addModelFor = (maker) => {
    setFormError("");
    setTab("models");
    setEditing({ _makerId: maker.id });
  };

  const modelsFor = (maker) =>
    allModels.filter((model) => model.manufacturer_ids.includes(maker.id));

  const pending = summary ? summary.models + summary.calibers + summary.manufacturers : 0;

  return (
    <section className="panel">
      <div className="page-head">
        <div>
          <h1>Armory</h1>
          <p>
            What models exist, what they chamber and who built them. Only rows in{" "}
            <strong>production</strong> fill in a listing’s missing caliber or decide what
            kind of gun it is — anything awaiting approval sits here and does nothing
            until you promote it.
          </p>
        </div>
        <div className="page-head__actions">
          <button
            type="button"
            className="btn btn--secondary"
            disabled={busy}
            onClick={() => act(() => api.seedArmory())}
          >
            <Refresh /> Load shipped armory
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => {
              setFormError("");
              setEditing({});
            }}
          >
            <Plus /> Add {SINGULAR[tab]}
          </button>
        </div>
      </div>

      {pending > 0 && (
        <p className="alert alert--info">
          {countLabel(pending, "row is", "rows are")} awaiting approval — {summary.models}{" "}
          model, {summary.calibers} caliber and {summary.manufacturers} maker. Until they
          are promoted they decide nothing.
        </p>
      )}
      {message && <p className="alert alert--success">{message}</p>}
      {failure && <p className="alert alert--error">{failure}</p>}

      <div className="form-row form-row--2">
        <Field label="Showing">
          {(id, describedBy) => (
            <select
              id={id}
              aria-describedby={describedBy}
              className="input"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              {STATUSES.map((entry) => (
                <option key={entry.value || "all"} value={entry.value}>
                  {entry.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Search" hint="Matches names and every spelling on them.">
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          )}
        </Field>
      </div>

      <div className="armory-tabs" role="tablist">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            className={`btn ${tab === entry.key ? "btn--primary" : "btn--ghost"} btn--sm`}
            onClick={() => {
              setTab(entry.key);
              setSelected(new Set());
            }}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {ids.length > 0 && (
        <div className="alert alert--info armory-bulk">
          <span>
            {countLabel(ids.length, "row", "rows")} selected
            {allShown && rows.length > 1 ? " — everything listed" : ""}
          </span>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            disabled={busy}
            onClick={() =>
              act(() => inBatches((some) => api.promoteArmoryRows(tab, some)))
            }
          >
            Promote to production
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            disabled={busy}
            onClick={() =>
              act(() => inBatches((some) => api.sendArmoryRowsBack(tab, some)))
            }
          >
            Send back for approval
          </button>
        </div>
      )}

      {tab === "manufacturers" ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <SelectAllCell
                  all={allShown}
                  some={someShown}
                  disabled={rows.length === 0}
                  onToggle={toggleAll}
                />
                <th aria-label="Expand" />
                <th>Name</th>
                <th>Models</th>
                <th>Listings</th>
                <th>Status</th>
                <th>Also written as</th>
                <th>Order</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={9} className="loading-row">
                    <span className="spinner" /> Loading…
                  </td>
                </tr>
              )}
              {!loading &&
                makers.map((maker) => {
                  const built = modelsFor(maker);
                  const open = opened.has(maker.id);
                  return (
                    <React.Fragment key={maker.id}>
                      <tr>
                        <td>
                          <input
                            type="checkbox"
                            checked={selected.has(maker.id)}
                            onChange={() => toggle(maker.id)}
                            aria-label={`Select ${maker.name}`}
                          />
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            aria-expanded={open}
                            aria-label={`${open ? "Collapse" : "Expand"} ${maker.name}`}
                            onClick={() =>
                              setOpened((prev) => {
                                const next = new Set(prev);
                                if (next.has(maker.id)) next.delete(maker.id);
                                else next.add(maker.id);
                                return next;
                              })
                            }
                          >
                            {open ? "▾" : "▸"}
                          </button>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            onClick={() => {
                              setFormError("");
                              setEditing(maker);
                            }}
                          >
                            {maker.name}
                          </button>
                          {!maker.enabled && (
                            <span className="chip chip--neutral">disabled</span>
                          )}
                        </td>
                        <td>{built.length}</td>
                        <td>{maker.item_count}</td>
                        <td>{statusChip(maker.status)}</td>
                        <td>
                          {(maker.aliases || "")
                            .split("\n")
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </td>
                        <td>{maker.position}</td>
                        <td className="table__actions">
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            onClick={() => {
                              setFormError("");
                              setMerging(maker);
                            }}
                          >
                            Merge…
                          </button>
                        </td>
                      </tr>
                      {open && (
                        <tr>
                          <td />
                          <td />
                          <td colSpan={7}>
                            <div className="armory-drilldown">
                              {built.length === 0 && (
                                <p className="armory-drilldown__empty">
                                  No models recorded for {maker.name} yet.
                                </p>
                              )}
                              {built.map((model) => (
                                <div key={model.id} className="armory-drilldown__row">
                                  <button
                                    type="button"
                                    className="btn btn--ghost btn--sm"
                                    onClick={() => {
                                      setFormError("");
                                      setTab("models");
                                      setEditing(model);
                                    }}
                                  >
                                    {model.name}
                                  </button>
                                  <span>
                                    {kinds.find((k) => k.value === model.kind)?.label ||
                                      "—"}
                                  </span>
                                  <span>{model.calibers.join(", ") || "—"}</span>
                                  {statusChip(model.status)}
                                  {model.manufacturers.length > 1 && (
                                    <span
                                      className="chip chip--neutral"
                                      title={model.manufacturers.join(", ")}
                                    >
                                      also {model.manufacturers.length - 1} other maker
                                      {model.manufacturers.length > 2 ? "s" : ""}
                                    </span>
                                  )}
                                </div>
                              ))}
                              <button
                                type="button"
                                className="btn btn--secondary btn--sm"
                                onClick={() => addModelFor(maker)}
                              >
                                <Plus /> Add model
                              </button>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              {!loading && makers.length === 0 && (
                <tr>
                  <td colSpan={9} className="loading-row">
                    No manufacturers yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <SelectAllCell
                  all={allShown}
                  some={someShown}
                  disabled={rows.length === 0}
                  onToggle={toggleAll}
                />
                <th>Name</th>
                <th>{tab === "models" ? "Kind" : "Listings"}</th>
                <th>{tab === "models" ? "Chambered in" : "Models"}</th>
                {tab === "models" && <th>Made by</th>}
                <th>Also written as</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={8} className="loading-row">
                    <span className="spinner" /> Loading…
                  </td>
                </tr>
              )}
              {!loading &&
                rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.has(row.id)}
                        onChange={() => toggle(row.id)}
                        aria-label={`Select ${row.name}`}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => {
                          setFormError("");
                          setEditing(row);
                        }}
                      >
                        {row.name}
                      </button>
                      {row.wikipedia_url && (
                        <a
                          href={row.wikipedia_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="armory-ref"
                        >
                          reference
                        </a>
                      )}
                      {row.merged_into && (
                        <span className="chip chip--neutral">→ {row.merged_into}</span>
                      )}
                    </td>
                    <td>
                      {tab === "models"
                        ? kinds.find((kind) => kind.value === row.kind)?.label || "—"
                        : row.item_count}
                    </td>
                    <td>
                      {tab === "models"
                        ? row.calibers.length
                          ? row.calibers.join(", ")
                          : "—"
                        : row.model_count}
                    </td>
                    {tab === "models" && (
                      <td>
                        {row.manufacturers.length ? row.manufacturers.join(", ") : "—"}
                      </td>
                    )}
                    <td title={row.first_seen_in || undefined}>
                      {(row.aliases || "").split("\n").filter(Boolean).join(" · ") || "—"}
                    </td>
                    <td>{statusChip(row.status)}</td>
                    <td className="table__actions">
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => {
                          setFormError("");
                          setMerging(row);
                        }}
                      >
                        Merge…
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        aria-label={`Delete ${row.name}`}
                        onClick={() =>
                          act(async () => {
                            await api.deleteArmoryRow(tab, row.id);
                            return { message: `Deleted ${row.name}.` };
                          })
                        }
                      >
                        <Trash />
                      </button>
                    </td>
                  </tr>
                ))}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="loading-row">
                    Nothing here. “Load shipped armory” brings in the starting list, and
                    scans add what they meet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <Modal
          title={editing.id ? `Edit ${editing.name}` : `Add a ${SINGULAR[tab]}`}
          onClose={() => {
            setEditing(null);
            setFormError("");
          }}
        >
          {tab === "models" && (
            <ModelForm
              model={editing.id ? editing : null}
              // Arriving from "+ Add model" under a maker, that maker is
              // already checked. A starting point, not a constraint: the
              // other eight can be checked here too.
              startWithMaker={editing._makerId}
              calibers={allCalibers}
              makers={makers}
              kinds={kinds}
              onSubmit={save}
              onAddCaliber={addCaliber}
              error={formError}
            />
          )}
          {tab === "calibers" && (
            <CaliberForm
              caliber={editing.id ? editing : null}
              onSubmit={save}
              error={formError}
            />
          )}
          {tab === "manufacturers" && (
            <MakerForm
              maker={editing.id ? editing : null}
              onSubmit={save}
              error={formError}
            />
          )}
        </Modal>
      )}

      {merging && (
        <Modal
          title={`Merge ${merging.name}`}
          onClose={() => {
            setMerging(null);
            setFormError("");
          }}
        >
          <MergeForm
            row={merging}
            rows={rows}
            error={formError}
            onSubmit={async (targetId) => {
              setFormError("");
              try {
                const result = await api.mergeArmoryRows(tab, merging.id, targetId);
                setMerging(null);
                setMessage(result.message);
                await load();
              } catch (error) {
                setFormError(error.message);
              }
            }}
          />
        </Modal>
      )}
    </section>
  );
}
