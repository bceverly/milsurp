/**
 * "Request access" form, shown on the sign-in screen in production only.
 *
 * Nothing here creates an account — the details are emailed to the support
 * address and an administrator decides. The reCAPTCHA script is loaded lazily,
 * only when the form is actually opened, so the sign-in page stays free of
 * third-party JavaScript for the people who just want to log in.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Modal from "./Modal.jsx";
import { Check, Mail } from "./Icons.jsx";

const RECAPTCHA_SRC = "https://www.google.com/recaptcha/api.js";

/** Load the reCAPTCHA v3 script once per page, resolving when grecaptcha is up. */
function loadRecaptcha(siteKey) {
  if (window.grecaptcha?.execute) return Promise.resolve(window.grecaptcha);
  if (window.__milsurpRecaptchaPromise) return window.__milsurpRecaptchaPromise;

  window.__milsurpRecaptchaPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${RECAPTCHA_SRC}?render=${encodeURIComponent(siteKey)}`;
    script.async = true;
    script.defer = true;
    script.onload = () => {
      if (!window.grecaptcha) {
        reject(new Error("reCAPTCHA failed to initialize."));
        return;
      }
      window.grecaptcha.ready(() => resolve(window.grecaptcha));
    };
    script.onerror = () =>
      reject(new Error("Could not load the verification challenge."));
    document.head.appendChild(script);
  });
  return window.__milsurpRecaptchaPromise;
}

export default function RequestAccess() {
  const [config, setConfig] = useState(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    message: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    // A 404/500 here just means the feature is off; the sign-in page must
    // still work, so failures are swallowed.
    api
      .accessConfig()
      .then((result) => {
        if (mounted.current) setConfig(result);
      })
      .catch(() => {});
    return () => {
      mounted.current = false;
    };
  }, []);

  // Warm the script as soon as the dialog opens, so submitting is instant.
  useEffect(() => {
    if (open && config?.recaptcha_site_key) {
      loadRecaptcha(config.recaptcha_site_key).catch(() => {});
    }
  }, [open, config]);

  const set = useCallback(
    (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value })),
    [],
  );

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      let token = null;
      if (config?.recaptcha_site_key) {
        const grecaptcha = await loadRecaptcha(config.recaptcha_site_key);
        token = await grecaptcha.execute(config.recaptcha_site_key, {
          action: "access_request",
        });
      }
      const result = await api.requestAccess({
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        email: form.email.trim(),
        message: form.message.trim() || null,
        recaptcha_token: token,
      });
      setSent(result.message);
    } catch (err) {
      setError(err.message);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  if (!config?.enabled) return null;

  function close() {
    setOpen(false);
    // Reset for a second attempt after the dialog has animated away.
    setTimeout(() => {
      setSent(false);
      setError(null);
    }, 200);
  }

  return (
    <>
      <div className="login__alt">
        <span>Don&rsquo;t have an account?</span>
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => setOpen(true)}
        >
          Request access
        </button>
      </div>

      {open && (
        <Modal
          title="Request access"
          onClose={close}
          footer={
            sent ? (
              <button className="btn btn--primary" onClick={close}>
                Close
              </button>
            ) : (
              <>
                <button className="btn btn--secondary" onClick={close}>
                  Cancel
                </button>
                <button
                  className="btn btn--primary"
                  type="submit"
                  form="access-form"
                  disabled={busy}
                >
                  {busy ? "Sending…" : "Send request"}
                </button>
              </>
            )
          }
        >
          {sent ? (
            <div className="alert alert--success" style={{ marginBottom: 0 }}>
              <Check size={16} /> {sent}
            </div>
          ) : (
            <form id="access-form" onSubmit={submit} noValidate>
              {error && (
                <div className="alert alert--error" role="alert">
                  {error}
                </div>
              )}

              <p style={{ marginTop: 0, fontSize: 13.5, color: "var(--ink-500)" }}>
                Your details are emailed to the site administrator, who will set up an
                account and reply. Nothing is created automatically.
              </p>

              <div className="form-row form-row--2">
                <label className="field">
                  <span className="field__label">First name</span>
                  <input
                    className="input"
                    value={form.first_name}
                    onChange={set("first_name")}
                    autoComplete="given-name"
                    maxLength={64}
                    required
                  />
                </label>
                <label className="field">
                  <span className="field__label">Last name</span>
                  <input
                    className="input"
                    value={form.last_name}
                    onChange={set("last_name")}
                    autoComplete="family-name"
                    maxLength={64}
                    required
                  />
                </label>
              </div>

              <label className="field">
                <span className="field__label">Email address</span>
                <input
                  className="input"
                  type="email"
                  value={form.email}
                  onChange={set("email")}
                  autoComplete="email"
                  required
                />
              </label>

              <label className="field">
                <span className="field__label">Anything else? (optional)</span>
                <textarea
                  className="textarea"
                  rows={3}
                  value={form.message}
                  onChange={set("message")}
                  maxLength={1000}
                  placeholder="How you heard about the site, what you collect…"
                />
              </label>

              {config.recaptcha_site_key && (
                <p style={{ fontSize: 11.5, color: "var(--ink-400)", margin: 0 }}>
                  Protected by reCAPTCHA. Google&rsquo;s{" "}
                  <a
                    href="https://policies.google.com/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Privacy Policy
                  </a>{" "}
                  and{" "}
                  <a
                    href="https://policies.google.com/terms"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Terms
                  </a>{" "}
                  apply.
                </p>
              )}
            </form>
          )}
        </Modal>
      )}
    </>
  );
}
