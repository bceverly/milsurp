import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";

//: Mirrors the backend defaults; used only until /api/policy answers.
export const DEFAULT_PASSWORD_POLICY = {
  password_min_length: 12,
  password_requirements: ["at least 12 characters"],
};

/**
 * Delay a rapidly-changing value.
 *
 * Used for the search box: without it every keystroke would be a request, and
 * the responses could land out of order.
 */
export function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** Run a callback on an interval, without restarting it when the callback changes. */
export function useInterval(callback, delayMs) {
  const saved = useRef(callback);
  useEffect(() => {
    saved.current = callback;
  }, [callback]);
  useEffect(() => {
    if (delayMs === null || delayMs === undefined) return undefined;
    const id = setInterval(() => saved.current(), delayMs);
    return () => clearInterval(id);
  }, [delayMs]);
}

/**
 * Server-side policy the UI needs for up-front validation.
 *
 * Fetched rather than hard-coded so that changing
 * `security.min_password_length` in the config file and restarting is
 * reflected in the form constraints without a frontend rebuild. Falls back to
 * the documented default if the request fails, so a form is never left
 * unusable.
 */
export function usePasswordPolicy() {
  const [policy, setPolicy] = useState(DEFAULT_PASSWORD_POLICY);
  useEffect(() => {
    let cancelled = false;
    api
      .policy()
      .then((result) => {
        if (!cancelled && result?.password_min_length) setPolicy(result);
      })
      .catch(() => {
        /* keep the defaults */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    minLength: policy.password_min_length,
    // Rendered verbatim: the server derives this from the same toggles it
    // enforces, so the guidance cannot drift from the rules.
    hint: `Must be ${(policy.password_requirements || []).join(", ")}.`,
  };
}

/** Set document.title, restoring it when the component unmounts. */
export function useTitle(title) {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} · Milsurp Monitor` : "Milsurp Monitor";
    return () => {
      document.title = previous;
    };
  }, [title]);
}
