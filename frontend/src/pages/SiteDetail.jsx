/** One site: what it charges to ship a gun, and its scan history, newest first. */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { useInterval, useTitle } from "../hooks.js";
import {
  formatDateTime,
  formatDuration,
  formatInterval,
  formatMoney,
  formatRelative,
  timeTitle,
} from "../format.js";
import { useAuth } from "../auth.jsx";
import { ScanStatusChip } from "../components/StatusChip.jsx";
import { ChevronLeft, External, Refresh } from "../components/Icons.jsx";

const PAGE_SIZE = 50;

/**
 * What this shop charges to ship one gun, which every delivered price uses.
 *
 * The figures come from the shop's own policy page, declared on its scraper
 * with the page they were read from. An administrator can override either one
 * here when the shop changes its charge -- and clear the override to go back
 * to the declared figure.
 */
function ShippingPanel({ site, onSaved }) {
  const { isAdmin } = useAuth();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ long: "", hand: "", note: "" });
  const [error, setError] = useState(null);

  const shown = (value) => (value == null ? "Not stated" : formatMoney(value));

  function open() {
    setForm({
      long: site.shipping_long_gun == null ? "" : String(site.shipping_long_gun),
      hand: site.shipping_handgun == null ? "" : String(site.shipping_handgun),
      note: site.shipping_overridden ? site.shipping_note || "" : "",
    });
    setError(null);
    setEditing(true);
  }

  async function save(event, clear = false) {
    event.preventDefault();
    const number = (value) => (value.trim() === "" ? null : Number(value));
    try {
      await api.updateSite(
        site.id,
        clear
          ? { shipping_long_gun: null, shipping_handgun: null, shipping_note: null }
          : {
              shipping_long_gun: number(form.long),
              shipping_handgun: number(form.hand),
              shipping_note: form.note.trim() || null,
            },
      );
      setEditing(false);
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="panel" data-testid="site-shipping">
      <div className="panel__head">
        <h2>Firearm shipping</h2>
        {site.shipping_overridden && <span className="chip chip--info">Overridden</span>}
        {isAdmin && !editing && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={open}>
            Change
          </button>
        )}
      </div>
      <div className="panel__body">
        <p style={{ margin: 0 }}>
          Long gun <strong>{shown(site.shipping_long_gun)}</strong> · Handgun{" "}
          <strong>{shown(site.shipping_handgun)}</strong>
        </p>
        {site.shipping_note && <p className="muted">{site.shipping_note}</p>}
        {site.shipping_source && (
          <a href={site.shipping_source} target="_blank" rel="noopener noreferrer">
            <External size={13} /> Their shipping policy
          </a>
        )}
        {editing && (
          <form className="shipping-form" onSubmit={save}>
            {error && <p className="alert alert--error">{error}</p>}
            <label className="field">
              <span>Long gun ($)</span>
              <input
                className="input"
                inputMode="decimal"
                value={form.long}
                onChange={(event) => setForm({ ...form, long: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Handgun ($)</span>
              <input
                className="input"
                inputMode="decimal"
                value={form.hand}
                onChange={(event) => setForm({ ...form, hand: event.target.value })}
              />
            </label>
            <label className="field">
              <span>Note</span>
              <input
                className="input"
                maxLength={200}
                value={form.note}
                onChange={(event) => setForm({ ...form, note: event.target.value })}
              />
            </label>
            <div className="shipping-form__actions">
              <button type="submit" className="btn btn--primary btn--sm">
                Save
              </button>
              {site.shipping_overridden && (
                <button
                  type="button"
                  className="btn btn--secondary btn--sm"
                  onClick={(event) => save(event, true)}
                >
                  Back to the declared figures
                </button>
              )}
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => setEditing(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default function SiteDetail() {
  const { siteId } = useParams();
  const navigate = useNavigate();
  const [site, setSite] = useState(null);
  const [runs, setRuns] = useState(null);
  const [error, setError] = useState(null);

  useTitle(site ? `${site.name} scans` : "Scan history");

  const load = useCallback(() => {
    Promise.all([api.site(siteId), api.siteScans(siteId, { limit: PAGE_SIZE })])
      .then(([siteResult, runResult]) => {
        setSite(siteResult);
        setRuns(runResult);
      })
      .catch((err) => setError(err.message));
  }, [siteId]);

  useEffect(load, [load]);

  const running = runs?.some((run) => run.status === "running");
  useInterval(load, running ? 3000 : null);

  if (error) {
    return (
      <div>
        <div className="alert alert--error" role="alert">
          {error}
        </div>
        <button className="btn btn--secondary" onClick={() => navigate(-1)}>
          <ChevronLeft size={16} />
          Back
        </button>
      </div>
    );
  }

  if (!site) {
    return (
      <div className="loading-row">
        <div className="spinner" />
        Loading…
      </div>
    );
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <button className="btn btn--ghost" onClick={() => navigate(-1)}>
            <ChevronLeft size={17} />
            Back
          </button>
          <h1 style={{ marginTop: 8 }}>{site.name}</h1>
          <p>
            {site.enabled ? "Enabled" : "Disabled"} · scanned every{" "}
            {formatInterval(site.scan_interval_minutes)} ·{" "}
            {site.active_item_count.toLocaleString()} active listings
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--secondary" onClick={load}>
            <Refresh size={16} />
            Refresh
          </button>
        </div>
      </div>

      <ShippingPanel site={site} onSaved={load} />

      <div className="panel">
        <div className="panel__head">
          <h2>Scan history</h2>
          <span className="chip chip--neutral">{runs?.length ?? 0} runs</span>
        </div>

        {runs?.length === 0 ? (
          <div className="empty">
            <h3>No scans yet</h3>
            <p>Start one from the Sites page, or wait for the schedule.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th className="table__num">Found</th>
                  <th className="table__num">New</th>
                  <th className="table__num">De-listed</th>
                  <th className="table__num">Price changes</th>
                  <th>Trigger</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs?.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <ScanStatusChip status={run.status} />
                    </td>
                    <td title={timeTitle(run.started_at)}>
                      {formatDateTime(run.started_at)}
                      <div style={{ fontSize: 11.5, color: "var(--ink-400)" }}>
                        {formatRelative(run.started_at)}
                      </div>
                    </td>
                    <td>{formatDuration(run.duration_seconds)}</td>
                    <td className="table__num">{run.items_found}</td>
                    <td className="table__num">{run.items_new}</td>
                    <td className="table__num">{run.items_delisted}</td>
                    <td className="table__num">
                      {run.price_changes}
                      {run.price_drops > 0 && (
                        <span
                          style={{ color: "var(--green-600)", marginLeft: 5 }}
                          title={`${run.price_drops} reductions`}
                        >
                          ▼{run.price_drops}
                        </span>
                      )}
                    </td>
                    <td>
                      <span className="chip chip--neutral">{run.trigger}</span>
                    </td>
                    <td className="table__actions">
                      <Link className="btn btn--ghost btn--sm" to={`/scans/${run.id}`}>
                        Details
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
