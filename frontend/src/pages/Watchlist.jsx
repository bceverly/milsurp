/**
 * The listings this reader is following.
 *
 * A row is read against two things: what it costs now, and what happened to it
 * since the last email. The headline comes from the server rather than being
 * worked out here, so the page and the digest cannot disagree about whether
 * something happened — which they would, eventually, as two copies of the same
 * rule always do.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatMoney, formatRelative } from "../format.js";
import AuthImage from "../components/AuthImage.jsx";
import { Trash } from "../components/Icons.jsx";

export default function Watchlist() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  useTitle("Watchlist");

  const load = useCallback(() => {
    api
      .watchlist()
      .then(setRows)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const stop = async (itemId) => {
    try {
      await api.unwatch(itemId);
      setRows((current) => (current || []).filter((row) => row.item.id !== itemId));
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="page">
      <div className="page__head">
        <h1>Watchlist</h1>
        {rows && rows.length > 0 && (
          <span className="chip chip--neutral">
            {rows.length} listing{rows.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {error && <div className="alert alert--error">{error}</div>}
      {rows === null && !error && <p className="muted">Loading…</p>}

      {rows !== null && rows.length === 0 && (
        <div className="panel">
          <div className="panel__body">
            <p style={{ margin: 0 }}>
              Nothing here yet. Open a listing and press <strong>Watch</strong> to follow
              it — you will hear when its price moves or it sells, and you can name a
              price you would pay.
            </p>
          </div>
        </div>
      )}

      {rows !== null && rows.length > 0 && (
        <div className="panel">
          <div className="panel__body">
            <ul className="watchlist">
              {rows.map(
                ({ id, item, target_price: target, note, headline, created_at }) => (
                  <li key={id} className="watchlist__row">
                    <Link className="watchlist__link" to={`/items/${item.id}`}>
                      {item.thumbnail_url ? (
                        <AuthImage
                          className="watchlist__thumb"
                          src={item.thumbnail_url}
                          alt=""
                        />
                      ) : (
                        <span
                          className="watchlist__thumb watchlist__thumb--empty"
                          aria-hidden="true"
                        />
                      )}
                      <span className="watchlist__text">
                        {/* Only when there is something to say. A row with no
                          headline is the ordinary case and needs no chip
                          saying "nothing happened". */}
                        {headline && <span className="watchlist__news">{headline}</span>}
                        <span className="watchlist__title">{item.title}</span>
                        <span className="watchlist__meta">
                          {item.site_name}
                          <span>Watching since {formatRelative(created_at)}</span>
                          {target != null && (
                            <span className="watchlist__target">
                              Target {formatMoney(target, item.currency)}
                            </span>
                          )}
                        </span>
                        {note && <span className="watchlist__note">{note}</span>}
                      </span>
                      <span className="watchlist__price">
                        {item.current_price == null
                          ? "Call for price"
                          : formatMoney(item.current_price, item.currency)}
                        {item.is_sold && <span className="watchlist__sold">Sold</span>}
                        {!item.is_active && !item.is_sold && (
                          <span className="watchlist__sold">Gone</span>
                        )}
                      </span>
                    </Link>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={() => stop(item.id)}
                      aria-label={`Stop watching ${item.title}`}
                      title="Stop watching"
                    >
                      <Trash />
                    </button>
                  </li>
                ),
              )}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
