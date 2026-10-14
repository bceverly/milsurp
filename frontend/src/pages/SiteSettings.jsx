/**
 * Site settings: the administrator's knobs that are not about anyone's email,
 * gathered on one page (2026-10-12) rather than at the foot of the pages they
 * affect -- asked for to keep the Armory clean, and then for anything else
 * that "isn't email related".
 *
 * - **Caliber data**: how often it is updated (daily, weekly or every 2
 *   weeks; weekly by default), and a button for each of its three parts and
 *   one for all of them. See app/services/ammunition.py. It started at the
 *   foot of the Email digest page, then sat on the Armory's Calibers tab.
 * - **Manufacturer data** (2026-10-13): the reads of the manufacturers' own
 *   sites -- each model's MSRP and variants, and its manufacturer page --
 *   which were commands on the server and nothing else.
 * - **Hot deals**: how deals are found, which sat at the foot of the Hot
 *   deals page.
 */
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { formatRelative } from "../format.js";
import { useTitle } from "../hooks.js";
import Field from "../components/Field.jsx";
import HotDealControls from "../components/HotDealControls.jsx";
import { Refresh } from "../components/Icons.jsx";

/** The parts of a refresh, in the order a full one runs them. */
const PARTS = [
  {
    key: "wikipedia",
    button: "Update Wikipedia facts",
    title: "Wikipedia facts",
    text:
      "Each caliber’s article: its bullet diameter and weights. New and edited " +
      "calibers are read hourly; this reads every article again.",
  },
  {
    key: "reloading",
    button: "Update reloading bullets",
    title: "Reloading bullets",
    text:
      "What a projectile costs at each caliber’s diameter, from Graf & Sons, and " +
      "whether Lee Precision makes dies for it.",
  },
  {
    key: "prices",
    button: "Update ammo prices",
    title: "Ammo prices",
    text:
      "The cheapest factory round at each weight, from Ammo.com, or Milsurp " +
      "Munitions for the cartridges nobody else loads.",
  },
];
const ALL = PARTS.map(({ key }) => key);
const TITLES = Object.fromEntries(PARTS.map(({ key, title }) => [key, title]));

/** "Wikipedia facts and Ammo prices", from "wikipedia,prices". */
function named(parts) {
  const keys = (parts || "").split(",").filter((key) => TITLES[key]);
  if (keys.length === 0 || keys.length === ALL.length) return "everything";
  const titles = keys.map((key) => TITLES[key]);
  return titles.length === 1
    ? titles[0]
    : `${titles.slice(0, -1).join(", ")} and ${titles.at(-1)}`;
}

export default function SiteSettingsPage() {
  useTitle("Site settings");
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Site settings</h1>
          <p>
            What the site does on its own schedule, and the buttons to make it do it now.
            Your own email is under Email digest.
          </p>
        </div>
      </div>
      <CaliberData />
      <JobSection
        title="Manufacturer data"
        intro="What the manufacturers’ own sites say about the models still made. Run when you like: nothing here is on a schedule."
        jobs={MANUFACTURER_JOBS}
        testId="manufacturer-data-section"
      />
      <JobSection
        title="Listing data"
        intro="What is read from each listing’s own words, read again over everything stored. A scan reads each listing as it goes; this is for after the rules change."
        jobs={LISTING_JOBS}
        testId="listing-data-section"
      />
      <HotDeals />
    </>
  );
}

