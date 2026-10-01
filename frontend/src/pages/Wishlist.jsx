/**
 * The guns this reader means to buy, added up.
 *
 * Each line is priced to the door -- the shelf price, the shop's shipping and
 * the dealer's transfer fee -- and set against what a gun of that model in
 * that condition is worth, so each line and the whole list say whether the
 * money would hold its value. The arithmetic is the server's (see
 * services/wishlist.py); this page shows it and says what it is missing.
 *
 * The transfer fee, "I hold a C&R license", the budget and the alerts switch
 * are set here, beside the totals they change, rather than on a settings page:
 * they are what turns the list into a plan.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatMoney } from "../format.js";
import { COLLATOR } from "../sorting.js";
import AuthImage from "../components/AuthImage.jsx";
import SortHeader from "../components/SortHeader.jsx";
import { Box, Download, Trash } from "../components/Icons.jsx";

//: What each sortable column reads off a line. A missing figure sorts last
//: whichever way round, rather than as nought.
const SORT_VALUES = {
  added: (line) => line.added_at,
  name: (line) => line.item.title,
  price: (line) => line.price,
  total: (line) => line.total,
  worth: (line) => line.valuation?.estimate ?? null,
  profit: (line) => line.profit,
};

/** "+$120" or "−$45", colored, or a dash when there is nothing to compare. */
function Profit({ value }) {
  if (value == null) return <span className="muted">—</span>;
  const gain = value >= 0;
  return (
    <strong className={gain ? "wishlist-gain" : "wishlist-loss"}>
      {gain ? "+" : "−"}
      {formatMoney(Math.abs(value))}
    </strong>
  );
}

/** Why this line has the fee it has, in a few words. */
function feeWords(line) {
  if (line.fee_waived) return "C&R, no dealer";
  if (line.fee_missing) return "Set your fee above";
  if (line.curio === "unknown") return "C&R status unknown";
  return null;
}

/** "↓ $50 since added", or nothing when it has not moved. */
function SinceAdded({ change }) {
  if (!change) return null;
  const down = change < 0;
  return (
    <div className={`collection-sub ${down ? "wishlist-gain" : "wishlist-loss"}`}>
      {down ? "↓" : "↑"} {formatMoney(Math.abs(change))} since added
    </div>
  );
}

function Line({ line, onRemove, onBought, busy }) {
  const { item } = line;
  const why = feeWords(line);
  return (
    <tr className={line.for_sale ? undefined : "wishlist-row--gone"}>
      <td>
        <Link className="wishlist-item" to={`/items/${item.id}`}>
          <AuthImage className="wishlist-item__thumb" src={item.thumbnail_url} alt="" />
          <span>
            <span className="wishlist-item__title">{item.title}</span>
            <span className="muted collection-sub wishlist-item__meta">
              {item.site_name}
              {!line.for_sale && (
                <span className="chip chip--neutral">
                  {item.is_sold ? "Sold" : "No longer listed"}
                </span>
              )}
            </span>
          </span>
        </Link>
      </td>
      <td className="num">
        {line.price == null ? (
          <span className="muted">No price</span>
        ) : (
          formatMoney(line.price)
        )}
        <SinceAdded change={line.since_added} />
      </td>
      <td className="num">
        {line.shipping != null ? (
          formatMoney(line.shipping)
        ) : item.is_rifle || item.is_pistol ? (
          <span className="muted" title={line.shipping_note || undefined}>
            Not stated
          </span>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
      <td className="num">
        {line.fee != null ? formatMoney(line.fee) : line.fee_waived ? "$0" : "—"}
        {why && <div className="muted collection-sub">{why}</div>}
      </td>
      <td className="num">
        {line.total == null ? (
          <span className="muted">—</span>
        ) : (
          <>
            <strong>{formatMoney(line.total)}</strong>
            {!line.complete && <div className="muted collection-sub">at least</div>}
          </>
        )}
      </td>
      <td className="num">
        {line.valuation ? (
          <>
            {formatMoney(line.valuation.estimate)}
            <div className="muted collection-sub">
              {line.valuation.basis === "left" ? "when sold" : "asking now"}
              {line.valuation.like_for_like ? ", same condition" : ""}
            </div>
          </>
        ) : (
          <span className="muted" title="Too few listings of this model to price it">
            —
          </span>
        )}
      </td>
      <td className="num">
        <Profit value={line.profit} />
      </td>
      <td>
        <div className="wishlist-actions">
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => onBought(line)}
            disabled={busy}
            aria-label={`Bought ${item.title}`}
            title="Bought it: move to your collection"
          >
            <Box size={15} />
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => onRemove(item.id)}
            disabled={busy}
            aria-label={`Take ${item.title} off the wishlist`}
            title="Take off the wishlist"
          >
            <Trash />
          </button>
        </div>
      </td>
    </tr>
  );
}

