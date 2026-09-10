/**
 * Database snapshots: the schedule, and taking one now.
 *
 * The three settings that are policy — whether, how often, how many to keep —
 * live in the database and are edited here. Where the files land does not: it
 * is shown and not editable, because a text box that can point the writer at
 * any path on the server is a worse idea than a default nobody can change from
 * a browser.
 *
 * The list matters as much as the switch. A schedule that says "daily" over a
 * directory holding nothing is the failure this page exists to make visible,
 * and it is only visible if both are on the screen at once.
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatBytes, formatRelative, timeTitle } from "../format.js";
import { Refresh } from "../components/Icons.jsx";

const HOURS_LABEL = {
  6: "Every 6 hours",
  12: "Every 12 hours",
  24: "Daily",
  48: "Every 2 days",
  72: "Every 3 days",
  168: "Weekly",
};

export default function BackupsPage() {
  useTitle("Backups");
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      setState(await api.backups());
      setError("");
    } catch (err) {
      setError(err.message || "Could not read the backup settings.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function change(patch) {
    setBusy("saving");
    setNote("");
    try {
      setState(await api.updateBackups(patch));
      setError("");
    } catch (err) {
      setError(err.message || "Could not save that.");
    } finally {
      setBusy("");
    }
  }

  async function runNow() {
    setBusy("running");
    setNote("");
    setError("");
    try {
      const next = await api.runBackup();
      setState(next);
      const newest = next.snapshots[0];
      setNote(newest ? `Wrote ${newest.name} (${formatBytes(newest.bytes)}).` : "Done.");
    } catch (err) {
      setError(err.message || "The backup failed.");
    } finally {
      setBusy("");
    }
  }

  if (!state) {
    return (
      <>
        <div className="page-head">
          <div>
            <h1>Backups</h1>
          </div>
        </div>
        {error ? (
          <p className="alert alert--error">{error}</p>
        ) : (
          <div className="loading-row" />
        )}
      </>
    );
  }

  const { settings, snapshots } = state;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Backups</h1>
          <p>
            Snapshots of the database, taken by the application itself. The code is in
            version control and the photos can be fetched again; the price history cannot.
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--primary" onClick={runNow} disabled={!!busy}>
            {busy === "running" ? (
              <span className="spinner spinner--sm" />
            ) : (
              <Refresh aria-hidden="true" />
            )}
            {busy === "running" ? "Backing up…" : "Back up now"}
          </button>
        </div>
      </div>

      {error && <p className="alert alert--error">{error}</p>}
      {note && <p className="alert alert--success">{note}</p>}

      <div className="settings-grid">
        <div className="panel">
          <div className="panel__head">
            <h2>Schedule</h2>
            <label className="switch">
              <input
                type="checkbox"
                checked={settings.enabled}
                disabled={!!busy}
                onChange={(event) => change({ enabled: event.target.checked })}
              />
              <span className="switch__track" />
              <span>{settings.enabled ? "On" : "Off"}</span>
            </label>
          </div>
          <div className="panel__body">
            <div className="form-row form-row--2">
              <label className="field">
                <span className="field__label">How often</span>
                <select
                  className="select"
                  value={settings.interval_hours}
                  disabled={!!busy || !settings.enabled}
                  onChange={(event) =>
                    change({ interval_hours: Number(event.target.value) })
                  }
                >
                  {state.interval_choices.map((hours) => (
                    <option key={hours} value={hours}>
                      {HOURS_LABEL[hours] || `Every ${hours} hours`}
                    </option>
                  ))}
                </select>
                <span className="field__hint">
                  Measured against the newest file on disk, not a timer, so a restart
                  never skips one.
                </span>
              </label>

              <label className="field">
                <span className="field__label">Keep</span>
                <select
                  className="select"
                  value={settings.keep}
                  disabled={!!busy}
                  onChange={(event) => change({ keep: Number(event.target.value) })}
                >
                  {state.keep_choices.map((count) => (
                    <option key={count} value={count}>
                      {count} snapshots
                    </option>
                  ))}
                </select>
                <span className="field__hint">
                  Older ones are deleted after each run. These are full copies.
                </span>
              </label>
            </div>

            {settings.last_run_at && (
              <p
                className={
                  settings.last_status === "FAILED" ? "alert alert--error" : "field__hint"
                }
              >
                Last run{" "}
                <span title={timeTitle(settings.last_run_at)}>
                  {formatRelative(settings.last_run_at)}
                </span>
                {settings.last_status === "FAILED"
                  ? ` — failed: ${settings.last_error}`
                  : settings.last_bytes
                    ? ` — wrote ${formatBytes(settings.last_bytes)}`
                    : ""}
              </p>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel__head">
            <h2>Snapshots</h2>
            <span className="chip chip--neutral">
              {snapshots.length} · {formatBytes(state.total_bytes)}
            </span>
          </div>
          <div className="panel__body">
            {snapshots.length === 0 ? (
              <p className="empty">
                No snapshots yet.
                {settings.enabled
                  ? " The next one is taken when it falls due."
                  : " The schedule is off — switch it on, or use “Back up now”."}
              </p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>Taken</th>
                      <th>Size</th>
                      {/*
                        Per file, because this directory outlives a move
                        between engines: after one it holds both kinds, and
                        only the newest of them is the sort the running
                        configuration describes. One hint for the whole list
                        told an operator to pg_restore two SQLite files.
                      */}
                      <th>Restore with</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshots.map((snapshot) => (
                      <tr key={snapshot.name}>
                        <td>{snapshot.name}</td>
                        <td title={timeTitle(snapshot.taken_at)}>
                          {formatRelative(snapshot.taken_at)}
                        </td>
                        <td>{formatBytes(snapshot.bytes)}</td>
                        <td>
                          <span
                            className={
                              snapshot.engine === state.engine
                                ? "chip chip--neutral"
                                : "chip chip--warning"
                            }
                            title={
                              snapshot.engine === state.engine
                                ? snapshot.restore_hint
                                : `Written by ${snapshot.engine}, which is not what this ` +
                                  `application is running now. To restore: ${snapshot.restore_hint}`
                            }
                          >
                            {snapshot.engine === "postgresql"
                              ? "pg_restore"
                              : "sqlite3 file"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="field__hint">
              Written to {state.directory}. The next snapshot is {state.engine}:{" "}
              {state.restore_hint}
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
