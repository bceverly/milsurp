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
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import Modal from "../components/Modal.jsx";
import SortHeader from "../components/SortHeader.jsx";
import { COLLATOR, compareCalibers } from "../sorting.js";
import Field from "../components/Field.jsx";
import AmmunitionButton from "../components/AmmunitionInfo.jsx";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  Mail,
  Plus,
  Refresh,
  Trash,
} from "../components/Icons.jsx";
import { fromMap } from "../lookup";

/** Rows on one page of an armory table. See the paging note in Armory. */
const ARMORY_PAGE = 100;

//: How long the search waits after the last keystroke before it asks again.
const SEARCH_PAUSE_MS = 300;
const TABS = [
  { key: "manufacturers", label: "Manufacturers" },
  { key: "models", label: "Models" },
  { key: "calibers", label: "Calibers" },
  // The suggested articles, waiting on a person (2026-10-12): they sat above
  // every tab, pushing the tables down, whichever tab was being worked on.
  { key: "wikipedia", label: "Wikipedia" },
  // Each modern model's own page on its maker's site, found in the maker's
  // sitemap (app/services/makerpages.py) and decided here (2026-10-12).
  { key: "maker_pages", label: "Manufacturer pages" },
  // Every model's versions on one list, approved or switched off in bulk
  // (2026-10-14): they could only be reached one model's dialog at a time.
  { key: "variants", label: "Variants" },
];

/** The two tabs of suggestions, and which kind each shows. */
const SUGGESTION_FIELD = { wikipedia: "wikipedia", maker_pages: "maker_page" };

// Manufacturers first: what the armory is browsed by (asked for on 2026-10-12).
const DEFAULT_TAB = "manufacturers";

/**
 * The tab lives in the URL fragment, and the fragment is the only copy of it.
 *
 * Held in component state it was invisible to the browser, so Back from the
 * armory did not go to the tab you came from — it left the page entirely, and
 * which page it landed on depended on how you had got here. A fragment is the
 * right shape for it: it names a section of one document, it costs no request,
 * and every tab click becomes a history entry that Back and Forward walk.
 *
 * Written singular, because it names *the* section. Read either way, so a
 * hand-typed or older plural link still lands where it means to.
 */
const TAB_HASH = {
  manufacturers: "manufacturer",
  models: "model",
  calibers: "caliber",
  wikipedia: "wikipedia",
  maker_pages: "manufacturer-pages",
  variants: "variants",
};
const TAB_FROM_HASH = {
  manufacturer: "manufacturers",
  manufacturers: "manufacturers",
  model: "models",
  models: "models",
  caliber: "calibers",
  calibers: "calibers",
  wikipedia: "wikipedia",
  "manufacturer-pages": "maker_pages",
  "maker-pages": "maker_pages",
  maker_pages: "maker_pages",
  variant: "variants",
  variants: "variants",
};

