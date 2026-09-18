/**
 * The service worker, whose entire job is to be awake when the page is not.
 *
 * A push message arrives at the browser whether or not this site is open — that
 * is the point of push and the reason a service worker exists at all. It is
 * deliberately tiny: it shows what the server sent and opens what the server
 * pointed at, and it holds no application logic, because a bug in here is a bug
 * that keeps running after every tab is closed and is updated only when the
 * browser decides to fetch this file again.
 *
 * It caches nothing. An offline cache would be a second, silent copy of the
 * application with its own idea of which version it is, and this app is a
 * catalog of other people's stock — the thing it must never do is show a price
 * that is no longer true.
 */

self.addEventListener("push", (event) => {
  // A push with no data is legitimate — services send them — and the right
  // answer is a generic notification rather than a crash in a worker nobody
  // can see the console of.
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }

  const title = payload.title || "Milsurp Monitor";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: payload.body || "Something you are watching has changed.",
      icon: "/favicon.svg",
      badge: "/favicon.svg",
      // Collapses repeats: a second alert replaces the first rather than
      // stacking, which is what somebody wants on a lock screen.
      tag: payload.tag || "milsurp-watch",
      data: { url: payload.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/", self.location.origin);

  // Focus a tab that already has the app open rather than opening a second
  // one. Somebody tapping a price alert wants the listing, not a fresh copy of
  // a site they already had.
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clients) => {
        for (const client of clients) {
          if (new URL(client.url).origin === target.origin && "focus" in client) {
            client.navigate(target.href);
            return client.focus();
          }
        }
        return self.clients.openWindow(target.href);
      }),
  );
});
