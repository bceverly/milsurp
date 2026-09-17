/**
 * API client.
 *
 * **This file no longer holds the session.** It used to keep a bearer token in
 * `sessionStorage`, which meant any script running on the page could read it:
 * one cross-site scripting hole, anywhere in this frontend or in anything it
 * loads, handed over a working session. The session is now an `HttpOnly`
 * cookie the browser sends and no script can see.
 *
 * What that costs is CSRF. A cookie is attached to every request reaching this
 * origin, including ones another site caused, which a header-based token was
 * immune to by construction. Two things stand in for it: `SameSite=Strict` on
 * the cookie, and a token in a second, readable cookie that this file echoes
 * back in `X-CSRF-Token` on anything that changes something. An attacker's
 * page can cause a request; the same-origin policy stops it reading our cookie
 * to know what to echo.
 *
 * A 401 from any call notifies the auth context so the app falls back to the
 * sign-in screen instead of rendering broken pages.
 */

//: Written by the server alongside the session, readable on purpose.
const CSRF_COOKIE = "milsurp_csrf";
const CSRF_HEADER = "X-CSRF-Token";

//: Methods the server asks for the echo on. Kept in step with
//: `sessions.UNSAFE_METHODS`.
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let onUnauthorized = null;

function csrfToken() {
  // Read at call time rather than cached: signing in replaces it, and a stale
  // one fails every write with a 403 that looks like a permissions bug.
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${CSRF_COOKIE}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request(path, { method = "GET", body, signal, raw = false } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) {
    const csrf = csrfToken();
    if (csrf) headers[CSRF_HEADER] = csrf;
  }

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
      // The session is a cookie now, so it has to be sent. "same-origin" and
      // not "include": this API is only ever same-origin, and "include" would
      // attach credentials to a cross-origin call if one were ever added by
      // accident.
      credentials: "same-origin",
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Cannot reach the server. Check your connection.", 0, null);
  }

  if (response.status === 401) {
    if (onUnauthorized) onUnauthorized();
  }

  if (response.status === 204) return null;
  if (raw) return response;

  let payload = null;
  const type = response.headers.get("Content-Type") || "";
  if (type.includes("application/json")) {
    payload = await response.json().catch(() => null);
  }

  if (!response.ok) {
    const detail =
      (payload && (payload.detail || payload.message)) ||
      `Request failed (HTTP ${response.status}).`;
    // FastAPI validation errors arrive as a list of field problems.
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg || String(d)).join("; ")
      : String(detail);
    throw new ApiError(message, response.status, payload);
  }
  return payload;
}

