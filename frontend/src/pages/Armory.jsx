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
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  country: "",
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

//: Names here are mostly numbers, and a plain string sort reads them wrong:
//: ".30-06" lands after ".303", "M1903" after "M191", and "Model 9" after
//: "Model 1873". Numeric collation compares each run of digits as a number,
//: which is the order somebody looking for a cartridge expects. Base
//: sensitivity so case and accents do not split "Schmidt-Rubin" from
//: "Schmidt–Rubin".
const COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

//: A caliber's leading number is not one kind of measurement, which is why
//: the general collator gets this list wrong. It reads the digits as ordinals,
//: so ".303 British" lands after ".45 ACP" -- 303 against 45 -- when as bore
//: diameters they are 0.303" and 0.45" and the .303 belongs between .30-06 and
//: .308. Three shapes, and the catalog holds nothing else:
//:
//:   .303 British        a fraction of an inch -- 0.303
//:   7.62x54R            millimetres -- 7.62
//:   12 gauge            a bore gauge, where a bigger number is a smaller bore
//:
//: Grouped by shape and then numeric within the group, rather than converted
//: to a common unit. Both are defensible; this one is legible. Interleaving
//: ".30-06 Springfield" with "7.62x54R" because they are the same bore is
//: true, and nobody scanning for a cartridge reads a list that way.
const INCH_BORE = /^\.(\d+)/;
const GAUGE = /^(\d+)\s*(?:gauge|ga\b)/i;
const MILLIMETRES = /^(\d+(?:\.\d+)?)/;

/** Which block a caliber belongs in, and where in it. */
function caliberRank(name) {
  const text = (name || "").trim();
  const gauge = GAUGE.exec(text);
  // Before the millimetre rule, which would otherwise read "12 gauge" as 12mm.
  if (gauge) return [2, Number(gauge[1])];
  const inch = INCH_BORE.exec(text);
  // The digits after the dot are the fraction, so ".45-70" is 0.45 and the 70
  // is grains of powder -- not part of the bore at all.
  if (inch) return [0, Number(`0.${inch[1]}`)];
  const millimetres = MILLIMETRES.exec(text);
  if (millimetres) return [1, Number(millimetres[1])];
  return [3, 0];
}

function compareCalibers(left, right) {
  const [leftGroup, leftBore] = caliberRank(left);
  const [rightGroup, rightBore] = caliberRank(right);
  // Same bore is the common case -- .38 Special, .38 Super and .380 ACP are
  // all 0.38 -- so the name settles it.
  return leftGroup - rightGroup || leftBore - rightBore || COLLATOR.compare(left, right);
}

/** How to order names on this tab. Only the calibers need the bore rules. */
const nameOrder = (tab) => (tab === "calibers" ? compareCalibers : COLLATOR.compare);

//: Sorting starts on the name, ascending, for every tab -- which is what makes
//: the Manufacturers tab alphabetical. Its rows arrive from the API ordered by
//: `position` instead, because that is the order the matching rules are tried
//: in and the API is right to report it that way; it is simply not the order
//: to read fifty firms in.
const DEFAULT_SORT = { key: "name", direction: "asc" };

