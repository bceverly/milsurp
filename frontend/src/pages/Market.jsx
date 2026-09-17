/**
 * What a kind of gun goes for, across every dealer at once.
 *
 * The detail page answers "is this a good deal?" for one listing by placing it
 * among others of the same model. This asks the same question one level up —
 * what does a 7.5x55 Swiss rifle cost anywhere — which is the question
 * somebody has *before* they have a listing in front of them.
 *
 * Two things on this page are there because the naive version misleads. The
 * spread is the tenth to ninetieth percentile rather than the range, because
 * one mislabeled $750,000 Gatling gun sets the maximum for .45-70 and says
 * nothing about the .45-70s anybody will buy. And every band says how many
 * shops it came from, because most of them are one: 7.5x55 Swiss is 94% a
 * single dealer, and a median from one shelf is that dealer's pricing.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatMoney } from "../format.js";
import { Refresh, Warning } from "../components/Icons.jsx";

const DIMENSIONS = [
  { key: "caliber", label: "Caliber" },
  { key: "country", label: "Country" },
  { key: "manufacturer", label: "Maker" },
];

/**
 * The band as a bar: tenth percentile to ninetieth, with the median marked.
 *
 * Drawn against the widest band on the page rather than each against itself,
 * so the bars are comparable — which is the whole reason to draw them instead
 * of printing three numbers.
 */
function Spread({ band, ceiling }) {
  const scale = (value) => `${Math.min(100, (value / ceiling) * 100)}%`;
  return (
    <div
      className="market-bar"
      title={`${formatMoney(band.low, band.currency)} to ${formatMoney(
        band.high,
        band.currency,
      )}, median ${formatMoney(band.median, band.currency)}`}
    >
      <div
        className="market-bar__range"
        style={{ left: scale(band.low), width: scale(band.high - band.low) }}
      />
      <div className="market-bar__median" style={{ left: scale(band.median) }} />
    </div>
  );
}

export default function Market() {
  useTitle("Market");
  const [dimension, setDimension] = useState("caliber");
  const [firearmsOnly, setFirearmsOnly] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setResult(null);
    setError(null);
    try {
      // Sent as the non-default: `qs` drops a false boolean, so a
      // `firearms_only=false` would never leave the browser and the switch
      // would quietly do nothing.
      setResult(await api.market({ by: dimension, include_accessories: !firearmsOnly }));
    } catch (err) {
      setError(err.message);
    }
  }, [dimension, firearmsOnly]);

  useEffect(() => {
    load();
  }, [load]);

  const ceiling = result?.bands.length
    ? Math.max(...result.bands.map((band) => band.high))
    : 1;
  const concentrated = result ? result.bands.filter((band) => band.concentrated) : [];

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Market</h1>
          <p>
            What each kind of gun is being asked for, across every shop at once. The
            middle of each bar is the median; the bar runs from the tenth to the ninetieth
            percentile, so one extraordinary listing cannot set the scale.
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--secondary" onClick={load}>
            <Refresh size={16} />
            Refresh
          </button>
        </div>
      </div>

      <div className="armory-tabs" role="tablist">
        {DIMENSIONS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={dimension === entry.key}
            className={`btn ${dimension === entry.key ? "btn--primary" : "btn--ghost"} btn--sm`}
            onClick={() => setDimension(entry.key)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={firearmsOnly}
          onChange={(event) => setFirearmsOnly(event.target.checked)}
        />
        <span>
          Firearms only
          <span className="field__hint">
            A caliber&rsquo;s listings mix $600 rifles with $40 bayonets, magazines and
            parts kits. A median across those describes nothing that exists.
          </span>
        </span>
      </label>

      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}

      {!result && !error && (
        <div className="loading-row" style={{ padding: 20 }}>
          <div className="spinner" />
          Working out the bands…
        </div>
      )}

      {result && (
        <>
          {concentrated.length > 0 && (
            <div className="alert alert--warning">
              <p style={{ margin: 0 }}>
                <Warning size={15} /> <strong>{concentrated.length}</strong> of{" "}
                {result.bands.length} bands come mostly from a single shop. That is that
                shop&rsquo;s pricing rather than the market&rsquo;s — the rows are marked,
                and worth reading as one dealer&rsquo;s shelf.
              </p>
            </div>
          )}

          <div className="panel">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{DIMENSIONS.find((d) => d.key === dimension).label}</th>
                    <th>Listings</th>
                    <th>Typical</th>
                    <th>Spread</th>
                    <th>Shops</th>
                  </tr>
                </thead>
                <tbody>
                  {result.bands.map((band) => (
                    <tr key={band.value}>
                      <td>
                        <Link to={`/?${dimension}=${encodeURIComponent(band.value)}`}>
                          {band.value}
                        </Link>
                        {band.concentrated && (
                          <span className="chip chip--warning market-chip">one shop</span>
                        )}
                      </td>
                      <td>{band.listings.toLocaleString()}</td>
                      <td>
                        <strong>{formatMoney(band.median, band.currency)}</strong>
                      </td>
                      <td className="market-spread">
                        <span className="market-spread__low">
                          {formatMoney(band.low, band.currency)}
                        </span>
                        <Spread band={band} ceiling={ceiling} />
                        <span className="market-spread__high">
                          {formatMoney(band.high, band.currency)}
                        </span>
                      </td>
                      <td>
                        {band.sites}
                        <span className="market-share">
                          {Math.round(band.top_site_share * 100)}% largest
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <p className="market-footnote">
            {result.considered.toLocaleString()} listings considered.{" "}
            {result.thin_groups > 0 && (
              <>
                {result.thin_groups.toLocaleString()} more had fewer than{" "}
                {result.min_sample} listings each ({result.thin_listings.toLocaleString()}{" "}
                in total) and are left out: below a handful, a median is an anecdote with
                a decimal point.
              </>
            )}
          </p>
        </>
      )}
    </div>
  );
}
