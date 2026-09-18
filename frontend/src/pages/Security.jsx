/**
 * Security settings: the password, two-factor authentication, and where this
 * account is signed in.
 *
 * A page of their own rather than a section of the digest page, where they
 * used to live. The password panel sat under a nav item called "Email digest"
 * since it was written, and adding two-factor beside it made that worse rather
 * than better: nobody looking for the two-factor switch clicks Email digest,
 * and somebody did go looking and did not find it.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { usePasswordPolicy, useTitle } from "../hooks.js";
import { formatDateTime, formatRelative, timeTitle } from "../format.js";
import * as push from "../push.js";

export default function SecurityPage() {
  useTitle("Security settings");
  return (
    <div className="page">
      <div className="page-head">
        <h1>Security settings</h1>
      </div>
      <TwoFactorPanel />
      <NotificationsPanel />
      <SessionsPanel />
      <PasswordPanel />
    </div>
  );
}

/**
 * Notifications on this browser.
 *
 * Per *device*, not per account, and the wording says so throughout: the same
 * person reading this on a phone and a desktop has to turn it on twice, and
 * nothing here would make sense to somebody who thought otherwise.
 *
 * The **Send a test** button is not a nicety. Four things have to line up —
 * browser support, a secure origin, permission, a registered service worker —
 * and when one of them is wrong everything still looks fine: the switch says
 * On and no notification ever arrives. One notification landing is the only
 * proof worth having.
 */