/** Which tab a URL fragment asks for, falling back to the default. */
export function tabFromHash(hash) {
  const wanted = decodeURIComponent(String(hash || "").replace(/^#/, ""))
    .trim()
    .toLowerCase();
  return fromMap(TAB_FROM_HASH, wanted, DEFAULT_TAB);
}

/**
 * The inventory, filtered to the listings one armory row accounts for.
 *
 * Three deliberate choices, each of which changes what comes back:
 *
 * - **Models filter by id, calibers and makers by name.** That is not a
 *   preference, it is what a listing stores: `Item.firearm_model_id` is a real
 *   foreign key, while `Item.caliber` and `Item.manufacturer` are the text a
 *   scan read off the shop. Filtering a model by name would miss every listing
 *   matched to it under a different spelling.
 * - **Aliases go in too.** ".32 ACP" and "7.65mm Browning" are one cartridge
 *   written two ways, and the filter matches the stored string exactly — so a
 *   row with aliases needs one value per spelling or it shows half its
 *   listings. Which is the same half-answer that makes somebody think a merge
 *   is unnecessary.
 * - **Everything, not just what is in stock.** A pending row usually arrived
 *   from a listing that has since sold, and defaulting to available would
 *   answer "no listings" for exactly the rows most in need of a decision.
 *
 * These navigate in the current tab, which is not the obvious choice -- looking
 * at the listings is something you do *while* deciding about a row.
 *
 * **The original reason for it has since gone away.** A new tab was tried and
 * backed out because the session was a bearer token in sessionStorage, which
 * is per-tab and which a browser will not copy into a tab opened with
 * target="_blank": every eye landed on the sign-in screen. The session is a
 * cookie now, shared across tabs, so a new tab would work.
 *
 * It stays in the current tab anyway, on the weaker argument that was always
 * underneath: Back has to bring the row list back exactly as it was, and the
 * URL carries the tab, the filter, the sort and the search precisely so that
 * it can. Worth revisiting if anybody would rather have the new tab -- this is
 * now a preference rather than a constraint.
 */
function listingsHref(tab, row) {
  const params = new URLSearchParams();
  if (tab === "models" && row.mention_count != null) {
    // A row awaiting approval links nothing, so filtering by it would show an
    // empty page. It opens the listings that *name* it instead -- the same
    // quoted search the server counted for the Listings column, so the number
    // in the table is the number of listings on the page it opens.
    params.set("search", mentionSearch(row.name));
  } else if (tab === "models") {
    params.set("model", String(row.id));
  } else {
    const param = tab === "calibers" ? "caliber" : "manufacturer";
    const names = [row.name, ...(row.aliases || "").split("\n")]
      .map((name) => name.trim())
      .filter(Boolean);
    // A row whose alias repeats its own name would otherwise send it twice.
    [...new Set(names)].forEach((name) => params.append(param, name));
  }
  params.set("availability", "all");
  return `/?${params.toString()}`;
}

/** The browse search for a phrase, quoted whole. Mirrors search.mention_search. */
function mentionSearch(name) {
  return `"${name.replace(/"/g, " ").split(/\s+/).filter(Boolean).join(" ")}"`;
}

/**
 * The Listings cell for a model row.
 *
 * An approved row shows how many listings it is linked to. A row awaiting
 * approval is linked to none -- that is what awaiting approval means -- so a
 * flat 0 there said nothing about whether it was worth approving. It shows how
 * many listings name it instead, marked as mentions so the two are not read
 * as the same thing.
 */
function ListingsCell({ row }) {
  if (row.mention_count == null) return row.item_count;
  return (
    <span
      className="armory-mentions"
      title="Awaiting approval, so nothing is linked yet. This is how many listings name it; the eye shows them."
    >
      {row.mention_count} mention{row.mention_count === 1 ? "" : "s"}
    </span>
  );
}

//: What the Showing box starts on, and the only value left out of the URL.
//: A page with no query string is the pending queue, which is what somebody
//: opening the armory has come to work through.
const DEFAULT_STATUS = "pending";

/**
 * Whether deleting this row will actually get rid of it.
 *
 * Usually not, and that is the thing the trashcan never said. Every
 * ``propose_*`` in services/armory.py looks a name up **regardless of status
 * or enabled**, so any surviving row — disabled, pending, merged — permanently
 * stops that name being proposed again, and a deleted one comes back the next
 * time a scan meets it. The row is the tombstone.
 *
 * Two signals answer it, and both are already on the row:
 *
 * - `first_seen_in` is set, so a scan proposed this name and will again;
 * - it is in the shipped armory file, so `armory seed` re-adds it — which the
 *   page cannot see from here, so `status` standing in is the honest
 *   approximation: everything the file carries arrives pending.
 *
 * Delete is still right for a row somebody created by mistake, or a duplicate.
 * What this changes is that it stops being the gesture that *looks* decisive
 * while quietly meaning "ask me again next week".
 */
function comesBack(row) {
  return Boolean((row.first_seen_in || "").trim());
}

//: The Showing filter. Not the same list as the row's status, and the
//: difference is "Disabled": a row somebody switched off has been ruled on, so
//: it leaves Awaiting approval rather than sitting in the queue forever, and it
//: leaves Production rather than showing there grayed out. Merging away also
//: switches a row off, but those have their own entry and stay out of this one.
const STATUSES = [
  { value: "pending", label: "Awaiting approval" },
  { value: "approved", label: "Production" },
  { value: "disabled", label: "Disabled" },
  { value: "merged", label: "Merged away" },
  { value: "", label: "Everything" },
];

//: The heading over a table: "Models in production (1,510)".
const TAB_NOUNS = {
  manufacturers: "Manufacturers",
  models: "Models",
  calibers: "Calibers",
};
const SHOWING_PHRASES = {
  pending: "awaiting approval",
  approved: "in production",
  disabled: "switched off",
  merged: "merged away",
  "": "in the armory",
};

//: What Showing means on the Manufacturer pages and Wikipedia tabs
//: (2026-10-13): the links waiting on a decision, the ones in the armory, and
//: the ones turned down. "Disabled" stands for rejected, so the value carries
//: over between tabs.
const LINK_VIEWS = [
  { value: "pending", label: "Awaiting approval" },
  { value: "approved", label: "Production" },
  { value: "disabled", label: "Rejected" },
  { value: "", label: "Everything" },
];

//: What Showing means on the Variants tab: a version is waiting, in use, or
//: switched off -- never merged.
const VARIANT_VIEWS = [
  { value: "pending", label: "Awaiting approval" },
  { value: "approved", label: "Approved" },
  { value: "disabled", label: "Switched off" },
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
  modern_production: false,
  maker_url: "",
  frame_size: "",
  position: 1000,
  enabled: true,
  notes: "",
};

//: The primers a cartridge takes, as app/services/reloading.py names them.
const PRIMER_SIZES = [
  "Small pistol",
  "Large pistol",
  "Small rifle",
  "Large rifle",
  ".50 BMG",
  "209 shotshell",
  "Berdan",
];

/** The reloading fields of a caliber, as the form holds them. */
function reloadingForm(caliber) {
  return {
    primer_size: caliber.primer_size || "",
    primer_magnum: Boolean(caliber.primer_magnum),
    powder_name: caliber.powder_name || "",
    powder_charge_gr: caliber.powder_charge_gr ?? "",
    powder_bullet_gr: caliber.powder_bullet_gr ?? "",
  };
}

/**
 * Only what was changed: a primer read from the article and saved untouched
 * stays the article's, and the next read may still correct it.
 */
function reloadingChanges(before, form) {
  const number = (value) => (value === "" ? null : Number(value));
  const changes = {};
  if (
    form.primer_size !== before.primer_size ||
    form.primer_magnum !== before.primer_magnum
  ) {
    changes.primer_size = form.primer_size;
    changes.primer_magnum = form.primer_size ? form.primer_magnum : null;
  }
  if (form.powder_name !== before.powder_name) changes.powder_name = form.powder_name;
  for (const key of ["powder_charge_gr", "powder_bullet_gr"]) {
    if (String(form[key]) !== String(before[key])) changes[key] = number(form[key]);
  }
  return changes;
}

/** "Hodgdon Varget — $52.12/lb", or that Graf & Sons is out of it. */
function powderLabel(powder) {
  if (!powder.in_stock) return `${powder.name} (out of stock)`;
  return powder.unit_price != null
    ? `${powder.name} — $${powder.unit_price.toFixed(2)}/lb`
    : powder.name;
}

/**
 * The load and the primer, typed by hand. Asked for on 2026-10-14: the
 * powder is picked from what Graf & Sons sells, the charge typed, and the
 * server prices the charge from the powder's price per pound.
 */
function ReloadingFields({ form, set }) {
  const [powders, setPowders] = useState(null);
  useEffect(() => {
    let live = true;
    api
      .ammoPowders()
      .then((found) => live && setPowders(found))
      .catch(() => live && setPowders([]));
    return () => {
      live = false;
    };
  }, []);
  const listed = powders || [];
  // A load naming a powder no longer listed still shows what it names.
  const missing =
    form.powder_name && powders && !listed.some((p) => p.name === form.powder_name);
  return (
    <fieldset className="caliber-reloading" data-testid="caliber-reloading">
      <legend>Reloading</legend>
      <div className="form-row form-row--2">
        <Field
          label="Primer"
          hint="Read from the article's infobox; choose one to set it by hand, blank to hand it back."
        >
          {(id, describedBy) => (
            <select
              id={id}
              aria-describedby={describedBy}
              className="input"
              value={form.primer_size}
              onChange={set("primer_size")}
            >
              <option value="">Not known</option>
              {PRIMER_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Magnum primer">
          {(id, describedBy) => (
            <label className="checkbox">
              <input
                id={id}
                aria-describedby={describedBy}
                type="checkbox"
                checked={form.primer_magnum}
                disabled={!form.primer_size}
                onChange={set("primer_magnum")}
              />
              <span>Magnum</span>
            </label>
          )}
        </Field>
      </div>
      <div className="form-row form-row--3">
        <Field label="Powder" hint="What Graf & Sons sells, priced by the pound.">
          {(id, describedBy) => (
            <select
              id={id}
              aria-describedby={describedBy}
              className="input"
              value={form.powder_name}
              onChange={set("powder_name")}
              disabled={powders === null}
            >
              <option value="">{powders === null ? "Loading…" : "No load"}</option>
              {missing && <option value={form.powder_name}>{form.powder_name}</option>}
              {listed.map((powder) => (
                <option key={powder.name} value={powder.name}>
                  {powderLabel(powder)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Charge (grains)">
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="number"
              step="0.1"
              min="0"
              max="999"
              value={form.powder_charge_gr}
              onChange={set("powder_charge_gr")}
            />
          )}
        </Field>
        <Field
          label="For a bullet of (grains)"
          hint="Optional; prices that weight's bullet."
        >
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="number"
              step="1"
              min="0"
              max="1999"
              value={form.powder_bullet_gr}
              onChange={set("powder_bullet_gr")}
            />
          )}
        </Field>
      </div>
    </fieldset>
  );
}

const EMPTY_CALIBER = {
  name: "",
  aliases: "",
  notes: "",
  enabled: true,
  wikipedia_url: "",
  bullet_diameter_in: "",
};

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

/**
 * Every model's variants on one list (asked for on 2026-10-14, "shouldn't that
 * be on its own tab?"): the 605 a first read of the manufacturers' sites
 * proposed could be seen and approved only one model's dialog at a time. The
 * same Showing filter and search as the other tabs; approve or switch off any
 * selection, a row or everything listed. A variant is still edited in its
 * model's dialog.
 */
function VariantsTab({ view, search, onChanged }) {
  const [rows, setRows] = useState(null);
  const [selected, setSelected] = useState(() => new Set());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    const params = { status: view };
    if (search.trim()) params.search = search.trim();
    setRows(await api.armoryVariants(params));
    setSelected(new Set());
  }, [view, search]);

  useEffect(() => {
    setRows(null);
    load().catch((err) => setError(err.message));
  }, [load]);

  async function act(call, ids) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      let changed = 0;
      for (let at = 0; at < ids.length; at += BATCH) {
        changed += (await call(ids.slice(at, at + BATCH))).changed;
      }
      setMessage(`${countLabel(changed, "variant", "variants")} done.`);
      await load();
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const ids = [...selected];
  const all = rows && rows.length > 0 && selected.size === rows.length;
  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const noun = VARIANT_VIEWS.find((entry) => entry.value === view)?.label.toLowerCase();
  return (
    <div data-testid="variants-tab">
      <h2 className="armory-count">
        Variants {view ? noun : "in the armory"}
        {search.trim() && <> matching “{search.trim()}”</>} (
        {rows ? rows.length.toLocaleString() : "…"})
      </h2>
      {message && <p className="alert alert--success">{message}</p>}
      {error && <p className="alert alert--error">{error}</p>}
      {ids.length > 0 && (
        <div className="alert alert--info armory-bulk">
          <span>{countLabel(ids.length, "variant", "variants")} selected</span>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            disabled={busy}
            onClick={() => act(api.approveVariants, ids)}
          >
            Approve
          </button>
          <button
            type="button"
            className="btn btn--secondary btn--sm"
            disabled={busy}
            onClick={() => act(api.disableVariants, ids)}
          >
            Switch off
          </button>
        </div>
      )}
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <SelectAllCell
                all={Boolean(all)}
                some={selected.size > 0}
                disabled={!rows || rows.length === 0}
                onToggle={() =>
                  setSelected(
                    all ? new Set() : new Set((rows || []).map((row) => row.id)),
                  )
                }
              />
              <th>Variant</th>
              <th>Model</th>
              <th>Caliber</th>
              <th>Barrel</th>
              <th>Frame</th>
              <th>Finish</th>
              <th>MSRP</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rows === null && (
              <tr>
                <td colSpan={9} className="loading-row">
                  <span className="spinner" aria-label="Loading" />
                </td>
              </tr>
            )}
            {rows &&
              rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${row.label}`}
                      checked={selected.has(row.id)}
                      onChange={() => toggle(row.id)}
                    />
                  </td>
                  <td>
                    {row.maker_url ? (
                      <a href={row.maker_url} target="_blank" rel="noopener noreferrer">
                        {row.label}
                      </a>
                    ) : (
                      row.label
                    )}
                    {!row.enabled && <div className="muted">switched off</div>}
                  </td>
                  <td>{row.model_name}</td>
                  <td>{row.caliber || "—"}</td>
                  <td>{row.barrel_inches != null ? `${row.barrel_inches}"` : "—"}</td>
                  <td>{row.frame_size || "—"}</td>
                  <td>{row.finish || "—"}</td>
                  <td>{row.msrp != null ? `$${row.msrp.toFixed(2)}` : "—"}</td>
                  <td className="table__actions">
                    {(row.status !== "approved" || !row.enabled) && (
                      <button
                        type="button"
                        className="btn btn--secondary btn--sm"
                        aria-label={`Approve ${row.label}`}
                        disabled={busy}
                        onClick={() => act(api.approveVariants, [row.id])}
                      >
                        Approve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            {rows && rows.length === 0 && (
              <tr>
                <td colSpan={9} className="loading-row">
                  Nothing here.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
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

/** How to order names on this tab. Only the calibers need the bore rules. */
const nameOrder = (tab) => (tab === "calibers" ? compareCalibers : COLLATOR.compare);

//: Sorting starts on the name, ascending, for every tab -- which is what makes
//: the Manufacturers tab alphabetical. Its rows arrive from the API ordered by
//: `position` instead, because that is the order the matching rules are tried
//: in and the API is right to report it that way; it is simply not the order
//: to read fifty firms in.
const DEFAULT_SORT = { key: "name", direction: "asc" };

/** The sort a query string asks for. "name" ascending, "-name" descending. */
function parseSort(search) {
  const raw = new URLSearchParams(search).get("sort");
  if (!raw) return DEFAULT_SORT;
  return raw.startsWith("-")
    ? { key: raw.slice(1), direction: "desc" }
    : { key: raw, direction: "asc" };
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
          modern_production: Boolean(model.modern_production),
          maker_url: model.maker_url || "",
          frame_size: model.frame_size || "",
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
          // Sent blank rather than null to clear it: the update reads an
          // absent field as "leave it", and null is what absent looks like.
          maker_url: form.maker_url.trim(),
          frame_size: form.frame_size,
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
          label="Modern production"
          hint="Still made, so a new one can be bought. A listing links to the manufacturer's page for it."
        >
          {(id, describedBy) => (
            <label className="checkbox">
              <input
                id={id}
                aria-describedby={describedBy}
                type="checkbox"
                checked={form.modern_production}
                onChange={set("modern_production")}
              />
              <span>Still made</span>
            </label>
          )}
        </Field>
        <Field
          label="Manufacturer's page"
          hint="This model on its manufacturer's site. Shown in What the armory knows on every listing of it."
        >
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="url"
              value={form.maker_url}
              onChange={set("maker_url")}
              maxLength={500}
              placeholder="https://"
            />
          )}
        </Field>
      </div>

      <div className="form-row form-row--2">
        <Field
          label="Frame size"
          hint="Only for a model made in one size: a Glock 19 is a Compact, a Model 10 a K-frame. Its listings take it when they do not say. A model made in several leaves it blank and its variants carry theirs."
        >
          {(id, describedBy) => (
            <FrameSizeSelect
              id={id}
              describedBy={describedBy}
              value={form.frame_size}
              onChange={set("frame_size")}
            />
          )}
        </Field>
      </div>

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
      ? {
          name: caliber.name,
          aliases: caliber.aliases || "",
          notes: caliber.notes || "",
          enabled: caliber.enabled !== false,
          wikipedia_url: caliber.wikipedia_url || "",
          bullet_diameter_in: caliber.bullet_diameter_in ?? "",
          ...reloadingForm(caliber),
        }
      : EMPTY_CALIBER,
  );
  const [before] = useState(() => (editing ? reloadingForm(caliber) : null));
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
        // A blank diameter is "not known", not zero.
        const {
          primer_size: _primer,
          primer_magnum: _magnum,
          powder_name: _powder,
          powder_charge_gr: _charge,
          powder_bullet_gr: _bullet,
          ...rest
        } = form;
        onSubmit({
          ...rest,
          bullet_diameter_in:
            form.bullet_diameter_in === "" ? null : Number(form.bullet_diameter_in),
          ...(editing ? reloadingChanges(before, form) : {}),
        });
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
      {/*
        The same switch models and makers have had. It is how a cartridge gets
        *rejected*: deleting is not, because a surviving row is what stops a
        scan proposing the name again — see migration 0018.
      */}
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
      {/* For the ammunition facts: the article is where the bullet's diameter
          and weights are read from, once, and again after every edit here. */}
      <div className="form-row">
        <Field
          label="Wikipedia article"
          hint="The cartridge's article. Usually proposed for you under Wikipedia suggestions."
        >
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="url"
              value={form.wikipedia_url}
              onChange={set("wikipedia_url")}
              placeholder="https://en.wikipedia.org/wiki/…"
            />
          )}
        </Field>
        <Field
          label="Bullet diameter (inches)"
          hint="Read from the article; type it where the article has none."
        >
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="number"
              step="0.0001"
              min="0"
              max="2"
              value={form.bullet_diameter_in}
              onChange={set("bullet_diameter_in")}
            />
          )}
        </Field>
      </div>
      {editing && <ReloadingFields form={form} set={set} />}
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

const EMPTY_MAKER = {
  name: "",
  aliases: "",
  marks: "",
  position: 1000,
  enabled: true,
  notes: "",
  country: "",
  website: "",
  wikipedia_url: "",
};

/**
 * What deleting this row will and will not do.
 *
 * Offered instead of doing it, when the row is one a scan will simply propose
 * again. See :func:`comesBack`.
 */
function DeleteForm({ row, canDisable, error, onDelete, onDisable }) {
  const returning = comesBack(row);
  const seen = (row.first_seen_in || "").split("\n").filter(Boolean);

  return (
    <div>
      {returning ? (
        <p className="field__hint" style={{ marginTop: 0 }}>
          <strong>{row.name}</strong> was proposed by a scan, and will be proposed again
          the next time a listing’s title names it. Deleting it removes it until then.
          {canDisable
            ? " Disabling keeps the row, takes it out of matching, and stops it being proposed."
            : " Sending it back for approval does the same: a pending row matches nothing and stops it being proposed."}
        </p>
      ) : (
        <p className="field__hint" style={{ marginTop: 0 }}>
          Delete <strong>{row.name}</strong>? Nothing has proposed this name, so it should
          stay gone.
        </p>
      )}

      {seen.length > 0 && (
        <p className="field__hint">
          First seen in: <em>{seen[0]}</em>
        </p>
      )}

      {Boolean(row.item_count) && (
        <p className="field__hint">
          {row.item_count} listing{row.item_count === 1 ? "" : "s"} carry this name and
          will be re-derived.
        </p>
      )}

      {error && <p className="alert alert--error">{error}</p>}

      <div className="page-head__actions">
        {returning && (
          <button type="button" className="btn btn--primary" onClick={onDisable}>
            {canDisable ? "Disable instead" : "Send back for approval"}
          </button>
        )}
        <button type="button" className="btn btn--danger" onClick={onDelete}>
          {returning ? "Delete anyway" : "Delete"}
        </button>
      </div>
    </div>
  );
}

/**
 * Choose which of a row's spellings is its name.
 *
 * Not the Name field on the edit form, and deliberately not reachable from it
 * by typing. Renaming a row leaves its old spelling behind — the row stops
 * recognizing the text it was built to recognize — and leaves every listing
 * already stamped with the old name pointing at a name nothing has any more.
 * This keeps the old name as an alias and restamps the listings, in one step,
 * and it will only ever choose between spellings the row already has.
 */
function PrimaryNameForm({ row, table, error, onSubmit }) {
  const spellings = [row.name, ...(row.aliases || "").split("\n")]
    .map((text) => text.trim())
    .filter(Boolean);
  const [choice, setChoice] = useState(row.name);
  const unchanged = choice === row.name;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!unchanged) onSubmit(choice);
      }}
    >
      <p className="field__hint" style={{ marginTop: 0 }}>
        The name is what gets written onto every listing this row matches. Whichever
        spelling you pick becomes it; <strong>{row.name}</strong> stays on as an alias, so
        nothing this row recognizes today stops being recognized.
      </p>
      <Field label="Primary name" hint="Only a spelling this row already has.">
        {(id, describedBy) => (
          <select
            id={id}
            aria-describedby={describedBy}
            className="select"
            value={choice}
            onChange={(event) => setChoice(event.target.value)}
          >
            {spellings.map((text) => (
              <option key={text} value={text}>
                {text}
                {text === row.name ? " — current" : ""}
              </option>
            ))}
          </select>
        )}
      </Field>
      {table !== "models" && Boolean(row.item_count) && !unchanged && (
        <p className="field__hint">
          {row.item_count} listing{row.item_count === 1 ? "" : "s"} carry “{row.name}” and
          will be restamped “{choice}”.
        </p>
      )}
      {spellings.length < 2 && (
        <p className="field__hint">
          This row has no other spelling yet. Add one under “Also written as” first.
        </p>
      )}
      {error && <p className="alert alert--error">{error}</p>}
      <div className="page-head__actions">
        <button type="submit" className="btn btn--primary" disabled={unchanged}>
          Make it the primary
        </button>
      </div>
    </form>
  );
}

function MakerForm({ maker, countries, onSubmit, error }) {
  const editing = Boolean(maker);
  const [form, setForm] = useState(() =>
    editing
      ? {
          name: maker.name,
          aliases: maker.aliases || "",
          marks: maker.marks || "",
          position: maker.position,
          enabled: maker.enabled,
          notes: maker.notes || "",
          country: maker.country || "",
          website: maker.website || "",
          wikipedia_url: maker.wikipedia_url || "",
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
      {/* The arsenal's own codes. Kept apart from the spellings above because
          they mean nothing on their own -- "SA" anywhere else is not
          Springfield -- and are only read on a listing of a model this firm
          is linked to. See app/services/arsenals.py. */}
      <Field
        label="Marks"
        hint={
          "One per line — factory codes and stamps that name this firm only on its own " +
          "models: “byf” on a K98k, “SA” on a Garand. Never matched anywhere else."
        }
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={2}
            value={form.marks}
            onChange={set("marks")}
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
      <Field
        label="Country"
        hint={
          "Where the firm is. The last and weakest answer to “where is this from”: a " +
          "listing that states one keeps it, then the model’s pattern origin, then this. " +
          "A proxy rather than a statement — a Yugoslav-built M24/47 is a German pattern."
        }
      >
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            list="armory-countries"
            value={form.country}
            onChange={set("country")}
            maxLength={64}
            placeholder="United States"
          />
        )}
      </Field>
      {/* The same list the model form offers, and it has to be in the DOM of
          whichever form is open — a datalist declared in the other one is not
          rendered at all while this modal is up. */}
      <datalist id="armory-countries">
        {(countries || []).map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <Field
        label="Website"
        hint="The firm's own site. A listing of one of its models still in production searches it."
      >
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            value={form.website}
            onChange={set("website")}
            maxLength={500}
            placeholder="https://www.example.com"
          />
        )}
      </Field>
      <Field
        label="Wikipedia"
        hint="The firm's article. Kept apart from its website: a firm long gone has an article and no site."
      >
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            value={form.wikipedia_url}
            onChange={set("wikipedia_url")}
            maxLength={500}
            placeholder="https://en.wikipedia.org/wiki/…"
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

/** How many changes a section lists before it says "and N more". */
const APPLY_SHOWN = 40;

/**
 * Make this armory match the shipped file, after seeing exactly what changes.
 *
 * "Load shipped armory" only adds what is missing, awaiting approval, and
 * never touches a row already here -- so a cleaned-up file (a duplicate
 * merged, a stray alias moved) reached nobody that already had the rows. This
 * applies the file: statuses, aliases, merges and corrections, and new rows
 * as the file has them. It overwrites, which is why the plan is shown first:
 * a row edited here since the file was exported is put back to the file's
 * version, and that should be seen before it happens. Nothing is deleted.
 * Every change goes to the audit log with what the row held, so each can be
 * undone from there on its own.
 */
function ArmoryApply({ onClose, onApplied }) {
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .armorySyncPlan()
      .then((found) => live && setPlan(found))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, []);

  const apply = async () => {
    setWorking(true);
    setError("");
    try {
      onApplied(await api.applyArmorySync());
    } catch (err) {
      setError(err.message);
      setWorking(false);
    }
  };

  const nothing = plan && plan.added + plan.updated === 0;
  const sections = plan
    ? [
        ["Calibers", plan.calibers],
        ["Models", plan.models],
        ["Manufacturers", plan.manufacturers],
      ].filter(([, changes]) => changes.length)
    : [];

  return (
    <Modal
      title="Apply the shipped armory"
      wide
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--secondary" onClick={onClose}>
            {nothing ? "Done" : "Cancel"}
          </button>
          {plan && !nothing && (
            <button
              type="button"
              className="btn btn--primary"
              disabled={working}
              onClick={apply}
            >
              {working ? "Applying…" : `Apply ${plan.added + plan.updated} change(s)`}
            </button>
          )}
        </>
      }
    >
      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      {!plan && !error && <p className="muted">Reading the shipped file…</p>}
      {nothing && <p>This armory already matches the shipped file. Nothing to change.</p>}
      {plan && !nothing && (
        <>
          <p data-testid="armory-apply-summary">
            <strong>{plan.added}</strong> to add and <strong>{plan.updated}</strong> to
            change. A row edited here since the file was made is put back to the
            file&rsquo;s version. Nothing is deleted. Every change is written to the audit
            log, where each one can be undone, and the listings it touches are matched
            again.
          </p>
          {sections.map(([title, changes]) => (
            <section key={title} className="armory-apply__section">
              <h3>
                {title} ({changes.length})
              </h3>
              <ul className="armory-apply__list">
                {changes.slice(0, APPLY_SHOWN).map((change) => (
                  <li key={`${change.action}:${change.name}`}>
                    {change.action === "add" ? (
                      <>
                        <span className="chip chip--success">add</span> {change.name}
                      </>
                    ) : (
                      <>
                        <span className="chip chip--info">change</span> {change.name}
                        <span className="muted"> — {change.fields.join(", ")}</span>
                      </>
                    )}
                  </li>
                ))}
              </ul>
              {changes.length > APPLY_SHOWN && (
                <p className="muted">and {changes.length - APPLY_SHOWN} more</p>
              )}
            </section>
          ))}
        </>
      )}
    </Modal>
  );
}

