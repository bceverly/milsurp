/**
 * Saved searches: the list, and the email settings for each.
 *
 * A saved search is the browse page's own query under a name, so "Run" is a
 * link to `/?<query>` and nothing more — there is no second search
 * implementation here to drift from the first one.
 *
 * The email is per search and capped by its owner. **The cap is on the email
 * alone**: running a search shows everything it matches, which is why the card
 * reports the full match count beside a limit that is usually smaller.
 *
 * **A want list is a saved search with the instant alert on.** Its price
 * ceiling is the target, and each listing that comes to match it -- new,
 * reduced into range, back in stock -- is mailed and pushed once, straight
 * away rather than in the digest. See services/wantlist.py.
 */
import { barrelText } from "../components/BarrelFilter.jsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatMoney, formatRelative, timeTitle } from "../format.js";
import { Bell, Bookmark, Mail, Refresh, Trash } from "../components/Icons.jsx";
import { fromMap } from "../lookup";
import ArmoryInput from "../components/ArmoryInput.jsx";
import Field from "../components/Field.jsx";

/** What the email-limit dropdown offers; mirrors SAVED_SEARCH_LIMITS. */
const LIMITS = [5, 10, 20, 30, 50, 100];

const SORT_LABELS = {
  newest: "Newest first",
  oldest: "Oldest first",
  price_asc: "Price: low to high",
  price_desc: "Price: high to low",
  price_drop: "Recently reduced",
  title: "Title A–Z",
};

/** The collector details and condition grades, as the browse rail names them. */
const TRAIT_LABELS = {
  unmarked: "No import marks",
  import_marked: "Import marked",
  all_matching: "All matching",
  not_matching: "Not all matching",
  original_finish: "Original finish",
  refinished: "Refinished",
};
const GRADE_LABELS = {
  like_new: "Like new",
  excellent: "Excellent",
  very_good: "Very good",
  good: "Good",
  fair: "Fair",
  poor: "Poor",
  Unknown: "Not stated",
};

/** The filters in a stored query, as something a person can read. */
function describe(query) {
  const params = new URLSearchParams(query || "");
  const parts = [];
  const named = (key, label) => {
    const values = params.getAll(key);
    if (values.length) parts.push(`${label}: ${values.join(", ")}`);
  };
  if (params.get("search")) parts.push(`“${params.get("search")}”`);
  named("kind", "Type");
  named("caliber", "Caliber");
  named("country", "Country");
  named("manufacturer", "Manufacturer");
  named("category", "Category");
  const labeled = (key, label, words) => {
    const values = params.getAll(key);
    if (values.length)
      parts.push(`${label}: ${values.map((v) => words[v] || v).join(", ")}`);
  };
  labeled("grade", "Condition", GRADE_LABELS);
  labeled("trait", "Details", TRAIT_LABELS);
  if (params.get("min_price") || params.get("max_price")) {
    parts.push(
      `Price: ${params.get("min_price") || "any"}–${params.get("max_price") || "any"}`,
    );
  }
  if (params.get("barrel_min") || params.get("barrel_max")) {
    const text = barrelText(
      params.get("barrel_min") ? Number(params.get("barrel_min")) : null,
      params.get("barrel_max") ? Number(params.get("barrel_max")) : null,
    );
    parts.push(`Barrel: ${text}"`);
  }
  if (params.get("threaded") === "yes") parts.push("Threaded barrel");
  if (params.get("threaded") === "no") parts.push("Barrel not threaded");
  if (params.get("price_drops_only") === "true") parts.push("Price reduced");
  if (params.get("guns_only") === "true") parts.push("Priced guns only");
  const availability = params.get("availability");
  if (availability && availability !== "available")
    parts.push(`Availability: ${availability}`);
  return parts.length ? parts.join(" · ") : "Everything";
}

