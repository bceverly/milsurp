import { useEffect, useState } from "react";
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
  //: Set once the server has asked for a code. The password stays in state and
  //: is sent again with it: the second exchange is a whole sign-in, not a
  //: continuation of a half-open one, so there is no session to hold on to
  //: between the two.
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState("");

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
  // `restoring` is what tells the shell to watch the next few requests: if the
  // page they were on is the reason they were thrown out, sending them
  // straight back to it would land them on the same broken screen.
  if (user) {
    const from = location.state?.from;
    return from ? (
      <Navigate to={from} replace state={{ restoring: from }} />
    ) : (
      <Navigate to="/" replace />
    );
  }

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const signedIn = await signIn(username.trim(), password, code.trim() || undefined);
      if (signedIn === null) {
        // Not an error: the password was right and the server wants the other
        // half. Showing a red box here would say the opposite.
        setNeedsCode(true);
        setBusy(false);
      }
    } catch (err) {
      setError(err.message);
      setBusy(false);
      // A wrong code clears the field and leaves the prompt up. Clearing the
      // password too would make somebody retype it for a mistyped digit.
      setCode("");
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

          {needsCode && (
            <label className="field">
              <span className="field__label">Authenticator code</span>
              <input
                className="input"
                name="totp"
                /* text, not number: a leading zero is part of the code and a
                   number input eats it, and the spinner arrows are nonsense
                   here. inputMode gets the numeric keypad on a phone. */
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                autoFocus
              />
              <span className="field__hint">
                The six digits from your authenticator app — or one of your recovery
                codes, if you do not have your phone.
              </span>
            </label>
          )}

          <button
            className="btn btn--primary btn--block"
            type="submit"
            disabled={busy || !username || !password || (needsCode && !code.trim())}
          >
            {busy ? <span className="spinner" /> : null}
            {busy ? "Signing in…" : needsCode ? "Verify" : "Sign in"}
          </button>
        </form>

        {/* Production only — the component hides itself when the server says
            access requests are not enabled. */}
        <RequestAccess />
      </div>
    </div>
  );
}
