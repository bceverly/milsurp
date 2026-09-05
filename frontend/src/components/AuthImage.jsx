/**
 * An <img> for photos behind the authenticated API.
 *
 * Photos require an Authorization header, so they cannot be a plain `src`.
 * The bytes are fetched, turned into an object URL, and revoked on unmount or
 * when the source changes — without that revoke, scrolling a long grid would
 * leak a blob per card.
 */
import React, { useEffect, useState } from "react";
import { fetchImageObjectUrl } from "../api.js";
import { Image as ImageIcon } from "./Icons.jsx";

export default function AuthImage({ src, alt, className, onClick, loading }) {
  const [objectUrl, setObjectUrl] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!src) {
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
  }, [src]);

  if (!src || failed) {
    return (
      <div className="item-card__noimg" title="No photo available">
        <ImageIcon size={26} />
      </div>
    );
  }

  if (!objectUrl) {
    return <div className="item-card__noimg" aria-hidden="true" />;
  }

  return (
    <img
      src={objectUrl}
      alt={alt}
      className={className}
      onClick={onClick}
      loading={loading}
    />
  );
}