/** How often the caliber data is updated, and each part of it now. */
function CaliberData() {
  const [state, setState] = useState(null);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .ammoSettings()
      .then(setState)
      .catch((err) => setMessage({ ok: false, text: err.message }));
  }, []);

  async function choose(event) {
    setMessage(null);
    try {
      setState(
        await api.updateAmmoSettings({ refresh_days: Number(event.target.value) }),
      );
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    }
  }

  async function update(parts) {
    setBusy(true);
    setMessage(null);
    try {
      const next = await api.refreshAmmo(parts);
      setState(next);
      setMessage({
        ok: true,
        text: `An update of ${named(next.requested_parts).toLowerCase()} starts within a minute.`,
      });
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  }

  const waiting = Boolean(state?.requested_at);
  return (
    <section className="settings-section" data-testid="caliber-data-section">
      <div className="settings-section__head">
        <div>
          <h2>Caliber data</h2>
          <p className="muted">
            What each caliber costs to shoot, for every caliber with a listing for sale:
            the Ammunition information on a listing and in the Armory.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => update(ALL)}
          disabled={!state || busy || waiting}
        >
          <Refresh aria-hidden="true" />
          Update all
        </button>
      </div>

      {message && (
        <p className={`alert ${message.ok ? "alert--success" : "alert--error"}`}>
          {message.text}
        </p>
      )}

      {state && (
        <div className="settings-grid" data-testid="caliber-data">
          {PARTS.map(({ key, button, title, text }) => (
            <div className="panel" key={key} data-testid={`caliber-data-${key}`}>
              <div className="panel__head">
                <h2>{title}</h2>
              </div>
              <div className="panel__body">
                <p className="muted" style={{ marginTop: 0 }}>
                  {text}
                </p>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => update([key])}
                  disabled={busy || waiting}
                >
                  {button}
                </button>
              </div>
            </div>
          ))}

          <div className="panel">
            <div className="panel__head">
              <h2>Schedule</h2>
            </div>
            <div className="panel__body">
              <Field label="How often">
                {(id) => (
                  <select
                    id={id}
                    className="input"
                    value={state.refresh_days}
                    onChange={choose}
                    style={{ maxWidth: 220 }}
                  >
                    {Object.entries(state.choices).map(([days, label]) => (
                      <option key={days} value={days}>
                        {label}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <p className="muted" data-testid="caliber-data-last">
                {waiting && (
                  <>
                    An update of {named(state.requested_parts).toLowerCase()} was asked
                    for and starts within a minute.{" "}
                  </>
                )}
                {state.last_run_at ? (
                  <>
                    Last updated {formatRelative(state.last_run_at)} (
                    {named(state.last_parts).toLowerCase()})
                    {state.last_status === "failed" ? " and failed: " : ": "}
                    {state.last_error || state.last_summary}
                  </>
                ) : (
                  "Not updated yet."
                )}
              </p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

//: The reads of the manufacturers' sites, as the page offers them.
const MANUFACTURER_JOBS = [
  {
    name: "variants",
    title: "MSRPs and variants",
    button: "Update MSRPs and variants",
    text:
      "Each model's versions -- caliber, barrel, finish, UPC and MSRP -- from Ruger, " +
      "Smith & Wesson, Kimber and Walther. New ones wait for approval in each model's " +
      "dialog on the Armory.",
  },
  {
    name: "pages",
    title: "Manufacturer pages",
    button: "Find manufacturer pages",
    text:
      "Each model still made, matched to its page in its manufacturer's sitemap. What " +
      "it finds waits on the Armory's Manufacturer pages tab.",
  },
];

//: The re-reads of what is stored, as the page offers them (2026-10-14).
const LISTING_JOBS = [
  {
    name: "barrels",
    title: "Barrels and frame sizes",
    button: "Re-read barrels and frame sizes",
    text:
      "Every gun's barrel length and whether it is threaded, and every handgun's frame " +
      "size, read again from its title and description; each listing of a model still " +
      "made matched to its versions again. Asks no website anything.",
  },
];

/** Long jobs, a button each: asked for here, run by the scheduler. */
function JobSection({ title, intro, jobs: offered, testId }) {
  const [jobs, setJobs] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    api
      .manufacturerJobs()
      .then(setJobs)
      .catch((err) => setMessage({ ok: false, text: err.message }));
  }, []);

  async function run(job) {
    setBusy(true);
    setMessage(null);
    try {
      setJobs(await api.runManufacturerJob(job.name));
      setMessage({ ok: true, text: `${job.title}: starts within a minute.` });
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  }

  const byName = Object.fromEntries((jobs || []).map((row) => [row.name, row]));
  return (
    <section className="settings-section" data-testid={testId}>
      <div className="settings-section__head">
        <div>
          <h2>{title}</h2>
          <p className="muted">{intro}</p>
        </div>
      </div>
      {message && (
        <p className={`alert ${message.ok ? "alert--success" : "alert--error"}`}>
          {message.text}
        </p>
      )}
      {jobs && (
        <div className="settings-grid">
          {offered.map((job) => {
            const row = byName[job.name] || {};
            return (
              <div
                className="panel"
                key={job.name}
                data-testid={`manufacturer-job-${job.name}`}
              >
                <div className="panel__head">
                  <h2>{job.title}</h2>
                </div>
                <div className="panel__body">
                  <p className="muted" style={{ marginTop: 0 }}>
                    {job.text}
                  </p>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => run(job)}
                    disabled={busy || Boolean(row.requested_at)}
                  >
                    {row.requested_at ? "Asked for" : job.button}
                  </button>
                  <p className="muted">
                    {row.last_run_at ? (
                      <>
                        Last run {formatRelative(row.last_run_at)}
                        {row.last_status === "failed" ? " and failed: " : ": "}
                        {row.last_summary}
                      </>
                    ) : (
                      "Not run yet."
                    )}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/** How hot deals are found: the administrator's half of the Hot deals page. */
function HotDeals() {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () =>
    api
      .hotDeals({ limit: 1 })
      .then(setState)
      .catch((err) => setError(err.message));

  useEffect(() => {
    load();
  }, []);

  async function send(call) {
    setBusy(true);
    setError(null);
    try {
      setState(await call());
    } catch (err) {
      // Read the settings again before reporting: the server refused, so the
      // box is showing a value that was never saved and has to be put back.
      await load();
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-section" data-testid="hot-deal-settings">
      <div className="settings-section__head">
        <div>
          <h2>Hot deals</h2>
          <p className="muted">What counts as a deal, and how often to look.</p>
        </div>
      </div>
      {error && <p className="alert alert--error">{error}</p>}
      {state?.settings && (
        <HotDealControls
          settings={state.settings}
          choices={state.interval_choices}
          busy={busy}
          onChange={(body) => send(() => api.updateHotDealSettings(body))}
          onRefresh={() => send(() => api.refreshHotDeals())}
        />
      )}
    </section>
  );
}
