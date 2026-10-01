/**
 * The cart on a browse card or row: put a listing on the wishlist, or take it
 * off, without opening it.
 *
 * A sibling of the card's link rather than inside it, since a button inside a
 * link is two controls in one and a click on it would open the listing too.
 * Optimistic: it fills at once and empties again if the server says no.
 */
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Cart } from "./Icons.jsx";

export default function WishButton({ item, className = "" }) {
  const [wished, setWished] = useState(Boolean(item.wishlisted));
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => setWished(Boolean(item.wishlisted)), [item.id, item.wishlisted]);

  const toggle = async () => {
    const next = !wished;
    setWished(next);
    setBusy(true);
    setFailed(false);
    try {
      if (next) await api.wish(item.id);
      else await api.unwish(item.id);
    } catch {
      setWished(!next);
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const label = wished
    ? `On your wishlist: ${item.title}`
    : `Add to wishlist: ${item.title}`;
  return (
    <button
      type="button"
      className={`wish-button ${wished ? "wish-button--on" : ""} ${className}`}
      onClick={toggle}
      disabled={busy}
      aria-pressed={wished}
      aria-label={label}
      title={failed ? "Could not change the wishlist" : label}
    >
      <Cart size={16} />
    </button>
  );
}