/** A column header that sorts. Clicking the active one reverses it. */
function SortHeader({ label, sortKey, sort, onSort, className }) {
  const active = sort.key === sortKey;
  return (
    <th
      className={className}
      aria-sort={
        active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"
      }
    >
      <button
        type="button"
        className={`table__sort${active ? " table__sort--active" : ""}`}
        // A title rather than an aria-label. The visible text is already the
        // accessible name (the arrow beside it is aria-hidden), and aria-sort
        // on the cell carries the state -- so a label here would only restate
        // them. It would also collide: an aria-label of "Sort by Name" makes
        // this button answer to getByLabel("Name"), which is how the form
        // fields are addressed, and every "Name"/"Kind"/"Models" lookup in the
        // suite started matching two elements.
        title={`Sort by ${label}`}
        onClick={() => onSort(sortKey)}
      >
        {label}
        <span className="table__sort-mark" aria-hidden="true">
          {active ? (sort.direction === "asc" ? "▲" : "▼") : "▾"}
        </span>
      </button>
    </th>
  );
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
  countries,
  onSubmit,
  onAddCaliber,
  startWithMaker,
  error,
}) {
  const editing = Boolean(model);
  //: Both lists alphabetical. The calibers arrive that way from the API and
  //: the makers do not -- they come ordered by `position`, which is the order
  //: their matching rules are tried in and no help at all when you are looking
  //: for Husqvarna among fifty firms.
  const sortedCalibers = useMemo(
    () => [...calibers].sort((left, right) => compareCalibers(left.name, right.name)),
    [calibers],
  );
  const sortedMakers = useMemo(
    () => [...makers].sort((left, right) => COLLATOR.compare(left.name, right.name)),
    [makers],
  );
  const [adding, setAdding] = useState("");
  const [form, setForm] = useState(() =>
    editing
      ? {
          name: model.name,
          aliases: model.aliases || "",
          kind: model.kind || "",
          country: model.country || "",
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
          country: form.country.trim() || null,
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
              {sortedCalibers.map((caliber) => (
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
            {sortedMakers.map((maker) => (
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
        label="Country of origin"
        hint="Where the pattern comes from, not where this one was built. A Mosin-Nagant is Russian whoever assembled it. Fills in listings whose title names no country."
      >
        {(id, describedBy) => (
          <>
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              list="armory-countries"
              value={form.country}
              onChange={set("country")}
              maxLength={64}
              placeholder="Russia"
            />
            <datalist id="armory-countries">
              {countries.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </>
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

function MergeForm({ row, rows, compare, onSubmit, error }) {
  const [targetId, setTargetId] = useState("");
  //: Alphabetical, whatever the table behind it is sorted by. A merge is a
  //: lookup -- you know the name you are folding this into -- and hunting for
  //: it down a list ordered by listing count is not that.
  const others = useMemo(
    () =>
      rows
        .filter((other) => other.id !== row.id && other.status !== "merged")
        .sort((left, right) => compare(left.name, right.name)),
    [rows, row.id, compare],
  );
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
  const [allMakers, setAllMakers] = useState([]);
  const [sort, setSort] = useState(DEFAULT_SORT);
  const [kinds, setKinds] = useState([]);
  //: Suggestions for the model form's country box, from the same list the
  //: classifier reads titles with -- so a model and a title that mean the same
  //: country write it the same way.
  const [countries, setCountries] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);

  const [selected, setSelected] = useState(() => new Set());
  const [editing, setEditing] = useState(null);
  const [merging, setMerging] = useState(null);
  const [formError, setFormError] = useState("");
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);

  //: Declared above the sort, which reads it: a useMemo callback runs during
  //: render, so a const defined further down is still in its dead zone.
  const modelsFor = (maker) =>
    allModels.filter((model) => model.manufacturer_ids.includes(maker.id));

  const unsorted = tab === "models" ? models : tab === "calibers" ? calibers : makers;
  //: The same three regardless of the status filter, for the places that must
  //: offer every row: the merge target list, and the model form's checkboxes.
  const allRows =
    tab === "models" ? allModels : tab === "calibers" ? allCalibers : allMakers;

  //: What each sortable column reads off a row. Defined here rather than at
  //: module scope because the makers' model count is derived from the models
  //: list, and sorting by a number other than the one on screen would be a
  //: quiet lie.
  const sortValues = {
    name: (row) => row.name || "",
    status: (row) => row.status || "",
    position: (row) => row.position ?? 0,
    listings: (row) => row.item_count ?? 0,
    models: (row) =>
      tab === "manufacturers" ? modelsFor(row).length : (row.model_count ?? 0),
    kind: (row) => kinds.find((kind) => kind.value === row.kind)?.label || "",
    country: (row) => row.country || "",
    calibers: (row) => (row.calibers || []).join(", "),
    makers: (row) => (row.manufacturers || []).join(", "),
    aliases: (row) => (row.aliases || "").split("\n").filter(Boolean).join(" · "),
  };

  /** Click a column to sort by it; click the one already sorted to reverse. */
  const sortBy = (key) =>
    setSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" },
    );

  const rows = useMemo(() => {
    const read = sortValues[sort.key] || sortValues.name;
    const byName = nameOrder(tab);
    return [...unsorted].sort((left, right) => {
      const a = read(left);
      const b = read(right);
      const first =
        typeof a === "number"
          ? a - b
          : sort.key === "name"
            ? byName(a, b)
            : COLLATOR.compare(a, b);
      // Ties fall back to the name, so equal counts and shared statuses still
      // come out alphabetically rather than in whatever order they arrived.
      return (sort.direction === "asc" ? first : -first) || byName(left.name, right.name);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unsorted, sort, tab, allModels, kinds]);

  /**
   * The newest `load()` wins, whatever order the responses come back in.
   *
   * `load()` fires nine requests and applies all nine results, and nothing was
   * stopping a *stale* one from landing last. That cost a real failure: adding
   * a caliber from inside the model dialog puts the new row straight into
   * `allCalibers` without a round trip — and a `load()` already in flight,
   * whose caliber list was fetched before the POST, then overwrote it and the
   * cartridge vanished from the list it had just been added to.
   *
   * A counter rather than the effect's `cancelled` flag: that only guards the
   * two setters in the effect itself, not the eight inside `load()`, and
   * `load()` is also called directly after every write.
   */
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const ticket = ++loadSeq.current;
    const filters = {};
    if (statusFilter) filters.status = statusFilter;
    if (search.trim()) filters.search = search.trim();
    const [
      modelRows,
      caliberRows,
      everyCaliber,
      everyModel,
      makerRows,
      everyMaker,
      kindRows,
      countryNames,
      counts,
    ] = await Promise.all([
      api.armoryModels(filters),
      api.armoryCalibers(filters),
      api.armoryCalibers(),
      api.armoryModels(),
      // Filtered like the other two tabs. Called with no filters, the makers
      // tab showed every row whatever the page was set to -- so the default
      // "Awaiting approval" view listed all fifty-one of them.
      api.manufacturers(filters),
      // And unfiltered, for the model form's "Made by" list: a model's makers
      // have nothing to do with which of them the page is currently listing.
      api.manufacturers(),
      api.armoryKinds(),
      api.armoryCountries(),
      api.armorySummary(),
    ]);
    // Anything newer has already been asked for; this answer is out of date.
    if (ticket !== loadSeq.current) return;
    setAllModels(everyModel);
    setModels(modelRows);
    setCalibers(caliberRows);
    setAllCalibers(everyCaliber);
    setMakers(makerRows);
    setAllMakers(everyMaker);
    setKinds(kindRows);
    setCountries(countryNames);
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
      // Any `load()` still in flight fetched its caliber list *before* this
      // row existed, so its answer is already out of date: retiring the
      // ticket makes it land on the floor instead of on top of this.
      //
      // Without that, the cartridge you just added disappeared from the list
      // you added it to. The page navigation fires a nine-request load and
      // only waits for the heading, so on a slow machine the dialog is open
      // and the POST is done while that load is still outstanding — which is
      // how this reached CI as a test that failed on one runner in four.
      loadSeq.current += 1;
      setAllCalibers((prev) =>
        [...prev, created].sort((a, b) => compareCalibers(a.name, b.name)),
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
              // Back to the name. The tabs do not share their columns, so a
              // sort on "Chambered in" means nothing on the makers tab.
              setSort(DEFAULT_SORT);
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
                <SortHeader label="Name" sortKey="name" sort={sort} onSort={sortBy} />
                <SortHeader label="Models" sortKey="models" sort={sort} onSort={sortBy} />
                <SortHeader
                  label="Listings"
                  sortKey="listings"
                  sort={sort}
                  onSort={sortBy}
                />
                <SortHeader label="Status" sortKey="status" sort={sort} onSort={sortBy} />
                <SortHeader
                  label="Also written as"
                  sortKey="aliases"
                  sort={sort}
                  onSort={sortBy}
                />
                <SortHeader
                  label="Order"
                  sortKey="position"
                  sort={sort}
                  onSort={sortBy}
                />
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
                // `rows`, not `makers`: the sorted view of them. Mapping the
                // raw state here is what made the sort silently do nothing on
                // this tab -- the header arrows moved and the list stayed in
                // the API's `position` order.
                rows.map((maker) => {
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
                                  <span>{model.country || "—"}</span>
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
              {!loading && rows.length === 0 && (
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
                <SortHeader label="Name" sortKey="name" sort={sort} onSort={sortBy} />
                <SortHeader
                  label={tab === "models" ? "Kind" : "Listings"}
                  sortKey={tab === "models" ? "kind" : "listings"}
                  sort={sort}
                  onSort={sortBy}
                />
                <SortHeader
                  label={tab === "models" ? "Chambered in" : "Models"}
                  sortKey={tab === "models" ? "calibers" : "models"}
                  sort={sort}
                  onSort={sortBy}
                />
                {tab === "models" && (
                  <SortHeader
                    label="From"
                    sortKey="country"
                    sort={sort}
                    onSort={sortBy}
                  />
                )}
                {tab === "models" && (
                  <SortHeader
                    label="Made by"
                    sortKey="makers"
                    sort={sort}
                    onSort={sortBy}
                  />
                )}
                <SortHeader
                  label="Also written as"
                  sortKey="aliases"
                  sort={sort}
                  onSort={sortBy}
                />
                <SortHeader label="Status" sortKey="status" sort={sort} onSort={sortBy} />
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={tab === "models" ? 9 : 7} className="loading-row">
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
                    {tab === "models" && <td>{row.country || "—"}</td>}
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
                  <td colSpan={tab === "models" ? 9 : 7} className="loading-row">
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
              makers={allMakers}
              kinds={kinds}
              countries={countries}
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
            // Every row of this kind, not the ones the status filter admits.
            // The target of a merge is usually in production and the row being
            // merged usually is not -- folding a freshly discovered "Mosin"
            // into the approved "Mosin-Nagant" is the case this exists for,
            // and passing the filtered list made exactly that impossible.
            rows={allRows}
            // A caliber list is ordered by bore, not by the digits in its
            // name. The dialog does not know which tab opened it.
            compare={nameOrder(tab)}
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