/** Build a query string, dropping empties and expanding arrays into repeats. */
export function qs(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      value.forEach((entry) => search.append(key, String(entry)));
    } else if (typeof value === "boolean") {
      if (value) search.set(key, "true");
    } else {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  // --- auth ---
  // totpCode is undefined on the first exchange. An account with two-factor
  // answers that one with { two_factor_required: true } and no token; the page
  // then asks again with the code alongside the password it already has.
  logout: () => request("/api/auth/logout", { method: "POST" }),
  login: (username, password, totpCode) =>
    request("/api/auth/login", {
      method: "POST",
      body: { username, password, ...(totpCode ? { totp_code: totpCode } : {}) },
    }),
  me: () => request("/api/auth/me"),
  policy: () => request("/api/policy"),
  accessConfig: () => request("/api/access-request/config"),
  requestAccess: (payload) =>
    request("/api/access-request", { method: "POST", body: payload }),
  // --- two-factor ---
  totpStatus: () => request("/api/auth/totp"),
  totpStart: () => request("/api/auth/totp/start", { method: "POST" }),
  totpConfirm: (code) =>
    request("/api/auth/totp/confirm", { method: "POST", body: { code } }),
  totpDisable: (password) =>
    request("/api/auth/totp/disable", { method: "POST", body: { password } }),

  // --- corrections by hand ---
  itemOverride: (id) => request(`/api/items/${id}/override`),
  setItemOverride: (id, values) =>
    request(`/api/items/${id}/override`, { method: "PUT", body: values }),
  clearItemOverride: (id) => request(`/api/items/${id}/override`, { method: "DELETE" }),

  // --- sessions ---
  sessions: () => request("/api/auth/sessions"),
  revokeSession: (id) => request(`/api/auth/sessions/${id}`, { method: "DELETE" }),
  revokeOtherSessions: () =>
    request("/api/auth/sessions/revoke-others", { method: "POST" }),

  // --- audit log (admin) ---
  auditLog: (params = {}) => {
    const query = new URLSearchParams();
    if (params.action) query.set("action", params.action);
    if (params.limit) query.set("limit", String(params.limit));
    const suffix = query.toString();
    return request(`/api/audit${suffix ? `?${suffix}` : ""}`);
  },
  auditActions: () => request("/api/audit/actions"),

  // --- password reset by link ---
  // Named resetToken, not token: the module already has a `token` holding the
  // session's own, and two things called that in one file is how the wrong one
  // gets sent.
  checkResetLink: (resetToken) =>
    request(`/api/auth/reset/${encodeURIComponent(resetToken)}`),
  redeemResetLink: (resetToken, new_password) =>
    request("/api/auth/reset", {
      method: "POST",
      body: { token: resetToken, new_password },
    }),
  sendResetLink: (userId) =>
    request(`/api/users/${userId}/reset-link`, { method: "POST" }),

  changePassword: (current_password, new_password) =>
    request("/api/auth/password", {
      method: "POST",
      body: { current_password, new_password },
    }),

  // --- backups (admin) ---
  backups: () => request("/api/admin/backups"),
  updateBackups: (body) => request("/api/admin/backups", { method: "PATCH", body }),
  runBackup: () => request("/api/admin/backups/run", { method: "POST" }),

  // --- items ---
  items: (params) => request(`/api/items${qs(params)}`),
  item: (id) => request(`/api/items/${id}`),
  itemPrices: (id) => request(`/api/items/${id}/prices`),
  // Where this listing sits among the others of the same gun. Null for most
  // of them — it needs a matched model, a maker, a cartridge and three peers.
  itemPricePosition: (id) => request(`/api/items/${id}/price-position`),
  itemSimilar: (id) => request(`/api/items/${id}/similar`),

  watchlist: () => request("/api/watchlist"),
  // The object, not a string: request() does the JSON.stringify itself, and
  // stringifying here again posts a quoted string the server cannot read.
  watch: (itemId, body) =>
    request(`/api/watchlist/${itemId}`, { method: "PUT", body: body || {} }),
  unwatch: (itemId) => request(`/api/watchlist/${itemId}`, { method: "DELETE" }),

  // --- sites ---
  sites: () => request("/api/sites"),
  // Vendors the roadmap intends to read. No rows behind these, so they are
  // fetched once and never polled with the real ones.
  plannedSites: () => request("/api/sites/planned"),
  site: (id) => request(`/api/sites/${id}`),
  updateSite: (id, patch) =>
    request(`/api/sites/${id}`, { method: "PATCH", body: patch }),
  startScan: (id) => request(`/api/sites/${id}/scan`, { method: "POST" }),
  cancelScan: (id) => request(`/api/sites/${id}/scan/cancel`, { method: "POST" }),
  siteScans: (id, params) => request(`/api/sites/${id}/scans${qs(params)}`),

  // --- scans ---
  scans: (params) => request(`/api/scans${qs(params)}`),
  scan: (id) => request(`/api/scans/${id}`),

  // --- users ---
  users: () => request("/api/users"),
  createUser: (payload) => request("/api/users", { method: "POST", body: payload }),
  updateUser: (id, patch) =>
    request(`/api/users/${id}`, { method: "PATCH", body: patch }),
  deleteUser: (id) => request(`/api/users/${id}`, { method: "DELETE" }),

  // --- manufacturers ---
  manufacturers: (params = {}) => request(`/api/manufacturers${qs(params)}`),
  createManufacturer: (payload) =>
    request("/api/manufacturers", { method: "POST", body: payload }),
  updateManufacturer: (id, patch) =>
    request(`/api/manufacturers/${id}`, { method: "PATCH", body: patch }),
  deleteManufacturer: (id) => request(`/api/manufacturers/${id}`, { method: "DELETE" }),

  // --- what a kind of gun goes for, across every dealer at once ---
  market: (params = {}) => request(`/api/market${qs(params)}`),

  // --- a week in review of the catalog, nobody's filters applied ---
  changes: (params = {}) => request(`/api/changes${qs(params)}`),

  // --- classification rules: countries, caliber designations, accessories ---
  countries: (params = {}) => request(`/api/countries${qs(params)}`),
  createCountry: (payload) =>
    request("/api/countries", { method: "POST", body: payload }),
  updateCountry: (id, patch) =>
    request(`/api/countries/${id}`, { method: "PATCH", body: patch }),
  deleteCountry: (id) => request(`/api/countries/${id}`, { method: "DELETE" }),

  caliberDesignations: (params = {}) => request(`/api/caliber-designations${qs(params)}`),
  createCaliberDesignation: (payload) =>
    request("/api/caliber-designations", { method: "POST", body: payload }),
  updateCaliberDesignation: (id, patch) =>
    request(`/api/caliber-designations/${id}`, { method: "PATCH", body: patch }),
  deleteCaliberDesignation: (id) =>
    request(`/api/caliber-designations/${id}`, { method: "DELETE" }),

  classifierKeywords: (params = {}) => request(`/api/classifier-keywords${qs(params)}`),
  createClassifierKeyword: (payload) =>
    request("/api/classifier-keywords", { method: "POST", body: payload }),
  updateClassifierKeyword: (id, patch) =>
    request(`/api/classifier-keywords/${id}`, { method: "PATCH", body: patch }),
  deleteClassifierKeyword: (id) =>
    request(`/api/classifier-keywords/${id}`, { method: "DELETE" }),

  // --- the armory: manufacturers, models, calibers, and the approval gate ---
  armorySummary: () => request("/api/armory/summary"),
  armoryKinds: () => request("/api/armory/kinds"),
  armoryCountries: () => request("/api/armory/countries"),
  armoryModels: (params) => request(`/api/armory/models${qs(params)}`),
  armoryCalibers: (params) => request(`/api/armory/calibers${qs(params)}`),
  createArmoryRow: (table, payload) =>
    request(`/api/armory/${table}`, { method: "POST", body: payload }),
  updateArmoryRow: (table, id, patch) =>
    request(`/api/armory/${table}/${id}`, { method: "PATCH", body: patch }),
  deleteArmoryRow: (table, id) =>
    request(`/api/armory/${table}/${id}`, { method: "DELETE" }),
  promoteArmoryRows: (table, ids) =>
    request(`/api/armory/${table}/promote`, { method: "POST", body: { ids } }),
  sendArmoryRowsBack: (table, ids) =>
    request(`/api/armory/${table}/send-back`, { method: "POST", body: { ids } }),
  // Promote one of a row's own spellings to be its name. Not a rename: the old
  // name stays as an alias and the listings carrying it are restamped, which
  // is why it is a call of its own rather than a field on the edit form.
  setArmoryPrimary: (table, id, name) =>
    request(`/api/armory/${table}/${id}/primary`, { method: "POST", body: { name } }),
  // The other half of merging. A merge records what it took before it takes
  // it, so this gives back the links and the aliases rather than only
  // un-hiding the row; a row merged before that recording existed comes back
  // on a best-effort basis and says so.
  unmergeArmoryRow: (table, id) =>
    request(`/api/armory/${table}/${id}/unmerge`, { method: "POST" }),
  mergeArmoryRows: (table, source_id, target_id) =>
    request(`/api/armory/${table}/merge`, {
      method: "POST",
      body: { source_id, target_id },
    }),
  seedArmory: () => request("/api/armory/seed", { method: "POST" }),
  // Addressed by the audit event rather than by the row: the event is what
  // somebody is looking at when they decide to undo it.
  revertArmoryChange: (eventId) =>
    request(`/api/armory/revert/${eventId}`, { method: "POST" }),
  // A plain link rather than a fetch, like the item export and for the same
  // reason: the session is a cookie, so the browser authenticates the
  // navigation itself and the file lands in Downloads instead of in memory.
  armoryExportUrl: () => "/api/armory/export",
  emailArmoryExport: () => request("/api/armory/export/email", { method: "POST" }),

  // --- email preferences ---
  preferences: () => request("/api/preferences/email"),
  savePreferences: (payload) =>
    request("/api/preferences/email", { method: "PUT", body: payload }),
  sendTestDigest: () => request("/api/preferences/email/test", { method: "POST" }),
  emailHistory: (params) => request(`/api/preferences/email/history${qs(params)}`),
  emailBody: (id) => request(`/api/preferences/email/history/${id}`),
  clearResting: (siteId) =>
    request(`/api/sites/${siteId}/resting/clear`, { method: "POST" }),

  // --- saved searches ---
  savedSearches: () => request("/api/saved-searches"),
  createSavedSearch: (payload) =>
    request("/api/saved-searches", { method: "POST", body: payload }),
  updateSavedSearch: (id, patch) =>
    request(`/api/saved-searches/${id}`, { method: "PATCH", body: patch }),
  deleteSavedSearch: (id) => request(`/api/saved-searches/${id}`, { method: "DELETE" }),
  sendSavedSearch: (id) => request(`/api/saved-searches/${id}/send`, { method: "POST" }),

  // --- admin ---
  status: () => request("/api/admin/status"),
  allEmailHistory: (params) => request(`/api/admin/email/history${qs(params)}`),
  testSmtp: () => request("/api/admin/email/test-connection", { method: "POST" }),
};

/**
 * Photos require the Authorization header, so they cannot be used as a plain
 * <img src>. Fetch the bytes and hand back an object URL the caller revokes.
 */
export async function fetchImageObjectUrl(path, signal) {
  const response = await request(path, { raw: true, signal });
  if (!response.ok) throw new ApiError("Image unavailable", response.status, null);
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
