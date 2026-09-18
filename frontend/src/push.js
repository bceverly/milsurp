/**
 * Turning notifications on for this browser, and off again.
 *
 * Four things have to line up and any one of them can fail silently, which is
 * why every step here reports what went wrong rather than returning false:
 * the browser must support push, the page must be on a secure origin, the
 * person must grant permission, and the service worker must register.
 *
 * The VAPID public key travels from the server as base64url and has to reach
 * `subscribe()` as a Uint8Array. That conversion is the single most common
 * reason a working server and a working browser still produce nothing.
 */
import { api } from "./api.js";

/** Whether this browser could ever do it. Checked before anything is offered. */
export function supported() {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/**
 * base64url → Uint8Array.
 *
 * `atob` wants standard base64 with padding; the key is sent unpadded and
 * URL-safe, because that is how every other field in these RFCs is written.
 */
function decodeKey(base64url) {
  const padded = base64url.padEnd(
    base64url.length + ((4 - (base64url.length % 4)) % 4),
    "=",
  );
  const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function worker() {
  // `/sw.js` and not a hashed bundle path: a service worker's scope is the
  // directory it is served from, and one under /assets/ could only control
  // /assets/.
  return navigator.serviceWorker.register("/sw.js", { scope: "/" });
}

/**
 * Subscribe this browser. Returns the stored subscription.
 *
 * Throws with a sentence worth showing. "Permission denied" from the browser
 * is terse and, worse, sticky — a person who dismissed the prompt once cannot
 * be asked again by this page, and has to change it in browser settings. So
 * that case says so.
 */
export async function subscribe(publicKey) {
  if (!supported()) {
    throw new Error("This browser cannot show notifications from a website.");
  }
  if (!window.isSecureContext) {
    throw new Error("Notifications need a secure connection (https).");
  }

  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error(
      permission === "denied"
        ? "This browser is blocking notifications for this site. Turn them back on in its site settings — the page cannot ask again."
        : "Notifications were not turned on.",
    );
  }

  const registration = await worker();
  await navigator.serviceWorker.ready;

  // An existing subscription is reused rather than replaced: the browser hands
  // back the same one anyway, and unsubscribing first would invalidate an
  // endpoint the server already has.
  const existing = await registration.pushManager.getSubscription();
  const subscription =
    existing ||
    (await registration.pushManager.subscribe({
      // Required to be true by every browser that implements this: a silent
      // push is not allowed, and asking for one fails outright.
      userVisibleOnly: true,
      applicationServerKey: decodeKey(publicKey),
    }));

  const raw = subscription.toJSON();
  return api.subscribePush({
    endpoint: raw.endpoint,
    p256dh: raw.keys.p256dh,
    auth: raw.keys.auth,
  });
}

/**
 * Stop this browser receiving them.
 *
 * Both halves, and in this order: the browser's own subscription is canceled
 * first so no message can arrive after the server has forgotten where to send
 * it, and the server row goes second. The reverse order leaves a window where
 * a notification arrives for a device the server no longer lists.
 */
export async function unsubscribe(subscriptionId) {
  if (supported()) {
    const registration = await navigator.serviceWorker.getRegistration("/");
    const existing = await registration?.pushManager.getSubscription();
    if (existing) await existing.unsubscribe();
  }
  if (subscriptionId) await api.deletePushSubscription(subscriptionId);
}