function Totals({ totals, budget }) {
  const left = budget == null ? null : budget - totals.cost;
  return (
    <div className="week-stats collection-totals" data-testid="wishlist-totals">
      <div className="week-stat">
        <span className="week-stat__value">{totals.for_sale}</span>
        <span className="week-stat__label">
          for sale
          {totals.count > totals.for_sale
            ? ` (${totals.count - totals.for_sale} gone)`
            : ""}
        </span>
      </div>
      <div className="week-stat">
        <span className="week-stat__value">
          {totals.cost_complete ? "" : "≥ "}
          {formatMoney(totals.cost)}
        </span>
        <span className="week-stat__label">
          delivered{totals.unpriced ? ` (${totals.unpriced} unpriced)` : ""}
        </span>
      </div>
      {left != null && (
        <div className="week-stat">
          <span className={`week-stat__value ${left < 0 ? "wishlist-loss" : ""}`}>
            {formatMoney(Math.abs(left))}
          </span>
          <span className="week-stat__label">
            {left < 0 ? "over" : "left of"} your {formatMoney(budget)} budget
            {/* A floor of a cost leaves a ceiling of what is left, and a
                floor of how far over. */}
            {totals.cost_complete ? "" : left < 0 ? ", at least" : ", at most"}
          </span>
        </div>
      )}
      <div className="week-stat">
        <span className="week-stat__value">{formatMoney(totals.value)}</span>
        <span className="week-stat__label">
          worth about
          {totals.valued < totals.for_sale - totals.unpriced
            ? ` (${totals.valued} the market can price)`
            : ""}
        </span>
      </div>
      <div className="week-stat">
        <span className="week-stat__value">
          {totals.compared ? <Profit value={totals.profit} /> : "—"}
        </span>
        <span className="week-stat__label">
          profit or loss
          {totals.compared ? `, over the ${totals.compared} with both` : ""}
        </span>
      </div>
    </div>
  );
}

/** A number box that saves when it loses focus or Enter is pressed. */
function MoneyField({ label, value, max, placeholder, onSave }) {
  const [draft, setDraft] = useState(value == null ? "" : String(value));
  useEffect(() => setDraft(value == null ? "" : String(value)), [value]);
  const commit = () => {
    const next = draft === "" ? null : Number(draft);
    if (next !== value) onSave(next);
  };
  return (
    <label className="watch__field">
      <span>{label}</span>
      <input
        className="input"
        type="number"
        min="0"
        max={max}
        step="1"
        value={draft}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => event.key === "Enter" && commit()}
      />
    </label>
  );
}

/**
 * The fee, the license, the budget and the alerts, saved as they change.
 *
 * The boxes are ticked at once and put back if the save fails, so they
 * answer the click rather than the round trip.
 */
