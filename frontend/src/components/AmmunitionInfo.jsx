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

/** "Large rifle magnum", as the primer is named. */
export function primerName(size, magnum) {
  if (!size) return null;
  return magnum ? `${size} magnum` : size;
}

/** What one reloaded round is made of, and what each part costs. */
function Reloading({ facts, unknown }) {
  const primer = primerName(facts.primer_size, facts.primer_magnum);
  const load = facts.powder_name && facts.powder_charge_gr;
  return (
    <>
      <dt>New brass</dt>
      <dd data-testid="ammo-brass">
        {facts.brass_cost != null ? (
          <>
            {perRound(facts.brass_cost)} a case
            <span className="muted"> (cheapest new, unprimed case)</span>
            {" · "}
            <Source url={facts.brass_url}>Graf &amp; Sons</Source>
          </>
        ) : (
          unknown
        )}
        <Checked at={facts.brass_checked_at} />
      </dd>
      <dt>Primer</dt>
      <dd data-testid="ammo-primer">
        {primer ? (
          <>
            {primer}
            <span className="muted">
              {facts.primer_source === "hand" ? " (set by hand)" : " (from the article)"}
            </span>
            {facts.primer_cost != null && (
              <>
                {" · "}
                {perRound(facts.primer_cost)} each ·{" "}
                <Source url={facts.primer_url}>Graf &amp; Sons</Source>
              </>
            )}
          </>
        ) : (
          unknown
        )}
      </dd>
      <dt>Powder</dt>
      <dd data-testid="ammo-powder">
        {load ? (
          <>
            {facts.powder_charge_gr} gr of{" "}
            <Source url={facts.powder_url}>{facts.powder_name}</Source>
            {facts.powder_bullet_gr ? ` under a ${facts.powder_bullet_gr} gr bullet` : ""}
            {facts.powder_cost != null ? (
              <>
                {" · "}
                {perRound(facts.powder_cost)} a charge
                {facts.powder_per_pound != null && (
                  <span className="muted">
                    {" "}
                    (${facts.powder_per_pound.toFixed(2)} a pound, 7,000 gr)
                  </span>
                )}
              </>
            ) : (
              <span className="muted"> · not in stock at Graf &amp; Sons</span>
            )}
          </>
        ) : (
          <span className="muted">no load entered yet</span>
        )}
      </dd>
      <dt>Reloaded round</dt>
      <dd data-testid="ammo-reload">
        {facts.reload_cost != null ? (
          <>
            <strong>{perRound(facts.reload_cost)} a round</strong>
            <span className="muted">
              {" "}
              (bullet {perRound(facts.bullet_cost)} + brass {perRound(facts.brass_cost)} +
              powder {perRound(facts.powder_cost)} + primer {perRound(facts.primer_cost)};
              new brass, no shipping or hazmat)
            </span>
          </>
        ) : (
          <span className="muted">not known until all four parts are</span>
        )}
      </dd>
    </>
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
        <Reloading facts={facts} unknown={unknown} />
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
