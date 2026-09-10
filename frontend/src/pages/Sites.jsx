/**
 * Site administration: at-a-glance status for every vendor, with controls to
 * enable/disable a site, set its scan frequency, and start a scan now.
 *
 * The list polls while any scan is running so progress appears without the
 * admin reloading; polling stops as soon as everything is idle.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useInterval, useTitle } from "../hooks.js";
import {
  formatCountdown,
  formatDuration,
  formatInterval,
  formatRelative,
  timeTitle,
} from "../format.js";
import { ScanStatusChip } from "../components/StatusChip.jsx";
import {
  Browser,
  Check,
  History,
  Pause,
  Play,
  Refresh,
  Stop,
  Warning,
  X,
} from "../components/Icons.jsx";

/** Offered cadences. The API floor is 5 minutes; nothing below an hour is
 *  polite to a vendor, so the shortest option here is hourly. The ceiling is
 *  the API's 30 days.
 *
 *  Spelled "Every 2 weeks" rather than "biweekly" on purpose: that word means
 *  both "every two weeks" and "twice a week" and half the readers of a select
 *  box would pick the wrong one. Same reason "Every 2 days" is not "bidaily".
 *
 *  A fortnight is here for the vendors whose scan is genuinely expensive —
 *  Collectors Firearms ask for a 10-second crawl delay and refuse it at 10, so
 *  a first pass over their 691 listings is hours of somebody else's bandwidth
 *  and their stock does not turn over in a day. */
const INTERVALS = [
  { value: 60, label: "Every hour" },
  { value: 180, label: "Every 3 hours" },
  { value: 360, label: "Every 6 hours" },
  { value: 720, label: "Every 12 hours" },
  { value: 1440, label: "Daily" },
  { value: 2880, label: "Every 2 days" },
  { value: 10080, label: "Weekly" },
  { value: 20160, label: "Every 2 weeks" },
];

/**
 * The outcome of a scan the operator just started.
 *
 * Shown until dismissed or until it ages out, so the answer to "did that
 * work?" does not disappear the instant the status chip flips back.
 */
function ScanResult({ result, onDismiss }) {
  const failed = result.status === "failed" || result.status === "canceled";
  const partial = result.status === "partial";
  const tone = failed ? "error" : partial ? "info" : "success";

  return (
    <div className={`site-card__result site-card__result--${tone}`} role="status">
      <span className="site-card__result-icon">
        {failed ? <X size={15} /> : partial ? <Warning size={15} /> : <Check size={15} />}
      </span>
      <div className="site-card__result-body">
        <strong>
          {failed
            ? result.status === "canceled"
              ? "Scan canceled"
              : "Scan failed"
            : partial
              ? "Scan finished with warnings"
              : "Scan complete"}
        </strong>
        {failed ? (
          <div className="site-card__result-detail">
            {result.error_message || "No further detail was recorded."}
          </div>
        ) : (
          <div className="site-card__result-detail">
            {result.items_found.toLocaleString()} found · {result.items_new} new ·{" "}
            {result.items_delisted} de-listed · {result.price_changes} price change
            {result.price_changes === 1 ? "" : "s"}
            {partial && result.error_message ? ` — ${result.error_message}` : ""}
          </div>
        )}
      </div>
      <button
        className="site-card__result-close"
        onClick={onDismiss}
        aria-label="Dismiss scan result"
      >
        <X size={14} />
      </button>
    </div>
  );
}

/**
 * Explain a scan time, because the number alone invites the wrong conclusion.
 *
 * A re-scan of Empire Arms is two static pages with every photo already on
 * disk, so it finishes in about two seconds — which reads as "it cannot have
 * done anything" until you see that it checked 58 listings and had no photos
 * left to fetch. Royal Tiger's quarter of an hour is mostly image downloads.
 * The counts are what make the difference legible.
 */
function scanTimeDetail(run) {
  if (!run || run.duration_seconds == null) return undefined;
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const parts = [`${run.duration_seconds.toFixed(1)} seconds end to end`];
  parts.push(`${plural(run.items_found, "listing")} checked`);
  if (run.items_new) parts.push(`${run.items_new} new`);
  parts.push(
    run.images_downloaded
      ? `${plural(run.images_downloaded, "photo")} downloaded`
      : "no photos needed downloading",
  );
  return parts.join(" · ");
}