//: The frame sizes: services/frames.SIZES, in its order -- a pistol's size,
//: then a revolver's frame.
const FRAME_SIZES = [
  "Long slide",
  "Full size",
  "Compact",
  "Subcompact",
  "Micro",
  "J-frame",
  "K-frame",
  "L-frame",
  "N-frame",
  "X-frame",
  "Small frame",
  "Medium frame",
  "Large frame",
];

function FrameSizeSelect({ id, describedBy, value, onChange }) {
  return (
    <select
      id={id}
      aria-describedby={describedBy}
      className="select"
      value={value}
      onChange={onChange}
    >
      <option value="">—</option>
      {FRAME_SIZES.map((name) => (
        <option key={name}>{name}</option>
      ))}
    </select>
  );
}

//: The finishes a variant can be: services/variants.FINISHES, in its order.
const FINISHES = [
  "Black",
  "Blued",
  "Stainless",
  "Two-tone",
  "Nickel",
  "Chrome",
  "Hard Chrome",
  "FDE",
  "OD Green",
  "Gray",
  "Parkerized",
  "Cerakote",
];

const EMPTY_VARIANT = {
  label: "",
  caliber_id: "",
  barrel_inches: "",
  finish: "",
  frame_size: "",
  upc: "",
  maker_part: "",
  msrp: "",
  maker_url: "",
  status: "approved",
};

