/** Scan history for one site, newest first. */
import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { useInterval, useTitle } from "../hooks.js";
import {
  formatDateTime,
  formatDuration,
  formatInterval,
  formatRelative,
  timeTitle,
} from "../format.js";
import { ScanStatusChip } from "../components/StatusChip.jsx";
import { ChevronLeft, Refresh } from "../components/Icons.jsx";

const PAGE_SIZE = 50;

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