function SiteCard({ site, result, onChange, onError, onDismissResult }) {
  const [busy, setBusy] = useState(false);

  async function patch(body) {
    setBusy(true);
    try {
      const updated = await api.updateSite(site.id, body);
      onChange(updated);
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  /** Lift the pause early, once whatever caused it is known and fixed.
   *
   * Deliberately a separate button rather than a confirmation on "Scan now":
   * the pause exists because the vendor's server refused us, so going back
   * before they asked is a decision about them, not a local preference.
   */
  async function wakeUp() {
    setBusy(true);
    try {
      await api.clearResting(site.id);
      onChange({ ...site, resting_seconds: null, resting_reason: null });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function scanNow() {
    setBusy(true);
    try {
      await api.startScan(site.id);
      onChange({ ...site, is_scanning: true });
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      await api.cancelScan(site.id);
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`panel site-card ${site.is_scanning ? "site-card--scanning" : ""}`}>
      {/* An indeterminate bar: a scan has no meaningful percentage until it
          finishes, so this signals "working" rather than faking progress. */}
      {site.is_scanning && (
        <div
          className="site-card__progress"
          role="progressbar"
          aria-label={`Scanning ${site.name}`}
        >
          <span className="site-card__progress-bar" />
        </div>
      )}

      <div className="site-card__top">
        <div style={{ minWidth: 0 }}>
          <div className="site-card__name">{site.name}</div>
          <a
            className="site-card__url"
            href={site.base_url}
            target="_blank"
            // noreferrer as well as noopener: the vendor does not need to
            // learn that the click came from here, which is the same rule the
            // item page follows for its "View on ..." link.
            rel="noopener noreferrer"
          >
            {site.base_url}
          </a>
          <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
            {site.is_scanning ? (
              <span className="chip chip--info">
                <span className="spinner spinner--sm" />
                Scanning…
              </span>
            ) : site.resting_seconds ? (
              <span
                className="chip chip--warning"
                title={site.resting_reason || "This host refused our requests"}
              >
                <Pause size={12} />
                Resting {formatCountdown(site.resting_seconds)}
              </span>
            ) : site.last_run ? (
              <ScanStatusChip status={site.last_run.status} />
            ) : (
              <span className="chip chip--neutral">Never scanned</span>
            )}
            {/*
              Neutral, not a warning. This states how the site is scraped — it
              is a permanent property of the vendor, not a problem and not a
              diagnosis. Styled as a warning next to a red "Failed" chip, it
              read as the cause of the failure and sent someone off to install
              a browser that was already working.
            */}
            {site.requires_browser && (
              <span
                className="chip chip--neutral"
                title="Scraped with headless Chrome, because this site renders its catalog in JavaScript"
              >
                <Browser size={12} />
                Browser
              </span>
            )}
            {!site.is_available && <span className="chip chip--danger">No scraper</span>}
          </div>
        </div>

        <label className="switch" title={site.enabled ? "Disable site" : "Enable site"}>
          <input
            type="checkbox"
            checked={site.enabled}
            disabled={busy || !site.is_available}
            onChange={(event) => patch({ enabled: event.target.checked })}
          />
          <span className="switch__track" />
          <span className="visually-hidden">
            {site.enabled ? "Disable" : "Enable"} {site.name}
          </span>
        </label>
      </div>

      <div className="site-card__stats">
        <div className="site-card__stat">
          <div className="site-card__stat-value">
            {site.active_item_count.toLocaleString()}
          </div>
          <div className="site-card__stat-label">Active</div>
        </div>
        <div className="site-card__stat">
          <div className="site-card__stat-value">{site.item_count.toLocaleString()}</div>
          <div className="site-card__stat-label">Total seen</div>
        </div>
        <div className="site-card__stat">
          <div
            className="site-card__stat-value"
            style={{ fontSize: 13, fontWeight: 600 }}
            title={timeTitle(site.last_scan_at)}
          >
            {site.last_scan_at ? formatRelative(site.last_scan_at) : "never"}
          </div>
          <div className="site-card__stat-label">Last scan</div>
        </div>
        <div className="site-card__stat">
          <div
            className="site-card__stat-value"
            style={{ fontSize: 13, fontWeight: 600 }}
            title={scanTimeDetail(site.last_run)}
          >
            {formatDuration(site.last_run?.duration_seconds)}
          </div>
          <div className="site-card__stat-label">Scan time</div>
        </div>
      </div>

      <div className="site-card__controls">
        <label className="visually-hidden" htmlFor={`interval-${site.id}`}>
          Scan frequency for {site.name}
        </label>
        <select
          id={`interval-${site.id}`}
          className="select"
          style={{ width: "auto", flex: "1 1 150px" }}
          value={site.scan_interval_minutes}
          disabled={busy}
          onChange={(event) =>
            patch({ scan_interval_minutes: Number(event.target.value) })
          }
        >
          {/* A cadence set elsewhere (config or CLI) still needs to display. */}
          {!INTERVALS.some((i) => i.value === site.scan_interval_minutes) && (
            <option value={site.scan_interval_minutes}>
              Every {formatInterval(site.scan_interval_minutes)}
            </option>
          )}
          {INTERVALS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        {site.is_scanning ? (
          <button className="btn btn--secondary btn--sm" onClick={cancel} disabled={busy}>
            <Stop size={14} />
            Stop
          </button>
        ) : (
          <button
            className="btn btn--primary btn--sm"
            onClick={scanNow}
            disabled={busy || !site.is_available || Boolean(site.resting_seconds)}
            title={
              site.resting_seconds
                ? "This host asked to be left alone. Scanning it now would ignore that."
                : undefined
            }
          >
            <Play size={14} />
            Scan now
          </button>
        )}

        {Boolean(site.resting_seconds) && (
          <button className="btn btn--secondary btn--sm" onClick={wakeUp} disabled={busy}>
            Fetch anyway
          </button>
        )}

        <Link className="btn btn--secondary btn--sm" to={`/sites/${site.id}`}>
          <History size={14} />
          History
        </Link>
      </div>

      {result && <ScanResult result={result} onDismiss={onDismissResult} />}

      {Boolean(site.resting_seconds) && (
        <div className="site-card__resting">
          Every scan and photo download is leaving this host alone for another{" "}
          {formatCountdown(site.resting_seconds)}
          {site.resting_reason ? ` — ${site.resting_reason}.` : "."} It refused our
          requests, so nothing will ask it again until then.
        </div>
      )}

      {site.next_scan_at && site.enabled && !site.is_scanning && (
        <div
          style={{
            padding: "0 16px 13px",
            fontSize: 12,
            color: "var(--ink-500)",
          }}
          title={timeTitle(site.next_scan_at)}
        >
          Next scan {formatRelative(site.next_scan_at)}
        </div>
      )}
    </div>
  );
}

//: How long a finished scan's result stays on screen before clearing itself.
const RESULT_TIMEOUT_MS = 45_000;

export default function Sites() {
  useTitle("Sites");
  const [sites, setSites] = useState(null);
  const [error, setError] = useState(null);
  // siteId -> the ScanRun that just finished, for the outcome banner.
  const [results, setResults] = useState({});
  // Mirrors watchingRef's size into state so a change re-renders and restarts
  // the poll interval; the ref remains the source of truth.
  const [watchCount, setWatchCount] = useState(0);
  // Sites whose scan we are waiting on. An id goes in when a scan is started or
  // observed running, and comes out only once its outcome has been recorded.
  //
  // Deliberately not "what was scanning last poll": a poll already in flight
  // when the operator clicks Scan now lands afterwards and would overwrite that,
  // losing the watch so the outcome banner never appears.
  const watchingRef = useRef(new Set());
  const timersRef = useRef({});

  const dismissResult = useCallback((siteId) => {
    setResults((current) => {
      if (!(siteId in current)) return current;
      const next = { ...current };
      delete next[siteId];
      return next;
    });
    clearTimeout(timersRef.current[siteId]);
    delete timersRef.current[siteId];
  }, []);

  const load = useCallback(() => {
    api
      .sites()
      .then((next) => {
        setSites(next);

        // Anything currently running is worth watching, however it started —
        // including a scan the scheduler kicked off, or one begun in another tab.
        next.forEach((site) => {
          if (site.is_scanning) watchingRef.current.add(site.id);
        });

        // A watched site that is no longer scanning has finished, so its
        // last_run is the outcome.
        const finished = next.filter(
          (site) =>
            watchingRef.current.has(site.id) && !site.is_scanning && site.last_run,
        );
        if (finished.length) {
          setResults((current) => {
            const merged = { ...current };
            finished.forEach((site) => {
              merged[site.id] = site.last_run;
            });
            return merged;
          });
          finished.forEach((site) => {
            watchingRef.current.delete(site.id);
            clearTimeout(timersRef.current[site.id]);
            timersRef.current[site.id] = setTimeout(
              () => dismissResult(site.id),
              RESULT_TIMEOUT_MS,
            );
          });
        }
        setWatchCount(watchingRef.current.size);
      })
      .catch((err) => setError(err.message));
  }, [dismissResult]);

  useEffect(load, [load]);

  // Drop any pending auto-dismiss timers when leaving the page.
  useEffect(() => {
    const timers = timersRef.current;
    return () => Object.values(timers).forEach(clearTimeout);
  }, []);

  // Poll while anything is running *or* still being waited on. Keying only on
  // is_scanning would stop polling at the moment a scan finished — which is
  // exactly the poll that needs to record the outcome.
  const anyScanning = sites?.some((site) => site.is_scanning);
  useInterval(load, anyScanning || watchCount > 0 ? 1500 : null);

  const replace = (updated) =>
    setSites((current) =>
      current.map((site) => (site.id === updated.id ? { ...site, ...updated } : site)),
    );

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Sites</h1>
          <p>
            Enable or disable each vendor, set how often it is scanned, and drill into its
            scan history.
          </p>
        </div>
        <div className="page-head__actions">
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

      {!sites && (
        <div className="loading-row">
          <div className="spinner" />
          Loading sites…
        </div>
      )}

      {sites?.length === 0 && (
        <div className="empty">
          <h3>No sites registered</h3>
          <p>Run `make init` to seed the site list from the scraper registry.</p>
        </div>
      )}

      {sites?.length > 0 && (
        <div className="site-list">
          {sites.map((site) => (
            <SiteCard
              key={site.id}
              site={site}
              result={results[site.id]}
              onChange={(updated) => {
                // Starting a scan clears any previous outcome and registers the
                // site as watched, so the poll that sees it finish can record
                // the result.
                if (updated.is_scanning) {
                  dismissResult(site.id);
                  watchingRef.current.add(site.id);
                  setWatchCount(watchingRef.current.size);
                }
                replace(updated);
              }}
              onError={setError}
              onDismissResult={() => dismissResult(site.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