function NotificationsPanel() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    api
      .pushStatus()
      .then(setStatus)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  async function turnOn() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await push.subscribe(status.public_key);
      setNotice(
        "This device will be notified when a watched listing reaches your price.",
      );
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function turnOff(subscriptionId) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await push.unsubscribe(subscriptionId);
      setNotice("Stopped. This device will not be notified.");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.sendTestPush();
      setNotice(
        `Sent to ${result.subscriptions.length} device(s). If nothing appeared, this ` +
          `browser is blocking notifications for the site.`,
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;

  // Two different "no" answers, and conflating them would send somebody to
  // change a browser setting over a server that has no keys.
  if (!status.available) {
    return (
      <div className="panel">
        <div className="panel__head">
          <h2>Notifications</h2>
          <span className="chip chip--neutral">Unavailable</span>
        </div>
        <div className="panel__body">
          <p>
            This server has no push keys, so it cannot send notifications. An
            administrator can generate a pair with <code>milsurp secrets</code>.
          </p>
        </div>
      </div>
    );
  }

  const devices = status.subscriptions || [];

  return (
    <div className="panel">
      <div className="panel__head">
        <h2>Notifications</h2>
        <span className={`chip ${devices.length ? "chip--success" : "chip--neutral"}`}>
          {devices.length ? `${devices.length} device(s)` : "Off"}
        </span>
      </div>
      <div className="panel__body">
        {error && (
          <div className="alert alert--error" role="alert">
            {error}
          </div>
        )}
        {notice && <div className="alert alert--success">{notice}</div>}

        <p>
          Be told the moment a watched listing reaches the price you named, without
          waiting for the digest. This is per device: turning it on here covers this
          browser and no other.
        </p>

        {!push.supported() ? (
          <p className="field__hint">
            This browser cannot show notifications from a website.
          </p>
        ) : (
          <div className="page-head__actions" style={{ marginBottom: 12 }}>
            <button className="btn btn--primary" disabled={busy} onClick={turnOn}>
              Turn on for this device
            </button>
            {devices.length > 0 && (
              <button className="btn btn--secondary" disabled={busy} onClick={test}>
                Send a test
              </button>
            )}
          </div>
        )}

        {devices.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Device</th>
                  <th>Added</th>
                  <th>Last notified</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {devices.map((device) => (
                  <tr key={device.id}>
                    <td>{device.user_agent || "Unknown browser"}</td>
                    <td title={timeTitle(device.created_at)}>
                      {device.created_at ? formatRelative(device.created_at) : "—"}
                    </td>
                    <td title={timeTitle(device.last_used_at)}>
                      {device.last_used_at
                        ? formatRelative(device.last_used_at)
                        : "never"}
                    </td>
                    <td className="table__actions">
                      <button
                        className="btn btn--ghost btn--sm"
                        disabled={busy}
                        onClick={() => turnOff(device.id)}
                      >
                        Turn off
                      </button>
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

/**
 * Two-factor authentication.
 *
 * Enrollment is two steps here because it is two steps on the server, and the
 * gap is the point: the secret is shown, and only a code typed back from the
 * phone turns it on. Somebody who closes this tab halfway has changed nothing.
 *
 * The secret is offered as text rather than a QR code. A QR would mean a new
 * frontend dependency for one screen, in an app with three; on a phone the
 * otpauth link opens the authenticator directly, and everywhere else the
 * grouped secret is typed in once.
 */
function TwoFactorPanel() {
  const [status, setStatus] = useState(null);
  const [enrolling, setEnrolling] = useState(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState(null);
  const [password, setPassword] = useState("");
  const [turningOff, setTurningOff] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .totpStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  useEffect(load, [load]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setEnrolling(await api.totpStart());
      setCode("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.totpConfirm(code.trim());
      setCodes(result.codes);
      setEnrolling(null);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function disable(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.totpDisable(password);
      setPassword("");
      setTurningOff(false);
      setCodes(null);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel__head">
        <h2>Two-factor authentication</h2>
        {status && (
          <span className={`chip ${status.enabled ? "chip--success" : "chip--neutral"}`}>
            {status.enabled ? "On" : "Off"}
          </span>
        )}
      </div>
      <div className="panel__body">
        {error && (
          <div className="alert alert--error" role="alert">
            {error}
          </div>
        )}

        {/* Shown once, and there is deliberately no way back to them: a list of
            second factors retrievable by anybody already signed in is not a
            second factor. */}
        {codes && (
          <div className="alert alert--success">
            <p style={{ marginTop: 0 }}>
              <strong>Two-factor is on. Save these recovery codes now.</strong> Each works
              once, and this is the only time they are shown. They are how you get in if
              you lose your phone.
            </p>
            <ul className="recovery-codes">
              {codes.map((one) => (
                <li key={one}>{one}</li>
              ))}
            </ul>
            <button type="button" className="btn btn--sm" onClick={() => setCodes(null)}>
              I have saved them
            </button>
          </div>
        )}

        {status && !status.enabled && !enrolling && !codes && (
          <>
            <p style={{ marginTop: 0 }}>
              A password is the only thing in front of this account. Two-factor adds a
              six-digit code from your phone, which an attacker with the password still
              does not have.
            </p>
            <button
              type="button"
              className="btn btn--primary"
              onClick={start}
              disabled={busy}
            >
              Turn on two-factor
            </button>
          </>
        )}

        {enrolling && (
          <form onSubmit={confirm} noValidate>
            <p style={{ marginTop: 0 }}>
              Add this to your authenticator app, then type the code it shows to finish.
              Nothing changes until you do.
            </p>
            <p>
              <a href={enrolling.otpauth_uri} className="btn btn--sm">
                Open in an authenticator app
              </a>{" "}
              <span className="field__hint">(on this device)</span>
            </p>
            <p className="field__hint" style={{ marginBottom: 4 }}>
              Or type this secret in by hand:
            </p>
            <p className="totp-secret">{enrolling.secret_grouped}</p>
            <label className="field">
              <span className="field__label">Code from the app</span>
              <input
                className="input"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                required
                autoFocus
              />
            </label>
            <button
              className="btn btn--primary"
              type="submit"
              disabled={busy || !code.trim()}
            >
              {busy ? "Checking…" : "Finish turning it on"}
            </button>{" "}
            <button type="button" className="btn" onClick={() => setEnrolling(null)}>
              Cancel
            </button>
          </form>
        )}

        {status?.enabled && !turningOff && (
          <>
            <p style={{ marginTop: 0 }}>
              On since {formatDateTime(status.confirmed_at)}.{" "}
              <strong>{status.recovery_codes_left}</strong> recovery code
              {status.recovery_codes_left === 1 ? "" : "s"} left.
            </p>
            <button type="button" className="btn" onClick={() => setTurningOff(true)}>
              Turn off two-factor
            </button>
          </>
        )}

        {turningOff && (
          <form onSubmit={disable} noValidate>
            {/* The password, because the thing being removed is what protects
                the account when the password is already known to somebody
                else. A live session alone must not be enough to undo it. */}
            <label className="field">
              <span className="field__label">Confirm your password</span>
              <input
                className="input"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                autoFocus
              />
            </label>
            <button
              className="btn btn--danger"
              type="submit"
              disabled={busy || !password}
            >
              {busy ? "Turning off…" : "Turn off two-factor"}
            </button>{" "}
            <button
              type="button"
              className="btn"
              onClick={() => {
                setTurningOff(false);
                setPassword("");
              }}
            >
              Cancel
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

/**
 * Where this account is signed in, and how to end one of those places.
 *
 * The session used to be a token this page could not enumerate -- there was
 * nothing written down, so "where am I signed in?" had no answer and the only
 * revocation available ended every session at once. A sign-in is a row now.
 *
 * **Which one is this browser is the first thing anybody looks for**, so the
 * current session is labelled and its button says "Sign out" rather than
 * "Revoke": ending the one you are using is a legitimate thing to want and a
 * bad thing to do by accident.
 */
function SessionsPanel() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .sessions()
      .then(setRows)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  async function end(id, isCurrent) {
    setError(null);
    setBusy(true);
    try {
      await api.revokeSession(id);
      // Ending the current one signs this tab out; any request after it gets a
      // 401 and the app falls back to the sign-in screen on its own.
      if (!isCurrent) load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function endOthers() {
    setError(null);
    setBusy(true);
    try {
      await api.revokeOtherSessions();
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const others = (rows || []).filter((row) => !row.current).length;

  return (
    <div className="panel">
      <div className="panel__head">
        <h2>Signed in</h2>
        {others > 0 && (
          <button
            type="button"
            className="btn btn--secondary"
            onClick={endOthers}
            disabled={busy}
          >
            Sign out everywhere else
          </button>
        )}
      </div>
      <div className="panel__body">
        {error && <p className="alert alert--danger">{error}</p>}
        {rows === null && !error && <p className="muted">Loading…</p>}
        {rows !== null && rows.length === 0 && (
          <p className="muted">No other sessions.</p>
        )}
        {rows !== null && rows.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Browser</th>
                <th>Address</th>
                <th>Signed in</th>
                <th>Last used</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    {row.user_agent || "Unknown"}
                    {row.current && <span className="chip chip--info">This browser</span>}
                  </td>
                  <td>{row.ip_address || "—"}</td>
                  <td>{row.created_at ? formatDateTime(row.created_at) : "—"}</td>
                  <td>{row.last_seen_at ? formatDateTime(row.last_seen_at) : "—"}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--ghost"
                      onClick={() => end(row.id, row.current)}
                      disabled={busy}
                    >
                      {row.current ? "Sign out" : "Revoke"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
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
