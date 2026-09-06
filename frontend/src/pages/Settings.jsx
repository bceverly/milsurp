/**
 * Per-user settings: email digest configuration and password change.
 *
 * The per-site item limits are deliberately required rather than optional —
 * without a cap, one big scan turns a digest into a hundred-item wall of text.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { usePasswordPolicy, useTitle } from "../hooks.js";
import { useAuth } from "../auth.jsx";
import { browserTimeZone, formatDateTime, formatRelative, timeTitle } from "../format.js";
import { EmailStatusChip } from "../components/StatusChip.jsx";
import Field from "../components/Field.jsx";
import { Check, Mail, Sparkle, TrendDown } from "../components/Icons.jsx";

const FREQUENCIES = [
  { value: 6, label: "Every 6 hours" },
  { value: 12, label: "Every 12 hours" },
  { value: 24, label: "Daily" },
  { value: 48, label: "Every 2 days" },
  { value: 168, label: "Weekly" },
];

const LIMITS = [1, 3, 5, 10, 15, 20, 25, 50];

export default function SettingsPage() {
  useTitle("Email digest");
  const { user } = useAuth();
  const [prefs, setPrefs] = useState(null);
  const [sites, setSites] = useState([]);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  // Built as a de-duplicated list rather than three hand-written <option>s.
  // The old version emitted a fixed <option value="UTC"> *and* an option for
  // the stored zone, so anyone whose stored zone was UTC — which was everyone,
  // because that was the column default — saw "UTC" listed twice.
  const timeZoneOptions = useMemo(() => {
    const zones = [];
    const add = (value, label) => {
      if (value && !zones.some((zone) => zone.value === value)) {
        zones.push({ value, label });
      }
    };
    add(browserTimeZone, `${browserTimeZone} (this device)`);
    add(prefs?.display_timezone, prefs?.display_timezone);
    add("UTC", "UTC");
    return zones;
  }, [prefs?.display_timezone]);

  const load = useCallback(() => {
    Promise.all([api.preferences(), api.sites(), api.emailHistory({ limit: 10 })])
      .then(([prefResult, siteResult, historyResult]) => {
        setPrefs(prefResult);
        setSites(siteResult);
        setHistory(historyResult);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const set = (key, value) => setPrefs((current) => ({ ...current, [key]: value }));

  function toggleSite(siteId) {
    setPrefs((current) => {
      const selected = current.site_ids || [];
      return {
        ...current,
        site_ids: selected.includes(siteId)
          ? selected.filter((id) => id !== siteId)
          : [...selected, siteId],
      };
    });
  }

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await api.savePreferences({
        enabled: prefs.enabled,
        frequency_hours: prefs.frequency_hours,
        include_new_items: prefs.include_new_items,
        new_items_per_site_limit: prefs.new_items_per_site_limit,
        include_price_drops: prefs.include_price_drops,
        price_drops_per_site_limit: prefs.price_drops_per_site_limit,
        minimum_price_drop: prefs.minimum_price_drop,
        skip_when_empty: prefs.skip_when_empty,
        display_timezone: prefs.display_timezone,
        site_ids: prefs.site_ids || [],
      });
      setPrefs(saved);
      setNotice("Digest settings saved.");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function sendTest() {
    setTesting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.sendTestDigest();
      setNotice(result.message);
      api
        .emailHistory({ limit: 10 })
        .then(setHistory)
        .catch(() => {});
    } catch (err) {
      setError(err.message);
    } finally {
      setTesting(false);
    }
  }

  if (!prefs) {
    return (
      <div className="loading-row">
        <div className="spinner" />
        Loading settings…
      </div>
    );
  }

  const allSites = (prefs.site_ids || []).length === 0;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Email digest</h1>
          <p>
            Choose what lands in your inbox, how often, and from which sites. Sent to{" "}
            <strong>{user?.email}</strong>.
          </p>
        </div>
      </div>

      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="alert alert--success" role="status">
          <Check size={15} /> {notice}
        </div>
      )}

      <form onSubmit={save}>
        <div className="settings-grid">
          <div>
            <div className="panel">
              <div className="panel__head">
                <h2>Delivery</h2>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={prefs.enabled}
                    onChange={(event) => set("enabled", event.target.checked)}
                  />
                  <span className="switch__track" />
                  <span>{prefs.enabled ? "On" : "Off"}</span>
                </label>
              </div>
              <div className="panel__body">
                <label className="field">
                  <span className="field__label">How often</span>
                  <select
                    className="select"
                    value={prefs.frequency_hours}
                    onChange={(event) =>
                      set("frequency_hours", Number(event.target.value))
                    }
                  >
                    {!FREQUENCIES.some((f) => f.value === prefs.frequency_hours) && (
                      <option value={prefs.frequency_hours}>
                        Every {prefs.frequency_hours} hours
                      </option>
                    )}
                    {FREQUENCIES.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <Field
                  label="Times shown in"
                  hint="Everything is stored in UTC; this only affects the times printed inside the email, where there is no browser to convert them."
                >
                  {(id, describedBy) => (
                    <select
                      id={id}
                      aria-describedby={describedBy}
                      className="select"
                      // Null means the user has never chosen: offer their own
                      // zone rather than silently mailing everyone UTC times.
                      value={prefs.display_timezone || browserTimeZone}
                      onChange={(event) => set("display_timezone", event.target.value)}
                    >
                      {timeZoneOptions.map((zone) => (
                        <option key={zone.value} value={zone.value}>
                          {zone.label}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>

                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={prefs.skip_when_empty}
                    onChange={(event) => set("skip_when_empty", event.target.checked)}
                  />
                  <span>
                    Skip the email when there is nothing new
                    <span className="field__hint">
                      Recommended. Otherwise you get a message every cycle even when
                      nothing changed.
                    </span>
                  </span>
                </label>

                {prefs.next_send_at && prefs.enabled && (
                  <p
                    style={{ fontSize: 13, color: "var(--ink-500)", marginBottom: 0 }}
                    title={timeTitle(prefs.next_send_at)}
                  >
                    Next digest {formatRelative(prefs.next_send_at)}.
                    {prefs.last_sent_at &&
                      ` Last sent ${formatRelative(prefs.last_sent_at)}.`}
                  </p>
                )}
              </div>
            </div>

            <div className="panel">
              <div className="panel__head">
                <h2>Sites</h2>
                <span className="chip chip--neutral">
                  {allSites ? "All sites" : `${prefs.site_ids.length} selected`}
                </span>
              </div>
              <div className="panel__body">
                <p style={{ fontSize: 13, color: "var(--ink-500)", marginTop: 0 }}>
                  Select none to follow every enabled site, including ones added later.
                </p>
                {sites.map((site) => (
                  <label className="checkbox" key={site.id}>
                    <input
                      type="checkbox"
                      checked={(prefs.site_ids || []).includes(site.id)}
                      onChange={() => toggleSite(site.id)}
                    />
                    <span>
                      {site.name}
                      {!site.enabled && (
                        <span className="chip chip--neutral" style={{ marginLeft: 7 }}>
                          disabled
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div>
            <div className="panel">
              <div className="panel__head">
                <h2>
                  <Sparkle size={16} /> New listings
                </h2>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={prefs.include_new_items}
                    onChange={(event) => set("include_new_items", event.target.checked)}
                  />
                  <span className="switch__track" />
                  <span className="visually-hidden">Include new listings</span>
                </label>
              </div>
              <div className="panel__body">
                <Field
                  label="Most per site"
                  hint="A hard cap per site, so a large scan cannot flood the email."
                >
                  {(id, describedBy) => (
                    <select
                      id={id}
                      aria-describedby={describedBy}
                      className="select"
                      value={prefs.new_items_per_site_limit}
                      disabled={!prefs.include_new_items}
                      onChange={(event) =>
                        set("new_items_per_site_limit", Number(event.target.value))
                      }
                    >
                      {LIMITS.map((limit) => (
                        <option key={limit} value={limit}>
                          {limit} listing{limit === 1 ? "" : "s"}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
              </div>
            </div>

            <div className="panel">
              <div className="panel__head">
                <h2>
                  <TrendDown size={16} /> Price reductions
                </h2>
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={prefs.include_price_drops}
                    onChange={(event) => set("include_price_drops", event.target.checked)}
                  />
                  <span className="switch__track" />
                  <span className="visually-hidden">Include price reductions</span>
                </label>
              </div>
              <div className="panel__body">
                <div className="form-row form-row--2">
                  <label className="field">
                    <span className="field__label">Most per site</span>
                    <select
                      className="select"
                      value={prefs.price_drops_per_site_limit}
                      disabled={!prefs.include_price_drops}
                      onChange={(event) =>
                        set("price_drops_per_site_limit", Number(event.target.value))
                      }
                    >
                      {LIMITS.map((limit) => (
                        <option key={limit} value={limit}>
                          {limit} listing{limit === 1 ? "" : "s"}
                        </option>
                      ))}
                    </select>
                  </label>

                  <Field label="Ignore drops under" hint="Dollars. 0 reports every drop.">
                    {(id, describedBy) => (
                      <input
                        id={id}
                        aria-describedby={describedBy}
                        className="input"
                        type="number"
                        min="0"
                        step="5"
                        value={prefs.minimum_price_drop}
                        disabled={!prefs.include_price_drops}
                        onChange={(event) =>
                          set("minimum_price_drop", Number(event.target.value) || 0)
                        }
                      />
                    )}
                  </Field>
                </div>
              </div>
            </div>

            <div className="page-head__actions" style={{ marginBottom: 18 }}>
              <button className="btn btn--primary" type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save settings"}
              </button>
              <button
                className="btn btn--secondary"
                type="button"
                onClick={sendTest}
                disabled={testing}
              >
                <Mail size={16} />
                {testing ? "Sending…" : "Send one now"}
              </button>
            </div>
          </div>
        </div>
      </form>

      <div className="panel">
        <div className="panel__head">
          <h2>Recent digests</h2>
        </div>
        {history.length === 0 ? (
          <div className="panel__body">
            <p style={{ margin: 0, color: "var(--ink-500)", fontSize: 14 }}>
              No digests sent yet.
            </p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Status</th>
                  <th className="table__num">New</th>
                  <th className="table__num">Reductions</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {history.map((entry) => (
                  <tr key={entry.id}>
                    <td title={timeTitle(entry.sent_at)}>
                      {formatDateTime(entry.sent_at)}
                    </td>
                    <td>
                      <EmailStatusChip status={entry.status} />
                    </td>
                    <td className="table__num">{entry.new_item_count}</td>
                    <td className="table__num">{entry.price_drop_count}</td>
                    <td style={{ color: "var(--ink-500)", fontSize: 12.5 }}>
                      {entry.error_message || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <PasswordPanel />
    </div>
  );
}

function PasswordPanel() {
  const policy = usePasswordPolicy();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    if (next !== confirm) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      // Changing the password revokes every issued token, including this tab's,
      // so the next request will bounce to the sign-in screen by design.
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel__head">
        <h2>Password</h2>
      </div>
      <div className="panel__body">
        {done ? (
          <div className="alert alert--success" style={{ marginBottom: 0 }}>
            Password changed. All other sessions have been signed out — you will be asked
            to sign in again shortly.
          </div>
        ) : (
          <form onSubmit={submit} style={{ maxWidth: 420 }}>
            {error && (
              <div className="alert alert--error" role="alert">
                {error}
              </div>
            )}
            <label className="field">
              <span className="field__label">Current password</span>
              <input
                className="input"
                type="password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <label className="field">
              <span className="field__label">New password</span>
              <input
                className="input"
                type="password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
                autoComplete="new-password"
                minLength={policy.minLength}
                required
              />
              <span className="field__hint">{policy.hint}</span>
            </label>
            <label className="field">
              <span className="field__label">Confirm new password</span>
              <input
                className="input"
                type="password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                autoComplete="new-password"
                required
              />
            </label>
            <button className="btn btn--primary" type="submit" disabled={busy}>
              {busy ? "Changing…" : "Change password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
