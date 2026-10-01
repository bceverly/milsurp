/**
 * How each shop behaves: what it stocks, when, at what price, and how it sells.
 *
 * The questions a regular buyer learns the hard way, answered from what the
 * scans have watched: does this dealer price above the market, does stock
 * last there, which day do the new guns go up, and will they mark it down if I
 * wait. Every figure is measured from when each shop was first scanned, and
 * one that has too little behind it is left blank rather than guessed. See
 * services/scorecards.py.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import SortHeader from "../components/SortHeader.jsx";
import { COLLATOR } from "../sorting.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

//: What each sortable column reads off a card. A missing figure sorts last
//: whichever way round, rather than as nought.
const SORT_VALUES = {
  name: (card) => card.name,
  guns: (card) => card.guns_for_sale,
  price: (card) => card.price_vs_market,
  sells: (card) => card.sell_days,
  cuts: (card) => card.habit?.drops ?? null,
};

/** "8% above", "3% below", "about the same". */
function versusMarket(ratio) {
  if (ratio == null) return null;
  const percent = Math.round((ratio - 1) * 100);
  if (Math.abs(percent) < 2) return "About the market";
  return `${Math.abs(percent)}% ${percent > 0 ? "above" : "below"}`;
}

/** Arrivals by weekday as seven small bars, the busiest full height. */
function Weekdays({ counts }) {
  const top = Math.max(...counts, 1);
  return (
    <span className="weekdays" aria-hidden="true">
      {counts.map((count, day) => (
        <span
          key={DAYS[day]}
          className="weekdays__bar"
          style={{ height: `${Math.max(2, (count / top) * 18)}px` }}
          title={`${DAYS[day]}: ${count}`}
        />
      ))}
    </span>
  );
}

export default function Shops() {
  useTitle("Shops");
  const [cards, setCards] = useState(null);
  const [error, setError] = useState(null);
  const [sort, setSort] = useState({ key: "guns", direction: "desc" });

  useEffect(() => {
    let live = true;
    api
      .shopScorecards()
      .then((rows) => live && setCards(rows))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, []);

  const rows = useMemo(() => {
    if (!cards) return [];
    const read = SORT_VALUES[sort.key];
    return [...cards].sort((left, right) => {
      const a = read(left);
      const b = read(right);
      if (a == null || b == null) {
        return a == null && b == null
          ? COLLATOR.compare(left.name, right.name)
          : a == null
            ? 1
            : -1;
      }
      const first = typeof a === "number" ? a - b : COLLATOR.compare(a, b);
      return (
        (sort.direction === "asc" ? first : -first) ||
        COLLATOR.compare(left.name, right.name)
      );
    });
  }, [cards, sort]);

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
          <h1>Shops</h1>
          <p>
            How each dealer behaves, measured since we started watching it: what it has
            for sale, which day new guns go up, how its prices sit against the same models
            elsewhere, how fast its stock sells, and whether it cuts prices on what does
            not.
          </p>
        </div>
      </div>

      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      {!cards && !error && <p className="muted">Loading…</p>}

      {cards && (
        <div className="panel">
          <div className="table-wrap">
            <table className="table" data-testid="shops-table">
              <thead>
                <tr>
                  <SortHeader label="Shop" sortKey="name" sort={sort} onSort={sortBy} />
                  <SortHeader
                    label="For sale"
                    sortKey="guns"
                    sort={sort}
                    onSort={sortBy}
                  />
                  <th>New stock lands</th>
                  <SortHeader label="Price" sortKey="price" sort={sort} onSort={sortBy} />
                  <SortHeader
                    label="Sells in"
                    sortKey="sells"
                    sort={sort}
                    onSort={sortBy}
                  />
                  <SortHeader
                    label="Cuts prices"
                    sortKey="cuts"
                    sort={sort}
                    onSort={sortBy}
                  />
                </tr>
              </thead>
              <tbody>
                {rows.map((card) => (
                  <tr key={card.site_id}>
                    <td>
                      <Link to={`/?site_id=${card.site_id}`}>{card.name}</Link>
                    </td>
                    <td>
                      {card.guns_for_sale.toLocaleString()}
                      {card.new_this_week > 0 && (
                        <div className="muted collection-sub">
                          {card.new_this_week} new this week
                        </div>
                      )}
                    </td>
                    <td>
                      {card.busiest_day ? (
                        <>
                          <Weekdays counts={card.arrivals_by_weekday} />{" "}
                          <span className="collection-sub">
                            Mostly {card.busiest_day}
                          </span>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {versusMarket(card.price_vs_market) ?? (
                        <span className="muted">—</span>
                      )}
                      {card.compared > 0 && (
                        <div className="muted collection-sub">
                          over {card.compared} comparable guns
                        </div>
                      )}
                    </td>
                    <td>
                      {card.sell_days != null ? (
                        <>
                          {Math.round(card.sell_days)} days
                          <div className="muted collection-sub">
                            typically, {card.sold_measured} watched
                          </div>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {card.habit ? (
                        <>
                          About {Math.round(card.habit.median_pct)}% around day{" "}
                          {Math.round(card.habit.median_day)}
                          <div className="muted collection-sub">
                            {card.habit.drops} cut so far
                          </div>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {cards && (
        <p className="market-footnote">
          A dash is a figure with too little behind it yet. Prices are compared only on
          models that at least two shops sell, five or more listed; price cuts are shown
          for shops that have made ten or more.
        </p>
      )}
    </section>
  );
}