function SavedSearchCard({ search, onChange, onDelete }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(null);

  /**
   * Apply the change locally first, then reconcile with what the server says.
   *
   * A checkbox that does not move until a round-trip has finished reads as
   * broken — and disabling it for the duration makes a second click land on a
   * disabled control. Reverted on failure, with the error shown, so an
   * optimistic update is never left standing as a lie.
   */
  async function patch(body) {
    const before = search;
    setBusy(true);
    setError(null);
    onChange({ ...search, ...body });
    try {
      onChange(await api.updateSavedSearch(search.id, body));
    } catch (problem) {
      onChange(before);
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  /**
   * Mail this one search now.
   *
   * Not gated on the email toggle: "send this every day" and "send it to me
   * now" are different questions, and seeing what a search would mail before
   * turning the daily one on is most of the point. A search matching nothing
   * comes back as an error here rather than as an empty email.
   */
  async function sendNow() {
    setSending(true);
    setSent(null);
    setError(null);
    try {
      const result = await api.sendSavedSearch(search.id);
      setSent(result.message);
      // The server stamps last_emailed_at; show it without a round trip.
      onChange({ ...search, last_emailed_at: new Date().toISOString() });
    } catch (problem) {
      setError(problem.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <article className="saved-search">
      <div className="saved-search__head">
        <h2 className="saved-search__name">{search.name}</h2>
        <span className="saved-search__count">
          {search.match_count} {search.match_count === 1 ? "match" : "matches"}
        </span>
      </div>

      <p className="saved-search__filters">{describe(search.query)}</p>
      <p className="saved-search__sort">
        Sorted by {fromMap(SORT_LABELS, search.sort, search.sort)}
      </p>

      <div className="saved-search__controls">
        {/* A link, not a fetch: running a saved search is the browse page
            doing what it already does. */}
        <Link className="btn btn--primary" to={`/?${search.query}`}>
          Run
        </Link>

        {/* First, because it is the stronger of the two: the digest tells
            you tomorrow, this tells you now. */}
        <label className="saved-search__toggle">
          <input
            type="checkbox"
            checked={Boolean(search.alert_instantly)}
            onChange={(event) => patch({ alert_instantly: event.target.checked })}
          />
          Alert me the moment one appears
        </label>

        <label className="saved-search__toggle">
          <input
            type="checkbox"
            checked={search.email_enabled}
            onChange={(event) => patch({ email_enabled: event.target.checked })}
          />
          Email me these
        </label>

        <label className="visually-hidden" htmlFor={`limit-${search.id}`}>
          How many listings to email for {search.name}
        </label>
        <select
          id={`limit-${search.id}`}
          className="select"
          style={{ width: "auto" }}
          value={search.email_item_limit}
          disabled={!search.email_enabled}
          onChange={(event) => patch({ email_item_limit: Number(event.target.value) })}
        >
          {LIMITS.map((limit) => (
            <option key={limit} value={limit}>
              Up to {limit} in the email
            </option>
          ))}
        </select>

        <button
          type="button"
          className="btn btn--secondary"
          disabled={sending}
          onClick={sendNow}
        >
          <Mail size={15} /> {sending ? "Sending…" : "Send now"}
        </button>

        <button
          type="button"
          className="btn btn--danger"
          disabled={busy}
          onClick={() => onDelete(search)}
          aria-label={`Delete ${search.name}`}
        >
          <Trash size={15} />
        </button>
      </div>

      {search.alert_instantly && (
        <p className="saved-search__note saved-search__note--alert">
          <Bell size={13} /> On your want list
          {search.target_price != null && (
            <> — target {formatMoney(search.target_price)}</>
          )}
          . A new listing, a reduction into range or a return to stock is mailed and
          pushed straight away, once per listing.
          {search.target_price == null && (
            <> Set a top price on the inventory and save again to give it a target.</>
          )}
        </p>
      )}
      {search.email_enabled && search.match_count > search.email_item_limit && (
        <p className="saved-search__note">
          The email carries {search.email_item_limit} of {search.match_count} and links to
          the rest.
        </p>
      )}
      {search.last_emailed_at && (
        <p className="saved-search__note" title={timeTitle(search.last_emailed_at)}>
          Last emailed {formatRelative(search.last_emailed_at)}
        </p>
      )}
      {sent && (
        <p className="alert alert--success" role="status">
          {sent}
        </p>
      )}
      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
    </article>
  );
}

/** The query a from-scratch search stands for, as the browse page writes one. */
export function scratchQuery(form) {
  const params = new URLSearchParams();
  if (form.search.trim()) params.set("search", form.search.trim());
  if (form.manufacturer.trim()) params.set("manufacturer", form.manufacturer.trim());
  if (form.caliber.trim()) params.set("caliber", form.caliber.trim());
  if (form.min_price !== "") params.set("min_price", form.min_price);
  if (form.max_price !== "") params.set("max_price", form.max_price);
  return params.toString();
}

const EMPTY_SCRATCH = {
  name: "",
  search: "",
  manufacturer: "",
  caliber: "",
  min_price: "",
  max_price: "",
  alert_instantly: true,
  email_enabled: false,
};

/**
 * A saved search typed in rather than saved from the inventory's filters.
 *
 * Asked for on 2026-10-15: "I'd really like to find a .32 ACP version of the
 * Bersa Thunder pistol and have the system send me an immediate email alert
 * if one shows up" -- a gun that may be for sale nowhere yet, so there are no
 * filters on the inventory to set. Keywords, a maker and a caliber (offered
 * from the armory as you type, free text still allowed), a price range, and
 * the instant alert on by default: the same search the inventory would save.
 */
function ScratchSearchForm({ onSaved, onCancel }) {
  const [form, setForm] = useState(EMPTY_SCRATCH);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));
  const query = scratchQuery(form);
  const suggested =
    [form.search.trim(), form.caliber.trim()].filter(Boolean).join(" in ") || "";

  async function submit(event) {
    event.preventDefault();
    if (!query) {
      setError("Give it at least one thing to look for.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await api.createSavedSearch({
        name: (form.name.trim() || suggested).slice(0, 80),
        query,
        alert_instantly: form.alert_instantly,
        email_enabled: form.email_enabled,
      });
      onSaved(saved);
    } catch (problem) {
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card scratch-search" onSubmit={submit} data-testid="scratch-search">
      <h2>A search from scratch</h2>
      <p className="muted">
        For a gun that may not be for sale anywhere yet. Every word you give must be in
        the listing; leave out what you do not mind.
      </p>
      <div className="form-row form-row--2">
        <Field label="Keywords" hint="Words in the title or description: Bersa Thunder.">
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              value={form.search}
              maxLength={200}
              onChange={(event) => set("search")(event.target.value)}
            />
          )}
        </Field>
        <Field label="Name" hint={suggested ? `Blank names it “${suggested}”.` : null}>
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              value={form.name}
              maxLength={80}
              onChange={(event) => set("name")(event.target.value)}
            />
          )}
        </Field>
      </div>
      <div className="form-row form-row--2">
        <ArmoryInput
          id="scratch-maker"
          label="Manufacturer"
          value={form.manufacturer}
          maxLength={128}
          lookup={api.collectionMakers}
          onChange={set("manufacturer")}
        />
        <ArmoryInput
          id="scratch-caliber"
          label="Caliber"
          value={form.caliber}
          maxLength={64}
          lookup={api.collectionCalibers}
          onChange={set("caliber")}
        />
      </div>
      <div className="form-row form-row--2">
        <Field label="Lowest price">
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="number"
              min="0"
              step="1"
              value={form.min_price}
              onChange={(event) => set("min_price")(event.target.value)}
            />
          )}
        </Field>
        <Field label="Highest price" hint="With the alert on, this is your target price.">
          {(id, describedBy) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="input"
              type="number"
              min="0"
              step="1"
              value={form.max_price}
              onChange={(event) => set("max_price")(event.target.value)}
            />
          )}
        </Field>
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={form.alert_instantly}
          onChange={(event) => set("alert_instantly")(event.target.checked)}
        />
        <span>Alert me the moment one appears (email and push)</span>
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={form.email_enabled}
          onChange={(event) => set("email_enabled")(event.target.checked)}
        />
        <span>Also list its matches in my email digest</span>
      </label>
      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      <div className="page-head__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          Save search
        </button>
      </div>
    </form>
  );
}

