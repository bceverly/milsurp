/**
 * An <img> for photos behind the authenticated API.
 *
 * Photos require an Authorization header, so they cannot be a plain `src`.
 * The bytes are fetched, turned into an object URL, and revoked on unmount or
 * when the source changes — without that revoke, scrolling a long grid would
 * leak a blob per card.
 *
 * **`loading="lazy"` defers the fetch, not just the decode.** It used to be
 * passed straight to the <img> underneath, where it did nothing at all: the
 * bytes had already been fetched by the effect below before the browser was
 * ever given a chance to defer anything. On a 192-card page that meant 192
 * simultaneous requests, each one costing an auth check, a database
 * connection and a threadpool slot on the server. The server has 15
 * connections and 40 threads, so most of them queued; past 30 seconds the
 * proxy in front gave up and the browser was shown a 504. The listing you
 * were actually trying to open was somewhere in that queue.
 *
 * So the fetch waits until the element is near the viewport. Cards above the
 * fold still load at once; the rest arrive as they are scrolled to, which is
 * a dozen requests instead of two hundred. An image with no `loading="lazy"`
 * — a detail page's hero shot, a gallery frame — is unchanged and fetches
 * immediately, because there is exactly one of it and waiting would only
 * make the page feel slower.
 */
import { useEffect, useRef, useState } from "react";
import { fetchImageObjectUrl } from "../api.js";
import { Image as ImageIcon } from "./Icons.jsx";

/**
 * How far outside the viewport counts as "near".
 *
 * Generous on purpose: the point is that the image has arrived by the time it
 * is scrolled to, not that the request is delayed as long as possible.
 */
const NEARBY = "400px";

export default function AuthImage({ src, alt, className, loading }) {
  const defer = loading === "lazy";
  const [objectUrl, setObjectUrl] = useState(null);
  const [failed, setFailed] = useState(false);
  // Anything not deferred starts wanted, so its fetch runs on the first pass.
  const [wanted, setWanted] = useState(!defer);
  const holder = useRef(null);

  // A new src on a deferred image has to prove itself visible again, or a
  // recycled card would fetch the replacement while still off screen.
  useEffect(() => {
    setWanted(!defer);
  }, [src, defer]);

  useEffect(() => {
    if (!defer || wanted || !src) return undefined;
    const node = holder.current;
    // No node to watch, or a browser without the observer: fetch rather than
    // leave a permanent blank. Failing open is the right way round here.
    if (!node || typeof IntersectionObserver === "undefined") {
      setWanted(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setWanted(true);
          observer.disconnect();
        }
      },
      { rootMargin: NEARBY },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [defer, wanted, src]);

  useEffect(() => {
    if (!src || !wanted) {
      setObjectUrl(null);
      return undefined;
    }
    let revoked = false;
    let created = null;
    const controller = new AbortController();
    setFailed(false);

    fetchImageObjectUrl(src, controller.signal)
      .then((url) => {
        if (revoked) {
          URL.revokeObjectURL(url);
          return;
        }
        created = url;
        setObjectUrl(url);
      })
      .catch((error) => {
        if (error.name !== "AbortError") setFailed(true);
      });

    return () => {
      revoked = true;
      controller.abort();
      if (created) URL.revokeObjectURL(created);
      setObjectUrl(null);
    };
  }, [src, wanted]);

  // **The stand-ins wear the caller's class too.** `item-card__noimg` is
  // `width: 100%; height: 100%`, which is right inside a card's fixed media
  // frame and ruinous anywhere else: dropped into a flex row it claims the
  // whole row and shoves the text and the price off to the right, and the
  // row only straightens out if and when the photo arrives. So the caller's
  // class rides along and sets the size, exactly as it does on the <img>.
  // Every such class is declared after `item-card__noimg` in layout.css, so
  // it wins on width and height without needing to shout about it.
  const standIn = ["item-card__noimg", className].filter(Boolean).join(" ");

  if (!src || failed) {
    return (
      <div className={standIn} title="No photo available">
        <ImageIcon size={26} />
      </div>
    );
  }

  // The placeholder carries the ref: it is what the observer watches while
  // the image is still off screen, so it has to be rendered, not skipped.
  if (!objectUrl) {
    return <div className={standIn} ref={holder} aria-hidden="true" />;
  }

  return <img src={objectUrl} alt={alt} className={className} loading={loading} />;
}