function Settings({ data, onSaved }) {
  const [holds, setHolds] = useState(data.has_cr_license);
  const [alerts, setAlerts] = useState(data.wishlist_alerts);
  const [error, setError] = useState("");

  useEffect(() => setHolds(data.has_cr_license), [data.has_cr_license]);
  useEffect(() => setAlerts(data.wishlist_alerts), [data.wishlist_alerts]);

  const save = async (call, undo) => {
    setError("");
    try {
      await call();
      onSaved();
    } catch (err) {
      undo?.();
      setError(err?.message || "Could not save that.");
    }
  };

  const fee = data.ffl_transfer_fee;
  return (
    <div className="wishlist-costs">
      <MoneyField
        label="Your dealer’s transfer fee"
        value={fee}
        max="1000"
        placeholder="Not set"
        onSave={(next) =>
          save(() => api.saveCosts({ ffl_transfer_fee: next, has_cr_license: holds }))
        }
      />
      <MoneyField
        label="Your budget"
        value={data.budget}
        placeholder="None"
        onSave={(next) => save(() => api.wishlistSettings({ budget: next }))}
      />
      <div className="wishlist-checks">
        <label className="watch__check">
          <input
            type="checkbox"
            checked={holds}
            onChange={(event) => {
              const next = event.target.checked;
              setHolds(next);
              save(
                () => api.saveCosts({ ffl_transfer_fee: fee, has_cr_license: next }),
                () => setHolds(!next),
              );
            }}
          />
          <span>I hold a C&amp;R license (no fee on C&amp;R-eligible guns)</span>
        </label>
        <label className="watch__check">
          <input
            type="checkbox"
            checked={alerts}
            onChange={(event) => {
              const next = event.target.checked;
              setAlerts(next);
              save(
                () => api.wishlistSettings({ alerts: next }),
                () => setAlerts(!next),
              );
            }}
          />
          <span>Email and notify me the moment one sells or changes price</span>
        </label>
      </div>
      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default function Wishlist() {
  useTitle("Wishlist");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [bought, setBought] = useState(null);
  const [sort, setSort] = useState({ key: "added", direction: "desc" });

  const load = useCallback(() => {
    api
      .wishlist()
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const act = async (call) => {
    setBusy(true);
    setError("");
    try {
      await call();
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = (itemId) => act(() => api.unwish(itemId));
  const markBought = (line) =>
    act(async () => {
      await api.wishlistBought(line.item.id);
      setBought({ title: line.item.title, paid: line.total });
    });

  const lines = useMemo(() => {
    if (!data) return [];
    const read = SORT_VALUES[sort.key];
    return [...data.lines].sort((left, right) => {
      const a = read(left);
      const b = read(right);
      if (a == null || b == null) return a == null && b == null ? 0 : a == null ? 1 : -1;
      const first = typeof a === "number" ? a - b : COLLATOR.compare(a, b);
      return sort.direction === "asc" ? first : -first;
    });
  }, [data, sort]);

  const sortBy = (key) =>
    setSort((current) =>
      current.key === key
        ? { key, direction: current.direction === "asc" ? "desc" : "asc" }
        : { key, direction: key === "name" ? "asc" : "desc" },
    );

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Wishlist</h1>
          <p>
            What the guns you mean to buy would cost delivered to your dealer, and what
            they are worth. Worth is what the same model has been asking, in the same
            condition where enough are listed — the market&rsquo;s price, not what a
            dealer would pay you, which is usually less.
          </p>
        </div>
        {data && data.lines.length > 0 && (
          <a className="btn btn--secondary" href="/api/wishlist/export">
            <Download size={16} />
            Export CSV
          </a>
        )}
      </div>

      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      {bought && (
        <p className="alert alert--success" role="status">
          {bought.title} is in your collection
          {bought.paid != null ? ` at ${formatMoney(bought.paid)} delivered` : ""}.{" "}
          <Link to="/collection">Open it</Link> to correct the price or the date.
        </p>
      )}
      {data === null && !error && <p className="muted">Loading…</p>}

      {data && <Settings data={data} onSaved={load} />}

      {data && data.lines.length === 0 && (
        <div className="panel">
          <div className="panel__body">
            <p style={{ margin: 0 }}>
              Nothing here yet. Press the cart on any listing, or{" "}
              <strong>Add to wishlist</strong> on its page, to price it to your door and
              see what it is worth.
            </p>
          </div>
        </div>
      )}

      {data && data.lines.length > 0 && (
        <>
          <Totals totals={data.totals} budget={data.budget} />
          <div className="panel">
            <div className="table-wrap">
              <table className="table wishlist-table" data-testid="wishlist-table">
                <thead>
                  <tr>
                    <SortHeader
                      label="Listing"
                      sortKey="name"
                      sort={sort}
                      onSort={sortBy}
                    />
                    <SortHeader
                      label="Price"
                      sortKey="price"
                      sort={sort}
                      onSort={sortBy}
                      className="num"
                    />
                    <th className="num">Shipping</th>
                    <th className="num">Transfer</th>
                    <SortHeader
                      label="Total"
                      sortKey="total"
                      sort={sort}
                      onSort={sortBy}
                      className="num"
                    />
                    <SortHeader
                      label="Worth"
                      sortKey="worth"
                      sort={sort}
                      onSort={sortBy}
                      className="num"
                    />
                    <SortHeader
                      label="Profit"
                      sortKey="profit"
                      sort={sort}
                      onSort={sortBy}
                      className="num"
                    />
                    <th>
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line) => (
                    <Line
                      key={line.item.id}
                      line={line}
                      onRemove={remove}
                      onBought={markBought}
                      busy={busy}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <p className="market-footnote">
            Sold and delisted guns stay on the list, dimmed, and are left out of the
            totals. A total marked &ldquo;at least&rdquo; is missing the shop&rsquo;s
            shipping or your transfer fee. A C&amp;R-eligible gun has no transfer fee only
            when you hold a license; one whose status is unknown is charged it. Profit is
            worth less the delivered total, summed over the guns that have both. The box
            moves a gun to your collection at its delivered total.
          </p>
        </>
      )}
    </section>
  );
}
