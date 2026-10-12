/**
 * Ammunition information: what it costs to shoot a caliber, and whether it
 * can be reloaded. Opened from a caliber's row on the Armory page and from a
 * listing's caliber; the figures are the server's (app/services/ammunition.py).
 *
 * Asked for on 2026-10-11: what a gun costs to shoot is often more of its
 * economics than what it costs to buy. Each figure names its source and when
 * it was checked, and an unknown says "not known yet" rather than leaving a
 * blank a reader could take for zero.
 */
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { formatRelative } from "../format.js";
import Modal from "./Modal.jsx";

const SOURCES = { "ammo-com": "Ammo.com", "milsurp-munitions": "Milsurp Munitions" };

/** "67¢" under a dollar, "$2.99" over it: a round is priced in cents. */
export function perRound(value) {
  if (value == null) return null;
  if (value < 1) return `${Math.round(value * 100)}¢`;
  return `$${value.toFixed(2)}`;
}

function Checked({ at }) {
  return at ? <span className="muted"> · checked {formatRelative(at)}</span> : null;
}

function Source({ url, children }) {
  return url ? (
    <a href={url} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ) : (
    children
  );
}

export function AmmunitionPanel({ caliber }) {
  const [facts, setFacts] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    api
      .ammunition(caliber)
      .then((found) => live && setFacts(found))
      .catch((err) => live && setError(err.message || "Could not load."));
    return () => {
      live = false;
    };
  }, [caliber]);

  if (error) return <p className="alert alert--error">{error}</p>;
  if (!facts) return <p className="muted">Loading…</p>;

  const unknown = <span className="muted">not known yet</span>;
  const weights = facts.bullet_weights || [];
  return (
    <div className="ammo" data-testid="ammunition-panel">
      <dl className="ammo__facts">
        <dt>Bullet diameter</dt>
        <dd>
          {facts.bullet_diameter_in
            ? `${facts.bullet_diameter_in.toFixed(3).replace(/^0/, "")}" (${(
                facts.bullet_diameter_in * 25.4
              ).toFixed(2)} mm)`
            : unknown}
          {facts.wikipedia_url && (
            <>
              {" · "}
              <Source url={facts.wikipedia_url}>Wikipedia</Source>
            </>
          )}
        </dd>
        <dt>Factory ammunition</dt>
        <dd data-testid="ammo-factory">
          {facts.factory_cpr != null ? (
            <>
              {perRound(facts.factory_cpr)} a round
              <span className="muted">
                {" "}
                (cheapest box at each weight, box price over rounds; no shipping)
              </span>
              {" · "}
              <Source url={facts.factory_url}>
                {SOURCES[facts.factory_source] || facts.factory_source}
              </Source>
            </>
          ) : (
            unknown
          )}
          <Checked at={facts.factory_checked_at} />
        </dd>
        <dt>Reloading dies</dt>
        <dd data-testid="ammo-dies">
          {facts.lee_dies === true && (
            <>
              Lee Precision makes them ·{" "}
              <Source url={facts.lee_url}>Lee&rsquo;s page</Source>
            </>
          )}
          {facts.lee_dies === false && "Not in Lee Precision's catalog"}
          {facts.lee_dies == null && unknown}
          <Checked at={facts.lee_checked_at} />
        </dd>
        <dt>Projectiles</dt>
        <dd data-testid="ammo-projectiles">
          {facts.projectile_cost != null ? (
            <>
              {perRound(facts.projectile_cost)} each
              <span className="muted"> (reloading bullets at this diameter)</span>
              {" · "}
              <Source url={facts.projectile_url}>Graf &amp; Sons</Source>
            </>
          ) : (
            unknown
          )}
          <Checked at={facts.projectile_checked_at} />
        </dd>
      </dl>
      {weights.length > 0 && (
        <table className="table ammo__weights">
          <thead>
            <tr>
              <th>Bullet</th>
              <th>Factory round</th>
              <th>Projectile</th>
            </tr>
          </thead>
          <tbody>
            {weights.map((weight) => (
              <tr key={weight.grains}>
                <td>{weight.grains} gr</td>
                <td>{perRound(weight.factory_cpr) || "—"}</td>
                <td>{perRound(weight.projectile_cost) || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** The button that opens the panel, for a caliber by name. */
export default function AmmunitionButton({
  caliber,
  className = "btn btn--ghost btn--sm",
}) {
  const [open, setOpen] = useState(false);
  if (!caliber) return null;
  return (
    <>
      <button
        type="button"
        className={className}
        onClick={() => setOpen(true)}
        aria-label={`Ammunition information for ${caliber}`}
      >
        Ammunition information
      </button>
      {open && (
        <Modal
          title={`Ammunition information: ${caliber}`}
          onClose={() => setOpen(false)}
          fit
        >
          <AmmunitionPanel caliber={caliber} />
        </Modal>
      )}
    </>
  );
}
