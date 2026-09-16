/**
 * A week in review of the catalog.
 *
 * Deliberately not the email digest. That one is a shopping list — each
 * person's sites, each person's price floor, capped so it fits in a preview
 * pane. This is the other question, *what happened to the catalog*, and it is
 * the same answer for everybody, which is why it is a page rather than a
 * message.
 *
 * Three things here are not in the digest and are the reason the page exists:
 * what **left**, which shops were **quiet**, and what the catalog **learned**.
 * The quiet shops matter most — a site that produced nothing all week is
 * either a slow vendor or a broken scraper, and nothing else in the
 * application puts those two side by side and makes you look at them.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatDate, formatMoney, formatRelative, timeTitle } from "../format.js";
import { External, Refresh, Warning } from "../components/Icons.jsx";

/** The windows worth offering. A year of this is a report, not a page. */
const WINDOWS = [
  { days: 7, label: "7 days" },
  { days: 14, label: "14 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

function Stat({ label, value, hint }) {
  return (
    <div className="week-stat">
      <span className="week-stat__value">{value}</span>
      <span className="week-stat__label">{label}</span>
      {hint && <span className="week-stat__hint">{hint}</span>}
    </div>
  );
}

function HighlightList({ rows, empty, showDrop }) {
  if (!rows.length) {
    return <p className="week-empty">{empty}</p>;
  }
  return (
    <ul className="week-list">
      {rows.map((row) => (
        <li key={row.item_id}>
          <Link to={`/items/${row.item_id}`} className="week-list__title">
            {row.title}
          </Link>
          <span className="week-list__meta">
            {row.site_name}
            {showDrop && row.drop != null ? (
              <>
                {" · "}
                <strong>−{formatMoney(row.drop, row.currency)}</strong>
                {row.drop_percent != null && ` (${row.drop_percent}%)`}
                {" · now "}
                {formatMoney(row.price, row.currency)}
              </>
            ) : (
              row.price != null && ` · ${formatMoney(row.price, row.currency)}`
            )}
          </span>
          <a
            href={row.url}
            target="_blank"
            rel="noreferrer noopener"
            className="week-list__out"
            title="Open at the vendor"
          >
            <External size={14} />
          </a>
        </li>
      ))}
    </ul>
  );
}

/** A list of values the catalog has not carried before. */
function Learned({ title, values, filter }) {
  if (!values.length) return null;
  return (
    <div className="week-learned">
      <h3>{title}</h3>
      <div className="week-learned__values">
        {values.map((value) => (
          <Link
            key={value}
            to={`/?${filter}=${encodeURIComponent(value)}`}
            className="chip"
          >
            {value}
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function Changes() {
  useTitle("What changed");
  const [days, setDays] = useState(7);
  const [week, setWeek] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setWeek(null);
    setError(null);
    try {
      setWeek(await api.changes({ days }));
    } catch (err) {
      setError(err.message);
    }
  }, [days]);

  useEffect(() => {
    load();
  }, [load]);

  const silent = week ? week.sites.filter((site) => site.silent && site.enabled) : [];
  const failing = week ? week.sites.filter((site) => site.failed_scans > 0) : [];

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>What changed</h1>
          <p>
            Every site, the whole catalog, nobody&rsquo;s filters. The email digest
            answers what <em>you</em> asked for; this answers what happened.
          </p>
        </div>
        <div className="page-head__actions">
          <label className="field" style={{ margin: 0 }}>
            <span className="field__label">Window</span>
            <select
              className="select"
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              {WINDOWS.map((entry) => (
                <option key={entry.days} value={entry.days}>
                  {entry.label}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn--secondary" onClick={load}>
            <Refresh size={16} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}

      {!week && !error && (
        <div className="loading-row" style={{ padding: 20 }}>
          <div className="spinner" />
          Working out what changed…
        </div>
      )}

      {week && (
        <>
          <p className="week-window">
            {formatDate(week.since)} to {formatDate(week.until)}
          </p>

          <div className="week-stats">
            <Stat label="arrived" value={week.added.toLocaleString()} />
            <Stat label="sold" value={week.sold.toLocaleString()} />
            <Stat label="taken down" value={week.delisted.toLocaleString()} />
            <Stat
              label="reduced"
              value={week.reduced.toLocaleString()}
              hint={
                week.total_reduction > 0
                  ? `${formatMoney(week.total_reduction)} off in total`
                  : null
              }
            />
            <Stat label="listed now" value={week.active_now.toLocaleString()} />
          </div>

          {(silent.length > 0 || failing.length > 0) && (
            <div className="alert alert--warning">
              <p style={{ margin: 0 }}>
                <Warning size={15} />{" "}
                {failing.length > 0 && (
                  <>
                    <strong>{failing.length}</strong>{" "}
                    {failing.length === 1 ? "site has" : "sites have"} a failed scan in
                    this window.{" "}
                  </>
                )}
                {silent.length > 0 && (
                  <>
                    <strong>{silent.length}</strong>{" "}
                    {silent.length === 1 ? "site is" : "sites are"} enabled and reported
                    nothing at all. That is a quiet vendor or a broken scraper, and the
                    two only tell apart by looking.
                  </>
                )}
              </p>
            </div>
          )}

          <div className="panel">
            <div className="panel__head">
              <h2>By site</h2>
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Site</th>
                    <th>Arrived</th>
                    <th>Sold</th>
                    <th>Taken down</th>
                    <th>Reduced</th>
                    <th>Listed now</th>
                    <th>Last good scan</th>
                  </tr>
                </thead>
                <tbody>
                  {week.sites.map((site) => (
                    <tr
                      key={site.site_id}
                      className={site.silent ? "week-row--silent" : ""}
                    >
                      <td>
                        <Link to={`/sites/${site.site_id}`}>{site.name}</Link>
                        {!site.enabled && (
                          <span className="chip chip--neutral week-chip">disabled</span>
                        )}
                        {site.failed_scans > 0 && (
                          <span className="chip chip--danger week-chip">
                            {site.failed_scans} failed
                          </span>
                        )}
                      </td>
                      <td>{site.added ? site.added.toLocaleString() : "—"}</td>
                      <td>{site.sold ? site.sold.toLocaleString() : "—"}</td>
                      <td>{site.delisted ? site.delisted.toLocaleString() : "—"}</td>
                      <td>{site.reduced ? site.reduced.toLocaleString() : "—"}</td>
                      <td>{site.active.toLocaleString()}</td>
                      <td title={timeTitle(site.last_success_at)}>
                        {site.last_success_at
                          ? formatRelative(site.last_success_at)
                          : "never"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="week-columns">
            <div className="panel">
              <div className="panel__head">
                <h2>Biggest reductions</h2>
              </div>
              <HighlightList
                rows={week.biggest_drops}
                showDrop
                empty="No price came down by more than a few dollars in this window."
              />
            </div>

            <div className="panel">
              <div className="panel__head">
                <h2>Dearest arrivals</h2>
              </div>
              {/* Ranked by price, not by recency: "newest" is what the browse
                  view already answers, and better. */}
              <HighlightList
                rows={week.arrivals}
                empty="Nothing new arrived with a price on it."
              />
            </div>
          </div>

          {(week.new_calibers.length > 0 ||
            week.new_countries.length > 0 ||
            week.new_manufacturers.length > 0) && (
            <div className="panel">
              <div className="panel__head">
                <h2>First seen this window</h2>
              </div>
              <div className="week-learned__body">
                <p className="week-empty" style={{ marginTop: 0 }}>
                  Values the catalog had never carried before. Usually new stock —
                  sometimes a classification rule that has started matching something it
                  should not.
                </p>
                <Learned title="Calibers" values={week.new_calibers} filter="caliber" />
                <Learned title="Countries" values={week.new_countries} filter="country" />
                <Learned
                  title="Makers"
                  values={week.new_manufacturers}
                  filter="manufacturer"
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