export default function SavedSearches() {
  useTitle("Saved searches");
  const [searches, setSearches] = useState(null);
  const [error, setError] = useState(null);
  const [scratch, setScratch] = useState(false);

  /**
   * The newest `load()` wins, and a local change retires whatever is in
   * flight.
   *
   * Every card here edits the list without a round trip — a delete filters a
   * row out, a toggle replaces one — and a `load()` that started *before* the
   * change knows nothing about it. Let its answer land last and the row comes
   * back: deleting the final saved search left the list still showing it, and
   * the empty state never appeared. Only reliably on a slow machine, which is
   * where CI found it.
   *
   * The page's mount fires that `load()`, so the window is exactly as long as
   * the first request takes. Same fix as the armory page, for the same reason.
   */
  const loadSeq = useRef(0);

  /** A local edit is newer than any fetch already outstanding. */
  const supersedeLoad = () => {
    loadSeq.current += 1;
  };

  const load = useCallback(async () => {
    const ticket = ++loadSeq.current;
    setError(null);
    try {
      const rows = await api.savedSearches();
      if (ticket === loadSeq.current) setSearches(rows);
    } catch (problem) {
      if (ticket === loadSeq.current) setError(problem.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function remove(search) {
    await api.deleteSavedSearch(search.id);
    supersedeLoad();
    setSearches((rows) => (rows || []).filter((row) => row.id !== search.id));
  }

  function replace(updated) {
    supersedeLoad();
    setSearches((rows) =>
      (rows || []).map((row) => (row.id === updated.id ? updated : row)),
    );
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Saved searches</h1>
          <p>
            A named set of browse filters. Turn on the email and its results ride in your
            digest, in the order the search was saved with. Turn on the alert and it
            becomes a want list: you hear the moment something new matches, with the top
            of its price range as your target.
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--primary" onClick={() => setScratch(true)}>
            <Bell size={15} /> New search from scratch
          </button>
          <button className="btn btn--secondary" onClick={load}>
            <Refresh size={15} /> Refresh
          </button>
        </div>
      </div>

      {scratch && (
        <ScratchSearchForm
          onCancel={() => setScratch(false)}
          onSaved={(saved) => {
            supersedeLoad();
            setSearches((rows) => [saved, ...(rows || [])]);
            setScratch(false);
          }}
        />
      )}

      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}

      {searches === null && !error && <p className="muted">Loading…</p>}

      {searches !== null && searches.length === 0 && (
        <div className="empty">
          <Bookmark size={28} />
          <h3>No saved searches yet</h3>
          <p>
            Set up the filters you want on the <Link to="/">inventory</Link>, then choose
            “Save this search” — or describe the gun from scratch above.
          </p>
        </div>
      )}

      <div className="saved-search-list">
        {(searches || []).map((search) => (
          <SavedSearchCard
            key={search.id}
            search={search}
            onChange={replace}
            onDelete={remove}
          />
        ))}
      </div>
    </section>
  );
}