/**
 * A model's variants, edited in the model's own dialog.
 *
 * A model is a design and a variant a product within it -- the 4" black .44
 * Tracker, with its UPC and MSRP. A listing that states a barrel and a finish
 * is matched to the one it is (services/variants.py), and every change here
 * re-matches the model's listings at once. Slice 2 of "New-gun prices".
 */
function VariantsEditor({ model, calibers }) {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(EMPTY_VARIANT);
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .modelVariants(model.id)
      .then(setRows)
      .catch((err) => setError(err.message));
  }, [model.id]);
  useEffect(load, [load]);

  const set = (key) => (event) =>
    setForm((prev) => ({ ...prev, [key]: event.target.value }));

  const payload = () => ({
    label: form.label.trim(),
    caliber_id: form.caliber_id ? Number(form.caliber_id) : null,
    barrel_inches: form.barrel_inches === "" ? null : Number(form.barrel_inches),
    finish: form.finish || null,
    frame_size: form.frame_size || null,
    upc: form.upc.trim() || null,
    maker_part: form.maker_part.trim() || null,
    msrp: form.msrp === "" ? null : Number(form.msrp),
    maker_url: form.maker_url.trim(),
    status: form.status,
  });

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    try {
      if (editingId) await api.updateVariant(editingId, payload());
      else await api.addVariant(model.id, payload());
      setForm(EMPTY_VARIANT);
      setEditingId(null);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  const remove = async (row) => {
    setError("");
    try {
      await api.deleteVariant(row.id);
      load();
    } catch (err) {
      setError(err.message);
    }
  };

  // What a maker's site proposed arrives pending; this is where it is let in.
  const approve = async (ids) => {
    setError("");
    try {
      for (const id of ids) await api.updateVariant(id, { status: "approved" });
      load();
    } catch (err) {
      setError(err.message);
    }
  };
  const pendingIds = (rows || [])
    .filter((row) => row.status !== "approved")
    .map((r) => r.id);

  const edit = (row) => {
    setEditingId(row.id);
    setForm({
      label: row.label,
      caliber_id: row.caliber_id ? String(row.caliber_id) : "",
      barrel_inches: row.barrel_inches ?? "",
      finish: row.finish || "",
      frame_size: row.frame_size || "",
      upc: row.upc || "",
      maker_part: row.maker_part || "",
      msrp: row.msrp ?? "",
      maker_url: row.maker_url || "",
      status: row.status,
    });
  };

  return (
    <section className="variants" data-testid="variants-editor">
      <h3>Variants</h3>
      <p className="field__hint">
        The versions a buyer chooses between. A listing whose words state a barrel, a
        frame size and a finish is matched to the one it is.
      </p>
      {error && <p className="alert alert--error">{error}</p>}
      {pendingIds.length > 1 && (
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          onClick={() => approve(pendingIds)}
        >
          Approve all pending ({pendingIds.length})
        </button>
      )}
      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Variant</th>
                <th>Barrel</th>
                <th>Frame</th>
                <th>Finish</th>
                <th>MSRP</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    {row.label}
                    <div className="muted">
                      {[row.caliber, row.upc && `UPC ${row.upc}`, row.maker_part]
                        .filter(Boolean)
                        .join(" · ")}
                      {row.status !== "approved" && " · awaiting approval"}
                    </div>
                  </td>
                  <td>{row.barrel_inches != null ? `${row.barrel_inches}"` : "—"}</td>
                  <td>{row.frame_size || "—"}</td>
                  <td>{row.finish || "—"}</td>
                  <td>{row.msrp != null ? `$${row.msrp.toFixed(2)}` : "—"}</td>
                  <td className="table__actions">
                    {row.status !== "approved" && (
                      <button
                        type="button"
                        className="btn btn--secondary btn--sm"
                        aria-label={`Approve ${row.label}`}
                        onClick={() => approve([row.id])}
                      >
                        Approve
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      aria-label={`Edit ${row.label}`}
                      onClick={() => edit(row)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      aria-label={`Delete ${row.label}`}
                      onClick={() => remove(row)}
                    >
                      <Trash size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <form className="variants__form" onSubmit={submit}>
        <Field label="Variant">
          {(id) => (
            <input
              id={id}
              className="input"
              value={form.label}
              onChange={set("label")}
              maxLength={200}
              placeholder='Tracker .44 Magnum 4" Black'
            />
          )}
        </Field>
        <div className="form-row form-row--3">
          <Field label="Variant caliber">
            {(id) => (
              <select
                id={id}
                className="select"
                value={form.caliber_id}
                onChange={set("caliber_id")}
              >
                <option value="">—</option>
                {(calibers || []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Barrel (inches)">
            {(id) => (
              <input
                id={id}
                className="input"
                inputMode="decimal"
                value={form.barrel_inches}
                onChange={set("barrel_inches")}
              />
            )}
          </Field>
          <Field label="Finish">
            {(id) => (
              <select
                id={id}
                className="select"
                value={form.finish}
                onChange={set("finish")}
              >
                <option value="">—</option>
                {FINISHES.map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </select>
            )}
          </Field>
        </div>
        <div className="form-row form-row--3">
          <Field label="Frame size">
            {(id) => (
              <FrameSizeSelect
                id={id}
                value={form.frame_size}
                onChange={set("frame_size")}
              />
            )}
          </Field>
        </div>
        <div className="form-row form-row--3">
          <Field label="UPC">
            {(id) => (
              <input
                id={id}
                className="input"
                inputMode="numeric"
                value={form.upc}
                onChange={set("upc")}
              />
            )}
          </Field>
          <Field label="Manufacturer's part number">
            {(id) => (
              <input
                id={id}
                className="input"
                value={form.maker_part}
                onChange={set("maker_part")}
              />
            )}
          </Field>
          <Field label="MSRP">
            {(id) => (
              <input
                id={id}
                className="input"
                inputMode="decimal"
                value={form.msrp}
                onChange={set("msrp")}
              />
            )}
          </Field>
        </div>
        <Field label="Variant's page">
          {(id) => (
            <input
              id={id}
              className="input"
              type="url"
              value={form.maker_url}
              onChange={set("maker_url")}
              placeholder="https://"
            />
          )}
        </Field>
        <div className="page-head__actions">
          <button
            type="submit"
            className="btn btn--primary btn--sm"
            disabled={!form.label.trim()}
          >
            {editingId ? "Save variant" : "Add variant"}
          </button>
          {editingId && (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => {
                setEditingId(null);
                setForm(EMPTY_VARIANT);
              }}
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

/** What a suggestion is for, as its row says it. */
const TARGET_LABEL = { manufacturer: "Manufacturer", model: "Model", caliber: "Caliber" };

/**
 * Wikipedia articles proposed for makers, models and calibers, waiting on a
 * person: the Armory's Wikipedia tab.
 *
 * Proposed by ``cli.py armory wikipedia`` and the caliber data's refresh (see
 * app/services/wikipedia.py), which take the first search result whose
 * categories say it is about a gun, a gun maker or a cartridge. "Confident"
 * means the article's title also names the row. Each is accepted -- which
 * writes the link onto the row -- or rejected, which keeps it from being
 * proposed again.
 *
 * The Armory loads them, for the count on the tab, and hands them here with
 * the search box's text. The Showing filter is about a row's status, which a
 * suggestion does not have, so it is left out.
 */
function WikipediaSuggestions({ rows, failure, search, onDecided, field = "wikipedia" }) {
  const makers = field === "maker_page";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const decide = async (call) => {
    setBusy(true);
    setError("");
    try {
      await call();
      onDecided?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const wanted = search.trim().toLowerCase();
  const shown = wanted
    ? rows.filter((row) =>
        [row.target_name, row.title, row.reason].some((text) =>
          String(text || "")
            .toLowerCase()
            .includes(wanted),
        ),
      )
    : rows;
  const confident = shown.filter((row) => row.confident);
  return (
    <div
      className="panel wiki-suggestions"
      data-testid={makers ? "maker-page-suggestions" : "wikipedia-suggestions"}
    >
      <div className="panel__head">
        <h2>{makers ? "Manufacturer page suggestions" : "Wikipedia suggestions"}</h2>
        {confident.length > 0 && (
          <button
            type="button"
            className="btn btn--primary btn--sm"
            disabled={busy}
            onClick={() =>
              decide(() =>
                wanted
                  ? api.acceptReferences(confident.map((row) => row.id))
                  : api.acceptConfidentReferences(field),
              )
            }
          >
            Accept all confident ({confident.length})
          </button>
        )}
      </div>
      {(error || failure) && <p className="alert alert--error">{error || failure}</p>}
      {shown.length === 0 ? (
        <div className="panel__body">
          <p className="muted" style={{ margin: 0 }}>
            {rows.length === 0
              ? makers
                ? "No suggestions waiting. New ones come from cli.py armory maker-pages, which reads the sitemaps of the manufacturers of every model marked as still made."
                : "No suggestions waiting. New ones come from the Wikipedia part of the caliber data on Site settings, and from cli.py armory wikipedia."
              : "No suggestion matches the search."}
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>For</th>
                <th>{makers ? "Page" : "Article"}</th>
                <th>Why</th>
                <th aria-label="Decide" />
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.id}>
                  <td>
                    {row.target_name}
                    <div className="muted">
                      {TARGET_LABEL[row.target_type] || row.target_type}
                    </div>
                  </td>
                  <td>
                    <a href={row.url} target="_blank" rel="noopener noreferrer">
                      {row.title}
                    </a>
                    {row.confident && (
                      <span className="chip chip--success wiki-suggestions__chip">
                        Confident
                      </span>
                    )}
                  </td>
                  <td className="muted">{row.reason}</td>
                  <td className="table__actions">
                    <button
                      type="button"
                      className="btn btn--secondary btn--sm"
                      disabled={busy}
                      aria-label={`Accept ${row.title} for ${row.target_name}`}
                      onClick={() => decide(() => api.acceptReferences([row.id]))}
                    >
                      Accept
                    </button>{" "}
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      disabled={busy}
                      aria-label={`Reject ${row.title} for ${row.target_name}`}
                      onClick={() => decide(() => api.rejectReferences([row.id]))}
                    >
                      Reject
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/**
 * The Manufacturer pages and Wikipedia tabs: a link the armory keeps on its
 * rows, suggested by a pass and decided here.
 *
 * Showing works on both (asked for on 2026-10-13, Wikipedia the same day):
 * Awaiting approval is the suggestions, Production every row that has a link
 * -- however it got one -- each editable or removable, with a form to add one
 * by hand, Rejected the suggestions turned down, and Everything all three.
 * A link lives on its row (a model's ``maker_url``, any row's
 * ``wikipedia_url``), so it is exported with the rest of the armory, and the
 * rejections go with it (``rejected_maker_pages``, ``rejected_wikipedia``).
 *
 * ``rows`` is every row that could carry one: ``{ key, table, type, id,
 * name, makers, url }``.
 */
function ReferenceLinks({ field, view, search, pending, rows, failure, onChanged }) {
  const pages = field === "maker_page";
  const noun = pages ? "manufacturer page" : "Wikipedia article";
  const prefix = pages ? "maker-pages" : "wikipedia";
  const [rejected, setRejected] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");
  const [adding, setAdding] = useState({ row: "", url: "" });
  const showPending = view === "pending" || view === "";
  const showProduction = view === "approved" || view === "";
  const showRejected = view === "disabled" || view === "";

  const loadRejected = useCallback(() => {
    api
      .referenceProposals({ field, status: "rejected" })
      .then(setRejected)
      .catch((err) => setError(err.message));
  }, [field]);
  useEffect(() => {
    if (showRejected) loadRejected();
  }, [showRejected, loadRejected]);

  const act = async (call) => {
    setBusy(true);
    setError("");
    try {
      await call();
      setEditing(null);
      loadRejected();
      onChanged?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const column = pages ? "maker_url" : "wikipedia_url";
  const write = (row, url) =>
    row.table === "manufacturers"
      ? api.updateManufacturer(row.id, { [column]: url })
      : api.updateArmoryRow(row.table, row.id, { [column]: url });
  // A row named twice -- "Mauser" the maker and "Mauser" the cartridge's
  // family, say -- is told apart by its type on the add form.
  const label = (row) => (pages ? row.name : `${row.name} (${row.type})`);

  /**
   * A row typed on the add form that the lists loaded with the page do not
   * have yet, asked of the server by name. Those lists are every row in the
   * armory and reload in the background after each change -- on an armory of
   * 2,500 rows, slowly enough that a model created and promoted a moment ago
   * was refused as "nothing in production called" it (2026-10-13).
   */
  const lookUp = async (typed) => {
    const found = /^(.*) \((Manufacturer|Model|Caliber)\)$/.exec(typed);
    const name = (pages ? typed : found?.[1] || typed).trim();
    const type = pages ? "Model" : found?.[2] || "Model";
    const table = { Manufacturer: "manufacturers", Model: "models", Caliber: "calibers" }[
      type
    ];
    const params = { search: name, status: "approved" };
    const answer = await (table === "manufacturers"
      ? api.manufacturers(params)
      : table === "calibers"
        ? api.armoryCalibers(params)
        : api.armoryModels(params));
    const hit = (answer || []).find(
      (row) => row.name.toLowerCase() === name.toLowerCase() && !row[column],
    );
    return hit
      ? { key: `${table}-${hit.id}`, table, type, id: hit.id, name: hit.name }
      : null;
  };

  const wanted = search.trim().toLowerCase();
  const matches = (...texts) =>
    !wanted ||
    texts.some((text) =>
      String(text || "")
        .toLowerCase()
        .includes(wanted),
    );
  const linked = rows
    .filter((row) => row.url)
    .filter((row) => matches(row.name, row.url, ...(row.makers || [])))
    .sort((a, b) => COLLATOR.compare(a.name, b.name));
  const unlinked = rows
    .filter((row) => !row.url)
    .sort((a, b) => COLLATOR.compare(a.name, b.name));
  const shownRejected = rejected.filter((row) =>
    matches(row.target_name, row.url, row.reason),
  );

  return (
    <>
      {error && <p className="alert alert--error">{error}</p>}
      {showPending && (
        <WikipediaSuggestions
          field={field}
          rows={pending}
          failure={failure}
          search={search}
          onDecided={onChanged}
        />
      )}
      {showProduction && (
        <div className="panel" data-testid={`${prefix}-production`}>
          <div className="panel__head">
            <h2>
              {pages ? "Manufacturer pages" : "Wikipedia articles"} in the armory (
              {linked.length})
            </h2>
          </div>
          <form
            className="panel__body form-row form-row--3"
            onSubmit={async (event) => {
              event.preventDefault();
              const row =
                unlinked.find((r) => label(r) === adding.row) ||
                (await lookUp(adding.row).catch(() => null));
              if (!row) {
                setError(
                  `Nothing in production called "${adding.row}" without a ${noun}.`,
                );
                return;
              }
              act(async () => {
                await write(row, adding.url);
                setAdding({ row: "", url: "" });
              });
            }}
          >
            <Field label={pages ? "Model" : "For"}>
              {(id) => (
                <>
                  <input
                    id={id}
                    className="input"
                    list={`${prefix}-candidates`}
                    value={adding.row}
                    placeholder={
                      pages ? "A model with no page yet" : "A row with no article yet"
                    }
                    onChange={(event) =>
                      setAdding((now) => ({ ...now, row: event.target.value }))
                    }
                  />
                  <datalist id={`${prefix}-candidates`}>
                    {unlinked.map((row) => (
                      <option key={row.key} value={label(row)} />
                    ))}
                  </datalist>
                </>
              )}
            </Field>
            <Field label={pages ? "Manufacturer's page" : "Wikipedia article"}>
              {(id) => (
                <input
                  id={id}
                  className="input"
                  type="url"
                  value={adding.url}
                  placeholder="https://"
                  onChange={(event) =>
                    setAdding((now) => ({ ...now, url: event.target.value }))
                  }
                />
              )}
            </Field>
            <div style={{ alignSelf: "end" }}>
              <button
                type="submit"
                className="btn btn--primary"
                disabled={busy || !adding.row || !adding.url}
              >
                <Plus /> Add {noun}
              </button>
            </div>
          </form>
          {linked.length === 0 ? (
            <div className="panel__body">
              <p className="muted" style={{ margin: 0 }}>
                {wanted ? `No ${noun} matches the search.` : `Nothing has a ${noun} yet.`}
              </p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{pages ? "Model" : "For"}</th>
                    <th>{pages ? "Manufacturer" : "Type"}</th>
                    <th>{pages ? "Page" : "Article"}</th>
                    <th aria-label="Change" />
                  </tr>
                </thead>
                <tbody>
                  {linked.map((row) => (
                    <tr key={row.key}>
                      <td>{row.name}</td>
                      <td className="muted">
                        {pages ? (row.makers || []).join(", ") || "—" : row.type}
                      </td>
                      <td>
                        {editing === row.key ? (
                          <input
                            className="input"
                            type="url"
                            aria-label={`${pages ? "Manufacturer's page" : "Wikipedia article"} for ${row.name}`}
                            value={draft}
                            onChange={(event) => setDraft(event.target.value)}
                          />
                        ) : (
                          <a href={row.url} target="_blank" rel="noopener noreferrer">
                            {row.url.replace(/^https?:\/\/(www\.)?/, "")}
                          </a>
                        )}
                      </td>
                      <td className="table__actions">
                        {editing === row.key ? (
                          <>
                            <button
                              type="button"
                              className="btn btn--primary btn--sm"
                              disabled={busy || !draft}
                              onClick={() => act(() => write(row, draft))}
                            >
                              Save
                            </button>{" "}
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              onClick={() => setEditing(null)}
                            >
                              Cancel
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="btn btn--secondary btn--sm"
                              aria-label={`Edit the ${pages ? "page" : "article"} for ${row.name}`}
                              onClick={() => {
                                setEditing(row.key);
                                setDraft(row.url);
                              }}
                            >
                              Edit
                            </button>{" "}
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              aria-label={`Remove the ${pages ? "page" : "article"} for ${row.name}`}
                              disabled={busy}
                              onClick={() => act(() => write(row, ""))}
                            >
                              Remove
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {showRejected && (
        <div className="panel" data-testid={`${prefix}-rejected`}>
          <div className="panel__head">
            <h2>
              Rejected {pages ? "manufacturer pages" : "Wikipedia articles"} (
              {shownRejected.length})
            </h2>
          </div>
          {shownRejected.length === 0 ? (
            <div className="panel__body">
              <p className="muted" style={{ margin: 0 }}>
                Nothing rejected{wanted ? " matches the search" : ""}.
              </p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>For</th>
                    <th>What it suggested</th>
                    <th aria-label="Decide" />
                  </tr>
                </thead>
                <tbody>
                  {shownRejected.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.target_name}
                        {!pages && (
                          <div className="muted">
                            {TARGET_LABEL[row.target_type] || row.target_type}
                          </div>
                        )}
                      </td>
                      <td>
                        <a href={row.url} target="_blank" rel="noopener noreferrer">
                          {pages
                            ? row.url.replace(/^https?:\/\/(www\.)?/, "")
                            : row.title}
                        </a>
                      </td>
                      <td className="table__actions">
                        <button
                          type="button"
                          className="btn btn--secondary btn--sm"
                          disabled={busy}
                          aria-label={`Accept ${row.url} for ${row.target_name} anyway`}
                          onClick={() => act(() => api.acceptReferences([row.id]))}
                        >
                          Accept anyway
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}

export default function Armory() {
  useTitle("Armory");
  const location = useLocation();
  const navigate = useNavigate();

  /**
   * Move one part of the URL and carry the rest.
   *
   * Both halves matter here and they are stored in different places — the tab
   * in the fragment, the Showing filter in the query — so anything that writes
   * one has to preserve the other. Neither `navigate({ hash })` nor
   * `setSearchParams()` does: each resolves against the current *path* and
   * drops the part it was not given, which would have made changing the filter
   * silently throw you back to the Models tab.
   */
  const go = useCallback(
    ({ search, hash, replace = false }) => {
      // Read the address bar, not the last render's `location`. Two of these
      // can happen before React has re-rendered — click a tab, then change the
      // filter — and the second would carry a stale copy of the other half and
      // silently undo the first: choosing "Everything" right after switching
      // to Calibers threw the page back to Models. `navigate` has already run
      // pushState by then, so window.location is current where a captured
      // `location` is a render behind.
      const now = window.location;
      navigate({ search: search ?? now.search, hash: hash ?? now.hash }, { replace });
    },
    [navigate],
  );

  /**
   * Write query parameters, `null` meaning "leave it out".
   *
   * Only null. An empty string is a value here and not an absence: the Showing
   * filter spells "Everything" as `?status=`, and absent means the default of
   * Awaiting approval, so deleting on "" quietly turned Everything back into
   * the pending queue.
   */
  const setParam = useCallback(
    (entries, { replace = false } = {}) => {
      const next = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(entries)) {
        if (value === null) next.delete(key);
        else next.set(key, value);
      }
      const query = next.toString();
      go({ search: query ? `?${query}` : "", replace });
    },
    [go],
  );

  // Derived, not mirrored. A useState kept alongside would have two sources of
  // truth for one fact, and Back would move the URL while the page stayed put.
  const tab = tabFromHash(location.hash);
  const setTab = useCallback(
    (key) => {
      // window.location for the same reason as `go`: this is a writer, and
      // writers have to see what the address bar says now.
      if (key === tabFromHash(window.location.hash)) return;
      // The sort goes with it, in the one navigation. The tabs do not share
      // their columns, so a sort on "Chambered in" means nothing on makers --
      // and doing it here rather than in an effect keeps it to a single history
      // entry, so one Back undoes the whole move.
      const next = new URLSearchParams(window.location.search);
      next.delete("sort");
      const query = next.toString();
      navigate({ search: query ? `?${query}` : "", hash: `#${TAB_HASH[key]}` });
    },
    [navigate],
  );

  // The same treatment for Showing, and for the same reason: it decides what
  // the page is showing, so Back should undo it. Absent means the default;
  // present-but-empty is "Everything", which is a real answer and not the
  // same thing as not having been asked.
  const query = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const statusFilter = query.has("status") ? query.get("status") : DEFAULT_STATUS;
  const setStatusFilter = useCallback(
    (value) => setParam({ status: value === DEFAULT_STATUS ? null : value }),
    [setParam],
  );

  // And the search box, for the same reason again. Replaces rather than pushes:
  // a history entry per keystroke would make Back walk the word backwards a
  // letter at a time instead of leaving the page you came from.
  const search = query.get("q") || "";
  const setSearch = useCallback(
    (value) => setParam({ q: value || null }, { replace: true }),
    [setParam],
  );

  // What is in the box right now, applied to the search a moment after the
  // typing stops. Applied on every keystroke, each letter reloaded the page:
  // typing "Mauser" sent over fifty requests in a couple of seconds, and the
  // proxy's per-visitor limit answered the rest with 429.
  const [typed, setTyped] = useState(search);
  useEffect(() => setTyped(search), [search]);
  useEffect(() => {
    if (typed === search) return undefined;
    const timer = setTimeout(() => setSearch(typed), SEARCH_PAUSE_MS);
    return () => clearTimeout(timer);
  }, [typed, search, setSearch]);

  // The sort, written as "key" or "-key". A sort is a deliberate act, so it
  // pushes -- and because each history entry now carries its own, arriving by
  // Back restores the sort that entry had rather than whatever the last click
  // left behind. That is what the [tab] effect below used to paper over.
  const sort = useMemo(() => parseSort(location.search), [location.search]);

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
  const [kinds, setKinds] = useState([]);
  //: Suggestions for the model form's country box, from the same list the
  //: classifier reads titles with -- so a model and a title that mean the same
  //: country write it the same way.
  const [countries, setCountries] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);

  const [selected, setSelected] = useState(() => new Set());
  // The bulk delete asks first, in the bar itself. Any change to the selection
  // takes the question back, so it can never apply to rows it did not name.
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  useEffect(() => setConfirmingDelete(false), [selected, tab]);
  const [editing, setEditing] = useState(null);
  const [merging, setMerging] = useState(null);
  // The row whose primary name is being chosen. Its own state rather than a
  // panel inside the edit dialog: it is a write with side effects of its own
  // (listings get restamped) and must not ride along with Save.
  const [renaming, setRenaming] = useState(null);
  // The row the trashcan was pressed on. Confirmed rather than done, because
  // for most rows deleting is not what the operator means — see comesBack().
  const [deleting, setDeleting] = useState(null);
  const [formError, setFormError] = useState("");
  const [message, setMessage] = useState("");
  // The "Apply shipped armory" dialog: open or not. See ArmoryApply.
  const [applying, setApplying] = useState(false);
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
    // Mentions for a pending row, links for an approved one: the number on
    // screen, whichever it is.
    listings: (row) => row.mention_count ?? row.item_count ?? 0,
    models: (row) =>
      tab === "manufacturers" ? modelsFor(row).length : (row.model_count ?? 0),
    kind: (row) => kinds.find((kind) => kind.value === row.kind)?.label || "",
    country: (row) => row.country || "",
    calibers: (row) => (row.calibers || []).join(", "),
    makers: (row) => (row.manufacturers || []).join(", "),
    aliases: (row) => (row.aliases || "").split("\n").filter(Boolean).join(" · "),
  };

  /** Click a column to sort by it; click the one already sorted to reverse. */
  const sortBy = (key) => {
    // The address bar, not `sort` from the last render -- the same rule `go`
    // and `setTab` follow, and for the same reason. Clicking a header twice
    // reverses and then restores the sort, and if the second click reads a
    // render that has not caught up it computes "descending" again and the
    // sort never comes back. CI caught exactly that: the caliber list stayed
    // on "410 Gauge" when the test expected ".17 HMR" back.
    const current = parseSort(window.location.search);
    const direction = current.key === key && current.direction === "asc" ? "desc" : "asc";
    // The default is spelled by leaving the parameter out, so the plain
    // /armory URL is the plain one and does not grow a ?sort=name on the way
    // back to where it started.
    const isDefault = key === DEFAULT_SORT.key && direction === DEFAULT_SORT.direction;
    setParam({ sort: isDefault ? null : direction === "desc" ? `-${key}` : key });
  };

  const rows = useMemo(() => {
    const read = fromMap(sortValues, sort.key, sortValues.name);
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
   * A counter rather than the effect's `canceled` flag: that only guards the
   * two setters in the effect itself, not the eight inside `load()`, and
   * `load()` is also called directly after every write.
   */
  const loadSeq = useRef(0);
  // A second counter for the filtered lists alone. With one counter, a filter
  // changed while a full load was in flight made the full load stale and
  // dropped *all* of its answer -- including the six unfiltered lists only
  // the full load fetches. The maker drill-down and the merge dropdown then
  // read lists from before the last write: a CI run lost "Colt" from the
  // merge list and the models under an expanded maker that way.
  const filterSeq = useRef(0);

  const load = useCallback(async () => {
    const ticket = ++loadSeq.current;
    const filterTicket = ++filterSeq.current;
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
    // Each half is applied unless something newer has replaced that half: the
    // unfiltered lists only by a newer full load, the filtered ones by any
    // newer load of them.
    if (ticket === loadSeq.current) {
      setAllModels(everyModel);
      setAllCalibers(everyCaliber);
      setAllMakers(everyMaker);
      setKinds(kindRows);
      setCountries(countryNames);
      setSummary(counts);
    }
    if (filterTicket === filterSeq.current) {
      setModels(modelRows);
      setCalibers(caliberRows);
      setMakers(makerRows);
      setSelected(new Set());
    }
  }, [statusFilter, search]);

  /**
   * Only what a filter changes: the three filtered lists. The six unfiltered
   * ones (every model, caliber and maker, the kinds, the countries, the
   * counts) do not depend on the search or the Showing filter, and fetching
   * them again on every change was two thirds of what each keystroke cost.
   * They are read by `load()`, on arrival and after every write.
   */
  const loadFiltered = useCallback(async () => {
    const ticket = ++filterSeq.current;
    const filters = {};
    if (statusFilter) filters.status = statusFilter;
    if (search.trim()) filters.search = search.trim();
    const [modelRows, caliberRows, makerRows] = await Promise.all([
      api.armoryModels(filters),
      api.armoryCalibers(filters),
      api.manufacturers(filters),
    ]);
    if (ticket !== filterSeq.current) return;
    setModels(modelRows);
    setCalibers(caliberRows);
    setMakers(makerRows);
    setSelected(new Set());
  }, [statusFilter, search]);
  const loadedOnce = useRef(false);

  // Whatever moved the tab — a click, Back, Forward, or a pasted link. The
  // sort is no longer reset here: it lives in the URL, so each history entry
  // carries the one that belongs to it and Back restores that rather than
  // whatever the last click left. The selection is not URL state and does
  // still have to be dropped.
  useEffect(() => {
    setSelected(new Set());
  }, [tab]);

  // The Wikipedia suggestions, loaded here rather than by their tab so the tab
  // can say how many are waiting.
  const [proposals, setProposals] = useState([]);
  const [proposalError, setProposalError] = useState("");
  const loadProposals = useCallback(() => {
    api
      .referenceProposals()
      .then((found) => {
        setProposals(found);
        setProposalError("");
      })
      .catch((err) => setProposalError(err.message));
  }, []);
  useEffect(loadProposals, [loadProposals]);
  // Showing on the link tabs: "merged" has no meaning there and reads as
  // rejected, like "disabled".
  const makerPageView = statusFilter === "merged" ? "disabled" : statusFilter;
  // Every production row that could carry a link of one kind, for ReferenceLinks.
  const linkRows = (field) => {
    const approved = (list) => list.filter((row) => row.status === "approved");
    const guns = approved(allModels).map((m) => ({
      key: `model-${m.id}`,
      table: "models",
      type: "Model",
      id: m.id,
      name: m.name,
      makers: m.manufacturers,
      url: field === "maker_page" ? m.maker_url : m.wikipedia_url,
    }));
    if (field === "maker_page") return guns;
    return [
      ...approved(allMakers).map((m) => ({
        key: `manufacturer-${m.id}`,
        table: "manufacturers",
        type: "Manufacturer",
        id: m.id,
        name: m.name,
        url: m.wikipedia_url,
      })),
      ...guns,
      ...approved(allCalibers).map((c) => ({
        key: `caliber-${c.id}`,
        table: "calibers",
        type: "Caliber",
        id: c.id,
        name: c.name,
        url: c.wikipedia_url,
      })),
    ];
  };
  // How many variants are waiting, for the Variants tab's label: fetched on
  // arrival and again after the tab approves or switches any off.
  const [variantsWaiting, setVariantsWaiting] = useState(0);
  const countVariants = useCallback(() => {
    api
      .armoryVariants({ status: "pending" })
      .then((pending) => setVariantsWaiting(pending.length))
      .catch(() => {});
  }, []);
  useEffect(() => {
    countVariants();
  }, [countVariants]);
  // How many of each kind are waiting, for the tabs' labels.
  const waiting = useMemo(() => {
    const counts = {};
    for (const row of proposals) {
      const field = row.field || "wikipedia";
      counts[field] = (counts[field] || 0) + 1;
    }
    return counts;
  }, [proposals]);

  // Everything on arrival; after that a changed filter reloads only what it
  // filters.
  useEffect(() => {
    let canceled = false;
    setLoading(true);
    (loadedOnce.current ? loadFiltered() : load())
      .then(() => {
        loadedOnce.current = true;
      })
      .catch((error) => !canceled && setFailure(error.message))
      .finally(() => !canceled && setLoading(false));
    return () => {
      canceled = true;
    };
  }, [load, loadFiltered]);

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

  // **A page of rows at a time.** The shipped armory is about two thousand
  // rows, and rendering every model at once -- 1,294 of them awaiting approval
  // after a load -- cost two seconds a view and seventeen to select the lot.
  // Only the table is paged: the selection, the counts and "Select everything
  // listed" still mean every row the filter and search admit.
  const [page, setPage] = useState(0);
  useEffect(() => {
    setPage(0);
  }, [tab, statusFilter, search, sort.key, sort.direction]);
  const pageCount = Math.max(1, Math.ceil(rows.length / ARMORY_PAGE));
  // Clamped rather than reset, so deleting the last row of the last page
  // lands on the page before it instead of on nothing.
  const currentPage = Math.min(page, pageCount - 1);
  const shown = rows.slice(currentPage * ARMORY_PAGE, (currentPage + 1) * ARMORY_PAGE);
  const pager =
    pageCount > 1 ? (
      <div className="pagination armory-pager">
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          disabled={currentPage === 0}
          onClick={() => setPage(currentPage - 1)}
        >
          <ChevronLeft size={16} />
          Previous
        </button>
        <span className="pagination__status">
          {(currentPage * ARMORY_PAGE + 1).toLocaleString()}–
          {Math.min(rows.length, (currentPage + 1) * ARMORY_PAGE).toLocaleString()} of{" "}
          {rows.length.toLocaleString()}
        </span>
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          disabled={currentPage >= pageCount - 1}
          onClick={() => setPage(currentPage + 1)}
        >
          Next
          <ChevronRight size={16} />
        </button>
      </div>
    ) : null;

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
   * worked. The counts come back per batch and are added up, and the message
   * still says what was done with them -- "206 row(s) moved" alone did not say
   * where. */
  const inBatches = async (send, done) => {
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
          ? `${changed} row(s) ${done}, in ${Math.ceil(ids.length / BATCH)} batches.`
          : last,
    };
  };

  /**
   * How many listings an edit moved, said out loud.
   *
   * An armory edit is not confined to the row it touches: approving a model,
   * or adding an alias to a cartridge, re-matches every listing whose text
   * mentions any of the spellings involved. That is the whole point of the
   * table — and it is also several hundred listings changing while the admin
   * is looking at one dialog, with nothing on screen to say so.
   */
  const reportEdit = (name, changed) =>
    setMessage(
      `Saved ${name}.` +
        (changed
          ? ` ${changed.toLocaleString()} listing(s) re-matched.`
          : " No listing changed."),
    );

  const save = async (payload) => {
    setFormError("");
    try {
      const name = payload?.name ?? editing?.name ?? SINGULAR[tab];
      if (tab === "manufacturers") {
        // The makers keep their own endpoint: an edit there re-derives the
        // listings it can reach and reports how many, which is a different
        // shape of answer from the armory's own writes.
        const result = editing?.id
          ? await api.updateManufacturer(editing.id, payload)
          : await api.createManufacturer(payload);
        reportEdit(name, result?.listings_changed ?? 0);
      } else if (editing?.id) {
        const result = await api.updateArmoryRow(tab, editing.id, payload);
        reportEdit(name, result?.listings_changed ?? 0);
      } else {
        // A create matches nothing yet — it is pending, and a pending row
        // decides nothing until it is promoted. Saying "0 re-matched" there
        // would read as a failure rather than as the gate working.
        await api.createArmoryRow(tab, payload);
        setMessage(`Added ${name}. It is awaiting approval and decides nothing yet.`);
      }
      // Reload first, close second. Closed while the reload was in flight, the
      // list still held the row as it was before the save, and opening it
      // again at once showed the old values -- the marks test caught that.
      await load();
      setEditing(null);
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
      filterSeq.current += 1;
      setAllCalibers((prev) =>
        [...prev, created].sort((a, b) => compareCalibers(a.name, b.name)),
      );
      return created;
    } catch (problem) {
      setFormError(problem.message);
      return null;
    }
  };

  /** Open the model dialog with this maker already checked. */
  const addModelFor = (maker) => {
    setFormError("");
    setTab("models");
    setEditing({ _makerId: maker.id });
  };

  // Undo a merge. Only ever offered on a row that has one: the button is
  // hidden otherwise, because "un-merge" on a row that was never merged reads
  // as a second kind of delete.
  async function runUnmerge(table, row) {
    setFormError("");
    try {
      const result = await api.unmergeArmoryRow(table, row.id);
      setMessage(result.message);
      await load();
    } catch (error) {
      setMessage(`Could not un-merge ${row.name}: ${error.message}`);
    }
  }

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
          {/* Getting what you curate here back into the repository. The armory
              is edited on a running instance and shipped from a file in the
              source tree, so the two drift the moment somebody approves a
              model — and until now the only way back was a shell on the
              server, which an administrator using these pages does not have. */}
          <a
            className="btn btn--secondary"
            href={api.armoryExportUrl()}
            download="armory.yaml"
          >
            <Download /> Download armory
          </a>
          <button
            type="button"
            className="btn btn--secondary"
            disabled={busy}
            title="Send it to your own address, with what to do with it"
            onClick={() => act(() => api.emailArmoryExport())}
          >
            <Mail /> Email it to me
          </button>
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
            className="btn btn--secondary"
            disabled={busy}
            title="Make this armory match the shipped file: shows every change first"
            onClick={() => setApplying(true)}
          >
            <Refresh /> Apply shipped armory…
          </button>
          {!SUGGESTION_FIELD[tab] && (
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
          )}
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
              value={
                SUGGESTION_FIELD[tab] || tab === "variants" ? makerPageView : statusFilter
              }
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              {(tab === "variants"
                ? VARIANT_VIEWS
                : SUGGESTION_FIELD[tab]
                  ? LINK_VIEWS
                  : STATUSES
              ).map((entry) => (
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
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
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
            onClick={() => setTab(entry.key)}
          >
            {entry.label}
            {SUGGESTION_FIELD[entry.key] &&
              waiting[SUGGESTION_FIELD[entry.key]] > 0 &&
              ` (${waiting[SUGGESTION_FIELD[entry.key]]})`}
            {entry.key === "variants" && variantsWaiting > 0 && ` (${variantsWaiting})`}
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
              act(() =>
                inBatches(
                  (some) => api.promoteArmoryRows(tab, some),
                  "promoted to production",
                ),
              )
            }
          >
            Promote to production
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            disabled={busy}
            onClick={() =>
              act(() =>
                inBatches(
                  (some) => api.sendArmoryRowsBack(tab, some),
                  "sent back for approval",
                ),
              )
            }
          >
            Send back for approval
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            disabled={busy}
            title="Out of matching and out of the queue, but kept, so a scan does not propose these names again"
            onClick={() =>
              act(() => inBatches((some) => api.disableArmoryRows(tab, some), "disabled"))
            }
          >
            Switch off
          </button>
          {confirmingDelete ? (
            <span
              className="armory-bulk__confirm"
              role="group"
              aria-label="Confirm delete"
            >
              <span>
                Delete {countLabel(ids.length, "row", "rows")}? A deleted name a scan
                proposed can be proposed again; Switch off keeps it out.
              </span>
              <button
                type="button"
                className="btn btn--danger btn--sm"
                disabled={busy}
                onClick={() =>
                  act(() =>
                    inBatches((some) => api.deleteArmoryRows(tab, some), "deleted"),
                  )
                }
              >
                Delete {countLabel(ids.length, "row", "rows")}
              </button>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={busy}
                onClick={() => setConfirmingDelete(false)}
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              type="button"
              className="btn btn--danger btn--sm"
              disabled={busy}
              onClick={() => setConfirmingDelete(true)}
            >
              Delete…
            </button>
          )}
        </div>
      )}

      {/* How many rows the table holds, as the link tabs say theirs (asked
          for on 2026-10-14): every row the Showing filter and the search
          admit, not just the page on screen. */}
      {!SUGGESTION_FIELD[tab] && tab !== "variants" && (
        <h2 className="armory-count" data-testid="armory-count">
          {TAB_NOUNS[tab]} {SHOWING_PHRASES[statusFilter] ?? "in the armory"}
          {search.trim() && <> matching “{search.trim()}”</>} (
          {loading && rows.length === 0 ? "…" : rows.length.toLocaleString()})
        </h2>
      )}
      {tab === "variants" ? (
        <VariantsTab view={makerPageView} search={search} onChanged={countVariants} />
      ) : SUGGESTION_FIELD[tab] ? (
        <ReferenceLinks
          key={tab}
          field={SUGGESTION_FIELD[tab]}
          view={makerPageView}
          search={search}
          pending={proposals.filter(
            (row) => (row.field || "wikipedia") === SUGGESTION_FIELD[tab],
          )}
          rows={linkRows(SUGGESTION_FIELD[tab])}
          failure={proposalError}
          onChanged={() => {
            loadProposals();
            load();
          }}
        />
      ) : tab === "manufacturers" ? (
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
                <th aria-label="Actions" className="table__actions" />
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
                shown.map((maker) => {
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
                          {maker.merged_into && (
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm"
                              title={`Bring ${maker.name} back and make ${maker.merged_into} give its spellings back`}
                              onClick={() => runUnmerge("manufacturers", maker)}
                            >
                              Un-merge
                            </button>
                          )}
                          <Link
                            className="btn btn--ghost btn--sm"
                            to={listingsHref("manufacturers", maker)}
                            aria-label={`View listings for ${maker.name}`}
                            title="Show every listing this manufacturer accounts for"
                          >
                            <Eye />
                          </Link>
                          {/*
                            This tab had no delete at all, while models and
                            calibers have had one throughout — so a maker
                            proposed by a scan and plainly wrong could only be
                            merged into something or left in the queue forever.
                            Merging is the wrong tool for that: it moves the
                            junk spelling onto the target as a live matching
                            rule, and "PD Trade" is in 228 titles.
                          */}
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            aria-label={`Delete ${maker.name}`}
                            title="Delete, or disable — deleting a name a scan proposed brings it back"
                            onClick={() => {
                              setFormError("");
                              setDeleting(maker);
                            }}
                          >
                            <Trash />
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
                                      also {model.manufacturers.length - 1} other
                                      manufacturer
                                      {model.manufacturers.length > 2 ? "s" : ""}
                                    </span>
                                  )}
                                  {/* The same eyeball the models tab carries.
                                      Deciding whether a maker really built a
                                      model means looking at what the model is
                                      actually holding, and from here the only
                                      route there was to open the row, read its
                                      name, switch tabs and find it again. */}
                                  <Link
                                    className="btn btn--ghost btn--sm armory-drilldown__view"
                                    to={listingsHref("models", model)}
                                    aria-label={`View listings for ${model.name}`}
                                    title={`Show every listing ${model.name} accounts for`}
                                  >
                                    <Eye />
                                  </Link>
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
          {pager}
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
                {/*
                  The makers tab has had this since it existed and the models
                  tab was the one place it was missing, which made "is this row
                  worth filling in?" the question the page could not answer.
                  Calibers carry theirs in the second column already.
                */}
                {tab === "models" && (
                  <SortHeader
                    label="Listings"
                    sortKey="listings"
                    sort={sort}
                    onSort={sortBy}
                  />
                )}
                <SortHeader label="Status" sortKey="status" sort={sort} onSort={sortBy} />
                <th aria-label="Actions" className="table__actions" />
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td colSpan={tab === "models" ? 9 : 6} className="loading-row">
                    <span className="spinner" /> Loading…
                  </td>
                </tr>
              )}
              {!loading &&
                shown.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.has(row.id)}
                        onChange={() => toggle(row.id)}
                        aria-label={`Select ${row.name}`}
                      />
                    </td>
                    {/* The listing that first proposed this row, as a tooltip.
                        It used to hang off the "Also written as" cell, which no
                        longer exists -- and hanging it off the aliases text
                        instead would lose it on every row that has none. It is
                        a fact about the row, so it belongs on the row's name. */}
                    <td title={row.first_seen_in || undefined}>
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
                      {row.modern_production && (
                        <span className="chip chip--info">Still made</span>
                      )}
                      {row.merged_into && (
                        <span className="chip chip--neutral">→ {row.merged_into}</span>
                      )}
                      {/* Calibers got this switch in migration 0018; models
                          always had it. Shown here for both, the way the
                          makers tab has always shown it. */}
                      {row.enabled === false && (
                        <span className="chip chip--neutral">disabled</span>
                      )}
                      {/* The other spellings, under the name rather than in a
                          column of their own. They were the widest column on
                          the page -- 182px of a 1114px table -- and the models
                          tab overflowed its container only when they happened
                          to be long, which made the horizontal scroll appear
                          and disappear with the data. They belong here anyway:
                          "M91/30" is a way of writing "Mosin-Nagant M91/30",
                          not a separate fact about it. */}
                      {(row.aliases || "").split("\n").filter(Boolean).length > 0 && (
                        <span className="armory-aliases">
                          {(row.aliases || "").split("\n").filter(Boolean).join(" · ")}
                        </span>
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
                    {tab === "models" && (
                      <td>
                        <ListingsCell row={row} />
                      </td>
                    )}
                    <td>{statusChip(row.status)}</td>
                    <td className="table__actions">
                      {tab === "calibers" && <AmmunitionButton caliber={row.name} />}
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
                      {row.merged_into && (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          title={`Bring ${row.name} back and make ${row.merged_into} give its spellings back`}
                          onClick={() => runUnmerge(tab, row)}
                        >
                          Un-merge
                        </button>
                      )}
                      <Link
                        className="btn btn--ghost btn--sm"
                        to={listingsHref(tab, row)}
                        aria-label={`View listings for ${row.name}`}
                        title={
                          row.mention_count != null
                            ? `Show every listing that names ${row.name}`
                            : `Show every listing this ${
                                tab === "models" ? "model" : "caliber"
                              } accounts for`
                        }
                      >
                        <Eye />
                      </Link>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        aria-label={`Delete ${row.name}`}
                        onClick={() => {
                          setFormError("");
                          setDeleting(row);
                        }}
                      >
                        <Trash />
                      </button>
                    </td>
                  </tr>
                ))}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={tab === "models" ? 9 : 6} className="loading-row">
                    Nothing here. “Load shipped armory” brings in the starting list, and
                    scans add what they meet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {pager}
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
          {/*
            Above the form, not inside it, because it is not one of the fields
            and must not ride along with Save: it renames the row, keeps the
            old name as an alias and restamps every listing carrying it. One
            button here covers all three tabs, which is the other reason it is
            not repeated in each of the three forms.

            Shown only when there is something to choose between. The Name
            field below is still the way to correct a spelling; this is the way
            to change which spelling is the answer.
          */}
          {editing.id && (editing.aliases || "").trim() && (
            <div className="armory-primary-swap">
              <div>
                <strong>Primary name:</strong> {editing.name}
              </div>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                onClick={() => {
                  setFormError("");
                  setRenaming(editing);
                }}
              >
                Change…
              </button>
            </div>
          )}
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
          {tab === "models" && editing.id && (
            <VariantsEditor model={editing} calibers={allCalibers} />
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
              countries={countries}
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

      {applying && (
        <ArmoryApply
          onClose={() => setApplying(false)}
          onApplied={async (result) => {
            setApplying(false);
            setMessage(result.message);
            await load();
          }}
        />
      )}

      {deleting && (
        <Modal
          title={`Delete ${deleting.name}?`}
          onClose={() => {
            setDeleting(null);
            setFormError("");
          }}
        >
          <DeleteForm
            row={deleting}
            // Calibers gained this switch in migration 0018; before that,
            // sending the row back for approval was the only durable "no".
            canDisable={"enabled" in deleting}
            error={formError}
            onDelete={async () => {
              setFormError("");
              try {
                const removed = deleting;
                if (tab === "manufacturers") {
                  const result = await api.deleteManufacturer(removed.id);
                  const moved = result?.listings_changed ?? 0;
                  setMessage(
                    `Deleted ${removed.name}.` +
                      (moved ? ` ${moved} listing(s) re-derived.` : ""),
                  );
                } else {
                  const result = await api.deleteArmoryRow(tab, removed.id);
                  const moved = result?.listings_changed ?? 0;
                  setMessage(
                    `Deleted ${removed.name}.` +
                      (moved ? ` ${moved.toLocaleString()} listing(s) re-matched.` : ""),
                  );
                }
                setDeleting(null);
                await load();
              } catch (error) {
                setFormError(error.message);
              }
            }}
            onDisable={async () => {
              setFormError("");
              try {
                const row = deleting;
                if ("enabled" in row) {
                  // Switching a row off is the edit most likely to move
                  // listings in bulk: everything it used to explain stops
                  // being explained by it, which is the number worth saying.
                  const result = await (tab === "manufacturers"
                    ? api.updateManufacturer(row.id, { enabled: false })
                    : api.updateArmoryRow(tab, row.id, { enabled: false }));
                  const moved = result?.listings_changed ?? 0;
                  setMessage(
                    `${row.name} is off. It matches nothing and will not be proposed.` +
                      (moved ? ` ${moved.toLocaleString()} listing(s) re-matched.` : ""),
                  );
                } else {
                  await api.sendArmoryRowsBack(tab, [row.id]);
                  setMessage(
                    `${row.name} is back to awaiting approval. It matches nothing ` +
                      `and will not be proposed.`,
                  );
                }
                setDeleting(null);
                await load();
              } catch (error) {
                setFormError(error.message);
              }
            }}
          />
        </Modal>
      )}

      {renaming && (
        <Modal
          title={`Primary name for ${renaming.name}`}
          onClose={() => {
            setRenaming(null);
            setFormError("");
          }}
        >
          <PrimaryNameForm
            row={renaming}
            table={tab}
            error={formError}
            onSubmit={async (name) => {
              setFormError("");
              try {
                const result = await api.setArmoryPrimary(tab, renaming.id, name);
                setRenaming(null);
                setEditing(null);
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
