import React, { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import Insignia from "../components/Insignia.jsx";
import RequestAccess from "../components/RequestAccess.jsx";

export default function Login() {
  const { user, loading, signIn } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    document.title = "Sign in · Milsurp Monitor";
  }, []);

  if (loading) {
    return (
      <div className="boot">
        <div className="spinner" />
      </div>
    );
  }
  if (user) return <Navigate to={location.state?.from || "/"} replace />;

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(username.trim(), password);
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
          <p>Military surplus listings, tracked across every vendor.</p>
        </div>

        <form onSubmit={submit} noValidate>
          {error && (
            <div className="alert alert--error" role="alert">
              {error}
            </div>
          )}

          <label className="field">
            <span className="field__label">Username</span>
            <input
              className="input"
              name="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck="false"
              required
              autoFocus
            />
          </label>

          <label className="field">
            <span className="field__label">Password</span>
            <input
              className="input"
              name="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          <button
            className="btn btn--primary btn--block"
            type="submit"
            disabled={busy || !username || !password}
          >
            {busy ? <span className="spinner" /> : null}
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {/* Production only — the component hides itself when the server says
            access requests are not enabled. */}
        <RequestAccess />
      </div>
    </div>
  );
}
