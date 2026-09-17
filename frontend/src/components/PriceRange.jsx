/**
 * The price filter: a histogram, two handles, and two number boxes.
 *
 * The rail had no price control at all — the API has taken `min_price` and
 * `max_price` since the beginning and nothing on screen ever set them. The
 * reason this is not simply two number boxes is that the reader would have to
 * guess what a sensible range is and then correct: this catalog runs from a $2
 * clip pouch to a $750,000 Gatling gun, and "is £600 dear for this?" is the
 * question the whole page exists to answer.
 *
 * **The scale is logarithmic, and that is not a flourish.** On a linear axis
 * every listing but a handful sits in the first column and the first pixel of
 * the track. The handles move linearly in pixels and the value underneath them
 * moves by ratio, which is how prices are actually compared — the step from
 * $200 to $400 is the same *kind* of step as $2,000 to $4,000.
 *
 * The number boxes stay, and stay authoritative. They are what a keyboard and
 * a screen reader drive, they accept a figure somebody already has in mind
 * without hunting for it, and the slider is a faster way to reach the same two
 * values rather than a replacement for them.
 */
import { useEffect, useMemo, useState } from "react";
import { formatMoney } from "../format.js";

/** Positions on the track. Fine enough that a drag feels continuous. */
const STEPS = 1000;

function toPosition(price, low, high) {
  if (!(price > 0) || high <= low) return 0;
  const span = Math.log(high) - Math.log(low);
  return Math.round(((Math.log(price) - Math.log(low)) / span) * STEPS);
}

function toPrice(position, low, high) {
  if (high <= low) return low;
  const span = Math.log(high) - Math.log(low);
  return Math.exp(Math.log(low) + (position / STEPS) * span);
}

/**
 * Rounded to something a person would type.
 *
 * An unrounded log position gives $417.8231, which is not a price anybody has
 * in mind and makes the box look broken. The step grows with the number,
 * because $5 is a meaningful difference at $40 and noise at $40,000.
 */
function tidy(price) {
  if (price < 50) return Math.round(price);
  if (price < 500) return Math.round(price / 5) * 5;
  if (price < 5000) return Math.round(price / 25) * 25;
  if (price < 50000) return Math.round(price / 250) * 250;
  return Math.round(price / 1000) * 1000;
}

export default function PriceRange({ distribution, min, max, onChange }) {
  const { low, high, typical_low: typicalLow, typical_high: typicalHigh } = distribution;
  // Memoized rather than defaulted inline: a fresh [] on every render makes
  // the useMemo below recompute every time, which is the one thing it exists
  // not to do.
  const buckets = useMemo(() => distribution.buckets || [], [distribution.buckets]);

  // Local while dragging, committed on release: a request per pixel would be
  // a hundred requests a drag, and the rail would flicker through every one.
  const [draft, setDraft] = useState(null);
  useEffect(() => setDraft(null), [min, max]);

  const lowValue = draft ? draft[0] : (min ?? low);
  const highValue = draft ? draft[1] : (max ?? high);

  const tallest = useMemo(
    () => Math.max(1, ...buckets.map((bucket) => bucket.count)),
    [buckets],
  );

  const commit = (nextLow, nextHigh) => {
    setDraft(null);
    onChange({
      // The ends mean "no bound", so dragging a handle back to the edge clears
      // the filter rather than pinning it to the cheapest listing that happens
      // to be in the catalog today.
      min: nextLow <= low ? null : tidy(nextLow),
      max: nextHigh >= high ? null : tidy(nextHigh),
    });
  };

  const lowPosition = toPosition(lowValue, low, high);
  const highPosition = toPosition(highValue, low, high);

  return (
    <div className="price-range">
      <div className="price-range__chart" aria-hidden="true">
        {buckets.map((bucket) => {
          const inside = bucket.high > lowValue && bucket.low < highValue;
          return (
            <span
              key={bucket.low}
              className={`price-range__bar ${inside ? "" : "price-range__bar--out"}`}
              style={{ height: `${Math.max(2, (bucket.count / tallest) * 100)}%` }}
              title={`${formatMoney(bucket.low)}–${formatMoney(bucket.high)}: ${bucket.count}`}
            />
          );
        })}
      </div>

      {/* Two native range inputs stacked on one track. Native because a
          hand-rolled slider is a keyboard trap waiting to happen, and these
          arrive with arrow keys, Home/End and a screen-reader contract for
          free. */}
      <div className="price-range__track">
        <input
          type="range"
          className="price-range__handle"
          min={0}
          max={STEPS}
          value={lowPosition}
          aria-label="Lowest price"
          onChange={(event) => {
            const next = Math.min(Number(event.target.value), highPosition);
            setDraft([toPrice(next, low, high), highValue]);
          }}
          onMouseUp={() => draft && commit(draft[0], draft[1])}
          onTouchEnd={() => draft && commit(draft[0], draft[1])}
          onKeyUp={() => draft && commit(draft[0], draft[1])}
        />
        <input
          type="range"
          className="price-range__handle"
          min={0}
          max={STEPS}
          value={highPosition}
          aria-label="Highest price"
          onChange={(event) => {
            const next = Math.max(Number(event.target.value), lowPosition);
            setDraft([lowValue, toPrice(next, low, high)]);
          }}
          onMouseUp={() => draft && commit(draft[0], draft[1])}
          onTouchEnd={() => draft && commit(draft[0], draft[1])}
          onKeyUp={() => draft && commit(draft[0], draft[1])}
        />
      </div>

      <div className="price-range__boxes">
        <label>
          <span className="price-range__box-label">Min</span>
          <input
            className="input input--sm"
            type="number"
            min={0}
            inputMode="numeric"
            placeholder={String(Math.round(low))}
            value={min ?? ""}
            onChange={(event) =>
              onChange({
                min: event.target.value ? Number(event.target.value) : null,
                max,
              })
            }
          />
        </label>
        <span className="price-range__dash">–</span>
        <label>
          <span className="price-range__box-label">Max</span>
          <input
            className="input input--sm"
            type="number"
            min={0}
            inputMode="numeric"
            placeholder={String(Math.round(high))}
            value={max ?? ""}
            onChange={(event) =>
              onChange({
                min,
                max: event.target.value ? Number(event.target.value) : null,
              })
            }
          />
        </label>
      </div>

      <p className="price-range__note">
        {/* Where the bulk is, so "most of them" is a number rather than a
            squint at the chart. */}
        Most are {formatMoney(typicalLow)} to {formatMoney(typicalHigh)}.
        {distribution.unpriced > 0 && (
          <>
            {" "}
            {distribution.unpriced.toLocaleString()} more say <em>call for price</em> and
            are left out by any range.
          </>
        )}
      </p>
    </div>
  );
}
