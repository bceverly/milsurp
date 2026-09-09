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
 */
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatRelative, timeTitle } from "../format.js";
import { Bookmark, Mail, Refresh, Trash } from "../components/Icons.jsx";

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
  named("manufacturer", "Maker");
  named("category", "Category");
  if (params.get("min_price") || params.get("max_price")) {
    parts.push(
      `Price: ${params.get("min_price") || "any"}–${params.get("max_price") || "any"}`,
    );
  }
  if (params.get("price_drops_only") === "true") parts.push("Price reduced");
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
        Sorted by {SORT_LABELS[search.sort] || search.sort}
      </p>

      <div className="saved-search__controls">
        {/* A link, not a fetch: running a saved search is the browse page
            doing what it already does. */}
        <Link className="btn btn--primary" to={`/?${search.query}`}>
          Run
        </Link>

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

export default function SavedSearches() {
  useTitle("Saved searches");
  const [searches, setSearches] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setSearches(await api.savedSearches());
    } catch (problem) {
      setError(problem.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function remove(search) {
    await api.deleteSavedSearch(search.id);
    setSearches((rows) => rows.filter((row) => row.id !== search.id));
  }

  function replace(updated) {
    setSearches((rows) => rows.map((row) => (row.id === updated.id ? updated : row)));
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Saved searches</h1>
          <p>
            A named set of browse filters. Turn on the email and its results ride in your
            digest, in the order the search was saved with.
          </p>
        </div>
        <button className="btn btn--secondary" onClick={load}>
          <Refresh size={15} /> Refresh
        </button>
      </div>

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
            “Save this search”.
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
