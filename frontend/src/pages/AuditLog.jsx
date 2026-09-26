/**
 * What administrators did, and who did it.
 *
 * Failed sign-ins were always logged; what happened *after* somebody got in
 * was not. Creating an account, changing a role, disabling a site are each a
 * decision somebody made, and a log file that scrolls and rotates is not where
 * you go to find out who made it.
 *
 * **Read-only, and that is the feature.** There is no way to edit or delete a
 * row from here, because a log somebody can tidy answers a different question
 * from the one it appears to answer.
 *
 * Admin-only, which is a judgment rather than an obvious call: the log is
 * mostly *about* administrators, and showing everyone who changed whose role
 * would be a privacy decision made by accident.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatDateTime, timeTitle } from "../format.js";

//: How an action reads to somebody who did not choose its name.
const LABELS = {
  "user.created": "User created",
  "user.updated": "User changed",
  "user.deleted": "User deleted",
  "user.role_changed": "Role changed",
  "user.reset_link_sent": "Reset link sent",
  // Rows written before the action was renamed. Kept so the old ones still
  // read as words rather than as a raw key; see services/audit.py for why the
  // name changed.
  "user.password_reset_sent": "Reset link sent",
  "site.enabled": "Site enabled",
  "site.disabled": "Site disabled",
  "site.newsletter_confirmed": "Mailing list marked confirmed",
  "session.revoked": "Session revoked",
  "session.revoked_all": "Other sessions revoked",
  "armory.edited": "Armory row changed",
  "armory.deleted": "Armory row deleted",
  "armory.reverted": "Armory change undone",
};

function label(action) {
  return LABELS[action] || action;
}

export default function AuditLogPage() {
  useTitle("Audit log");
  const [rows, setRows] = useState(null);
  const [actions, setActions] = useState([]);
  const [action, setAction] = useState("");
  const [undoing, setUndoing] = useState(null);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setError(null);
    api
      .auditLog({ action: action || undefined, limit: 200 })
      .then(setRows)
      .catch((err) => setError(err.message));
  }, [action]);

  useEffect(load, [load]);

  /**
   * Put one change back.
   *
   * The list is reloaded afterwards rather than patched in place: an undo
   * writes a new event of its own, and a page that showed the old list with a
   * row silently altered would be lying about its own history.
   */
  async function undo(row) {
    setUndoing(row.id);
    setNotice("");
    setProblem("");
    try {
      const result = await api.revertArmoryChange(row.id);
      setNotice(result.message);
      load();
    } catch (err) {
      setProblem(err.message);
    } finally {
      setUndoing(null);
    }
  }

  useEffect(() => {
    // The filter offers only actions that have actually happened: one listing
    // every action the code can emit is a filter that mostly returns nothing.
    api
      .auditActions()
      .then(setActions)
      .catch(() => setActions([]));
  }, []);

  return (
    <div className="page">
      <div className="page-head">
        <h1>Audit log</h1>
        <label className="field field--inline">
          <span>Action</span>
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            <option value="">Everything</option>
            {actions.map((name) => (
              <option key={name} value={name}>
                {label(name)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="alert alert--danger">{error}</p>}
      {rows === null && !error && <p className="muted">Loading…</p>}
      {rows !== null && rows.length === 0 && (
        <p className="muted">Nothing recorded yet.</p>
      )}

      {notice && <p className="alert alert--success">{notice}</p>}
      {problem && <p className="alert alert--error">{problem}</p>}

      {rows !== null && rows.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>What</th>
                <th>Target</th>
                <th>Detail</th>
                <th>From</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td title={row.created_at ? timeTitle(row.created_at) : undefined}>
                    {row.created_at ? formatDateTime(row.created_at) : "—"}
                  </td>
                  {/* The name, not a link to the account: it may not exist any
                      more, and the row about somebody who has been deleted is
                      usually the one worth reading. */}
                  <td>{row.actor_name || "—"}</td>
                  <td>{label(row.action)}</td>
                  <td>{row.target_label || row.target_id || "—"}</td>
                  <td>{row.detail || "—"}</td>
                  <td>{row.ip_address || "—"}</td>
                  <td className="table__actions">
                    {/* Only where the row recorded what it held beforehand.
                        The server answers that question, because a button that
                        replies with an error is worse than no button. */}
                    {row.revertible && (
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        disabled={undoing === row.id}
                        onClick={() => undo(row)}
                      >
                        {undoing === row.id ? "Undoing…" : "Undo"}
                      </button>
                    )}
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
