/**
 * API client.
 *
 * The bearer token is held in memory and mirrored into sessionStorage rather
 * than localStorage: sessionStorage is cleared when the tab closes, which keeps
 * a forgotten session on a shared machine from outliving the browsing session.
 * A 401 from any call clears it and notifies the auth context so the app can
 * fall back to the sign-in screen instead of rendering broken pages.
 */

const TOKEN_KEY = "milsurp.token";

let token = null;
let onUnauthorized = null;

function readStoredToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    // Private mode or blocked storage: fall back to memory only.
    return null;
  }
}

export function setToken(value) {
  token = value;
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* memory-only session */
  }
}

export function getToken() {
  if (token === null) token = readStoredToken();
  return token;
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
  const current = getToken();
  if (current) headers.Authorization = `Bearer ${current}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
      // The token travels in a header, so no cookies are needed; omitting
      // credentials also means CSRF is not reachable against this API.
      credentials: "omit",
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Cannot reach the server. Check your connection.", 0, null);
  }

  if (response.status === 401) {
    setToken(null);
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
  login: (username, password) =>
    request("/api/auth/login", { method: "POST", body: { username, password } }),
  me: () => request("/api/auth/me"),
  policy: () => request("/api/policy"),
  accessConfig: () => request("/api/access-request/config"),
  requestAccess: (payload) =>
    request("/api/access-request", { method: "POST", body: payload }),
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
  mergeArmoryRows: (table, source_id, target_id) =>
    request(`/api/armory/${table}/merge`, {
      method: "POST",
      body: { source_id, target_id },
    }),
  seedArmory: () => request("/api/armory/seed", { method: "POST" }),

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
