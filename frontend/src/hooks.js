import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
    let canceled = false;
    api
      .policy()
      .then((result) => {
        if (!canceled && result?.password_min_length) setPolicy(result);
      })
      .catch(() => {
        /* keep the defaults */
      });
    return () => {
      canceled = true;
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

/**
 * `useSearchParams`, but the value you just wrote is visible immediately.
 *
 * React Router 7 wraps every navigation in `React.startTransition`, so the
 * render that follows a click still sees the *old* search params. For a
 * controlled input that is a visible defect: clicking a filter checkbox ticks
 * the box natively, React resets it to match the stale props, and only then
 * does the transition commit and tick it again. The filter rail flickers, and
 * on a slow render it stays wrong long enough to look broken.
 *
 * Holding the pending value until the router catches up fixes the controls
 * while leaving the transition to do its real job — keeping the expensive part,
 * re-rendering the item grid, off the interaction's critical path.
 */
export function useOptimisticSearchParams() {
  const [params, setParams] = useSearchParams();
  const [pending, setPending] = useState(null);

  // The router has caught up (or the user navigated some other way), so the
  // optimistic copy has nothing left to say.
  useEffect(() => {
    setPending(null);
  }, [params]);

  const set = useCallback(
    (next, options) => {
      setPending(new URLSearchParams(next));
      setParams(next, options);
    },
    [setParams],
  );

  return [pending ?? params, set];
}
