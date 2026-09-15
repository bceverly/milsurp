/**
 * Setting a new password from a one-time link an administrator sent.
 *
 * Unauthenticated, necessarily: whoever followed the link cannot sign in. The
 * link is checked before the form is shown, so somebody holding an expired one
 * is told so rather than choosing a password twice and then being refused.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { usePasswordPolicy, useTitle } from "../hooks.js";
import Insignia from "../components/Insignia.jsx";

export default function ResetPassword() {
  const { token } = useParams();
  const navigate = useNavigate();
  const policy = usePasswordPolicy();
  const [checking, setChecking] = useState(true);
  const [valid, setValid] = useState(false);
  const [username, setUsername] = useState(null);
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  useTitle("Set a new password");

  useEffect(() => {
    let canceled = false;
    api
      .checkResetLink(token)
      .then((result) => {
        if (canceled) return;
        setValid(Boolean(result?.valid));
        setUsername(result?.username || null);
      })
      .catch(() => !canceled && setValid(false))
      .finally(() => !canceled && setChecking(false));
    return () => {
      canceled = true;
    };
  }, [token]);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    if (next !== confirm) {
      setError("Those two passwords are not the same.");
      return;
    }
    setBusy(true);
    try {
      await api.redeemResetLink(token, next);
      setDone(true);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login__panel">
        <div className="login__brand">
          <Insignia size={56} />
          <h1>Milsurp Monitor</h1>
        </div>

        {checking && <div className="spinner" />}

        {!checking && !valid && (
          <>
            <div className="alert alert--error" role="alert">
              That link has expired or has already been used. Ask whoever sent it for
              another — they can send a fresh one in a moment.
            </div>
            <Link className="btn btn--block" to="/login">
              Back to sign in
            </Link>
          </>
        )}

        {!checking && valid && done && (
          <>
            <div className="alert alert--success">
              Your password is set. You have been signed out everywhere else — and if you
              use an authenticator app, you will still be asked for a code.
            </div>
            <button
              type="button"
              className="btn btn--primary btn--block"
              onClick={() => navigate("/login")}
            >
              Sign in
            </button>
          </>
        )}

        {!checking && valid && !done && (
          <form onSubmit={submit} noValidate>
            <p style={{ marginTop: 0 }}>
              Choose a new password{username ? ` for ${username}` : ""}. This link works
              once.
            </p>
            {error && (
              <div className="alert alert--error" role="alert">
                {error}
              </div>
            )}

            <label className="field">
              <span className="field__label">New password</span>
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
                required
                autoFocus
              />
              {policy?.requirements?.length > 0 && (
                <span className="field__hint">{policy.requirements.join(" · ")}</span>
              )}
            </label>

            <label className="field">
              <span className="field__label">Again, to be sure</span>
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                required
              />
            </label>

            <button
              className="btn btn--primary btn--block"
              type="submit"
              disabled={busy || !next || !confirm}
            >
              {busy ? "Setting…" : "Set my password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
