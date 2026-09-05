/**
 * One scan run, with its live progress log.
 *
 * While the run is still going the page polls every two seconds and keeps the
 * log pinned to the bottom, so watching a scan works the way tailing a log does.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { useInterval, useTitle } from "../hooks.js";
import { formatDateTime, formatDuration, timeTitle } from "../format.js";
import { ScanStatusChip } from "../components/StatusChip.jsx";
import { ChevronLeft } from "../components/Icons.jsx";

const STATS = [
  ["items_found", "Found"],
  ["items_new", "New"],
  ["items_updated", "Updated"],
  ["items_delisted", "De-listed"],
  ["price_changes", "Price changes"],
  ["price_drops", "Reductions"],
  ["images_downloaded", "Photos"],
];

export default function ScanDetail() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const logRef = useRef(null);
  const pinnedRef = useRef(true);

  useTitle(run ? `Scan #${run.id}` : "Scan");

  const load = useCallback(() => {
    api
      .scan(runId)
      .then(setRun)
      .catch((err) => setError(err.message));
  }, [runId]);

  useEffect(load, [load]);

  const isRunning = run?.status === "running";
  useInterval(load, isRunning ? 2000 : null);

  // Follow the tail only while the reader has not scrolled up to read history.
  useEffect(() => {
    const node = logRef.current;
    if (!node || !pinnedRef.current) return;
    node.scrollTop = node.scrollHeight;
  }, [run?.log]);

  function onLogScroll(event) {
    const node = event.currentTarget;
    pinnedRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 40;
  }

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

  if (!run) {
    return (
      <div className="loading-row">
        <div className="spinner" />
        Loading scan…
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
          <h1 style={{ marginTop: 8 }}>
            {run.site_name} · scan #{run.id}
          </h1>
          <p title={timeTitle(run.started_at)}>
            Started {formatDateTime(run.started_at)}
            {run.finished_at
              ? ` · finished in ${formatDuration(run.duration_seconds)}`
              : " · in progress"}
          </p>
        </div>
        <div className="page-head__actions">
          <ScanStatusChip status={run.status} />
        </div>
      </div>

      {run.error_message && (
        <div
          className={`alert ${run.status === "partial" ? "alert--info" : "alert--error"}`}
          role="alert"
        >
          <strong>{run.status === "partial" ? "Warnings: " : "Error: "}</strong>
          {run.error_message}
        </div>
      )}

      <div className="panel">
        <div className="panel__head">
          <h2>Results</h2>
        </div>
        <div className="panel__body">
          <div className="stat-grid">
            {STATS.map(([key, label]) => (
              <div className="stat" key={key}>
                <div className="stat__value">{run[key]}</div>
                <div className="stat__label">{label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel__head">
          <h2>Progress log</h2>
          {isRunning && (
            <span className="chip chip--info">
              <span className="spinner" style={{ width: 12, height: 12 }} />
              Live
            </span>
          )}
        </div>
        <div className="panel__body">
          <pre className="scan-log" ref={logRef} onScroll={onLogScroll}>
            {run.log || "No log output recorded."}
          </pre>
        </div>
      </div>
    </div>
  );
}
