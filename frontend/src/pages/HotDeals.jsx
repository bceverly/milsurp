/**
 * The listings that are cheap for what they are.
 *
 * The Market page says what a gun is worth; the price spectrum on a listing
 * says where that one sits. This is those two put together and pointed at the
 * whole catalog: of everything on every shelf, which ones are well under the
 * going rate right now.
 *
 * **Every row carries its own evidence**, and that is the point rather than
 * decoration. "38% below the usual price" on its own is a marketing claim; the
 * same sentence with "53 listed across 5 shops" under it is a measurement, and
 * a reader can tell the difference between a deal drawn from a real market and
 * one drawn from two listings on the same shelf.
 *
 * The three filters are the browse page's own buckets under its own names, and
 * the server decides both the order and the labels — the email says the same
 * words, and three copies of a list of categories is three chances to drift.
 *
 * **The sort is the server's too, and not only for consistency.** The list is
 * capped, so re-ordering the rows here would be re-ordering the two hundred
 * deepest discounts — which is the right two hundred for one order out of five
 * and quietly the wrong one for the rest. "Cheapest first" has to mean the
 * cheapest deals, so the ordering happens where the limit does.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../auth.jsx";
import { useTitle } from "../hooks.js";
import { formatMoney, formatRelative } from "../format.js";
import AuthImage from "../components/AuthImage.jsx";
import { Flame, Refresh, Warning } from "../components/Icons.jsx";

/** One deal, read against what the same gun usually costs. */
function DealRow({ deal }) {
  const { item } = deal;
  return (
    <li className="deal">
      <Link className="deal__link" to={`/items/${item.id}`}>
        {item.thumbnail_url ? (
          // Deferred, like every other long list of photos here. The whole
          // catalog's best prices is a page of a hundred and fifty rows, and
          // fetching all of their photos at once is the request storm that
          // AuthImage's own notes describe: the server has fifteen database
          // connections, and the listing you actually wanted is somewhere in
          // the queue behind them.
          <AuthImage
            className="deal__thumb"
            src={item.thumbnail_url}
            alt=""
            loading="lazy"
          />
        ) : (
          <span className="deal__thumb deal__thumb--empty" aria-hidden="true" />
        )}
        <span className="deal__text">
          <span className="deal__headline">
            {Math.round(deal.discount_percent)}% below the usual price
          </span>
          <span className="deal__title">{item.title}</span>
          <span className="deal__meta">
            <span>{item.site_name}</span>
            <span>
              Usually {formatMoney(deal.median_price, item.currency)} &middot;{" "}
              {deal.peer_count} listed across {deal.vendor_count} shop
              {deal.vendor_count === 1 ? "" : "s"}
            </span>
            <span>Cheaper than {deal.cheaper_than}% of them</span>
            {/* Dealers buy surplus by the crate and list it a rifle at a
                time. Nine identical rows is not nine things to tell somebody,
                so they collapse — and the row says how many it stands for
                rather than quietly hiding eight listings. */}
            {deal.duplicate_count > 1 && (
              <span className="deal__more">
                {deal.duplicate_count} at this price here
              </span>
            )}
          </span>
        </span>
        <span className="deal__price">
          {formatMoney(item.current_price, item.currency)}
          <span className="deal__since">
            Listed {formatRelative(deal.first_listed_at)}
          </span>
        </span>
      </Link>
    </li>
  );
}

/** Which categories to be mailed about. Everyone is subscribed until they say
    otherwise, which is why this panel opens switched on. */
function Subscription({ preference, labels, buckets, onChange, busy }) {
  const FIELD = {
    rifle: "include_rifles",
    pistol: "include_handguns",
    police_surplus: "include_police_surplus",
  };
  return (
    <div className="panel deal-panel">
      <div className="panel__head">
        <h2>Email me about these</h2>
      </div>
      <div className="panel__body">
        <label className="switch">
          <input
            type="checkbox"
            checked={preference.enabled}
            disabled={busy}
            onChange={(event) => onChange({ enabled: event.target.checked })}
          />
          <span className="switch__track" />
          <span>Send me hot deals as they are found</span>
        </label>
        <p className="muted deal-panel__note">
          One email after each pass, carrying only what you have not been sent. A listing
          whose price moves again comes back — that is the whole point of the alert — but
          nothing is repeated at a price you have already seen.
        </p>
        <fieldset className="deal-panel__cats" disabled={!preference.enabled || busy}>
          <legend>Categories</legend>
          {buckets.map((bucket) => (
            <label className="switch" key={bucket}>
              <input
                type="checkbox"
                checked={preference[FIELD[bucket]]}
                onChange={(event) => onChange({ [FIELD[bucket]]: event.target.checked })}
              />
              <span className="switch__track" />
              <span>{labels[bucket]}</span>
            </label>
          ))}
        </fieldset>
        <label className="switch">
          <input
            type="checkbox"
            checked={Boolean(preference.match_saved_searches)}
            disabled={!preference.enabled || busy}
            onChange={(event) => onChange({ match_saved_searches: event.target.checked })}
          />
          <span className="switch__track" />
          <span>Only deals that match one of my saved searches</span>
        </label>
        <p className="muted deal-panel__note" data-testid="saved-search-note">
          {preference.saved_searches === 0 ? (
            <>
              You have no <Link to="/saved-searches">saved searches</Link> yet, so with
              this on nothing would be sent. Save a search from the inventory first.
            </>
          ) : (
            <>
              Each deal is checked against your{" "}
              <Link to="/saved-searches">
                {preference.saved_searches} saved search
                {preference.saved_searches === 1 ? "" : "es"}
              </Link>{" "}
              exactly as the inventory would run them. The categories above still apply.
            </>
          )}
        </p>
      </div>
    </div>
  );
}

/** The administrator's half: how often to look, and what counts as a deal. */
function Controls({ settings, choices, onChange, onRefresh, busy }) {
  const [draft, setDraft] = useState(settings);
  useEffect(() => setDraft(settings), [settings]);

  const NUMBERS = [
    {
      key: "min_cheaper_than",
      label: "Must undercut at least",
      suffix: "% of its peers",
      min: 50,
      max: 99,
    },
    {
      key: "min_discount_percent",
      label: "and be at least",
      suffix: "% below the median",
      min: 5,
      max: 60,
    },
    {
      key: "max_discount_percent",
      label: "but no more than",
      suffix: "% below it",
      min: 25,
      max: 90,
    },
    {
      key: "min_vendors",
      label: "Peers must span at least",
      suffix: " shops",
      min: 1,
      max: 5,
    },
  ];

  return (
    <div className="panel deal-panel">
      <div className="panel__head">
        <h2>How deals are found</h2>
        <button
          className="btn btn--ghost"
          onClick={onRefresh}
          disabled={busy}
          type="button"
        >
          <Refresh size={15} /> Look again now
        </button>
      </div>
      <div className="panel__body">
        <label className="switch">
          <input
            type="checkbox"
            checked={settings.enabled}
            disabled={busy}
            onChange={(event) => onChange({ enabled: event.target.checked })}
          />
          <span className="switch__track" />
          <span>Look for deals on a schedule</span>
        </label>

        <label className="field deal-panel__field">
          <span className="field__label">Look again every</span>
          <select
            value={settings.interval_hours}
            disabled={busy}
            onChange={(event) => onChange({ interval_hours: Number(event.target.value) })}
          >
            {(choices || []).map((hours) => (
              <option key={hours} value={hours}>
                {hours} hours
              </option>
            ))}
          </select>
        </label>

        {NUMBERS.map(({ key, label, suffix, min, max }) => (
          <label className="field deal-panel__field" key={key}>
            <span className="field__label">{label}</span>
            <input
              type="number"
              min={min}
              max={max}
              value={draft[key]}
              disabled={busy}
              onChange={(event) =>
                setDraft((current) => ({ ...current, [key]: Number(event.target.value) }))
              }
              // Committed on blur rather than on every keystroke: typing "8"
              // on the way to "80" would otherwise send a request that is
              // both rejected and, briefly, the truth.
              onBlur={() =>
                draft[key] !== settings[key] && onChange({ [key]: draft[key] })
              }
            />
            <span className="field__hint">{suffix}</span>
          </label>
        ))}

        {/* The ceiling is the one that needs explaining, because it reads
            backwards: an upper limit on how good a deal may be. It is there
            because past about two thirds off, a listing has stopped being the
            same object as the guns it is being compared against. */}
        <p className="muted deal-panel__note">
          The upper limit is not fussiness. Past roughly two thirds below the median a
          listing is usually not the same thing as its peers — a magazine, a bolt, a bare
          frame, a replica — and no threshold on price tells a mismatch from a bargain.
          Raising it fills this page with parts.
        </p>

        <dl className="deal-panel__last">
          <div>
            <dt>Last looked</dt>
            <dd>
              {settings.last_run_at ? formatRelative(settings.last_run_at) : "never"}
              {settings.last_status === "failed" && (
                <span className="chip chip--danger">failed</span>
              )}
            </dd>
          </div>
          <div>
            <dt>Found</dt>
            <dd>
              {settings.last_deal_count ?? "—"} from {settings.last_considered ?? "—"}{" "}
              comparable listings
              {settings.last_seconds != null && ` in ${settings.last_seconds}s`}
            </dd>
          </div>
        </dl>
        {settings.last_error && (
          <div className="alert alert--error">{settings.last_error}</div>
        )}
      </div>
    </div>
  );
}

export default function HotDeals() {
  useTitle("Hot deals");
  const { isAdmin } = useAuth();
  const [bucket, setBucket] = useState(null);
  // Null until the reader chooses, rather than a copy of the server's default
  // kept here: the same shape `bucket` uses for "everything", and it means the
  // default lives in exactly one place. What the select shows falls back to
  // the order the response says it was given.
  const [sort, setSort] = useState(null);
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (which, order) => {
    setError("");
    try {
      setState(await api.hotDeals({ bucket: which, sort: order }));
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load(bucket, sort);
  }, [load, bucket, sort]);

  // Every write answers with the whole page, so nothing here reloads: the
  // response *is* the new state, and a second request would leave the two
  // able to disagree for a moment.
  // The category and order being looked at, handed to every write so the page
  // it answers with is the page that is on screen. Without it, ticking a
  // checkbox on the Rifles tab came back as the whole catalog in the default
  // order and reset the list under the reader.
  const view = { bucket, sort };

  const send = async (call) => {
    setBusy(true);
    setError("");
    try {
      setState(await call());
    } catch (err) {
      // **Reload first, then report.** The server refused, so the page is now
      // showing a value that was never saved and has to be put back — but
      // `load` clears the error as it starts, so setting the message before
      // reloading wiped it and the refusal arrived as nothing happening at
      // all. The Playwright spec is what found that.
      await load(bucket, sort);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  if (error && state === null) {
    return (
      <div className="page">
        <div className="page__head">
          <h1>Hot deals</h1>
        </div>
        <div className="alert alert--error">
          <Warning size={16} /> {error}
        </div>
      </div>
    );
  }

  if (state === null) {
    return (
      <div className="page">
        <div className="page__head">
          <h1>Hot deals</h1>
        </div>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const total = state.buckets.reduce((sum, key) => sum + (state.counts[key] || 0), 0);

  return (
    <div className="page">
      <div className="page__head">
        <h1>
          <Flame size={20} /> Hot deals
        </h1>
        <span className="chip chip--neutral">
          {total} listing{total === 1 ? "" : "s"}
        </span>
      </div>

      <p className="muted deal-lede">
        Listings priced well below what the same gun usually sells for across every dealer
        here. Each one is compared only against others of the same model and cartridge,
        and only where several shops are selling it.
      </p>

      {error && (
        <div className="alert alert--error">
          <Warning size={16} /> {error}
        </div>
      )}

      <div className="deal-toolbar">
        {/* The Armory's and the Market's tab strip, not a third one. */}
        <div className="armory-tabs" role="tablist" aria-label="Category">
          <button
            type="button"
            role="tab"
            aria-selected={bucket === null}
            className={`btn ${bucket === null ? "btn--primary" : "btn--ghost"} btn--sm`}
            onClick={() => setBucket(null)}
          >
            Everything ({total})
          </button>
          {state.buckets.map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={bucket === key}
              className={`btn ${bucket === key ? "btn--primary" : "btn--ghost"} btn--sm`}
              onClick={() => setBucket(key)}
            >
              {state.labels[key]} ({state.counts[key] || 0})
            </button>
          ))}
        </div>

        {/* Labelled in words rather than by an aria-label alone: there is room
            for it here, and "Biggest discount" out of context does not say
            what it is the biggest of. The options and their wording come from
            the response, so this page and the email cannot drift on either. */}
        <label className="deal-sort">
          <span className="deal-sort__label">Sort by</span>
          <select
            className="select deal-sort__select"
            value={sort ?? state.sort}
            disabled={busy}
            onChange={(event) => setSort(event.target.value)}
          >
            {state.sorts.map((key) => (
              <option key={key} value={key}>
                {state.sort_labels[key]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {state.deals.length === 0 ? (
        <div className="panel">
          <div className="panel__body">
            <p style={{ margin: 0 }}>
              Nothing here at the moment. A listing has to be well under what several
              shops are asking for the same gun, which on a quiet week is nothing at all —
              and police surplus is a small enough corner of the catalog that it is often
              empty.
            </p>
          </div>
        </div>
      ) : (
        <div className="panel">
          <div className="panel__body">
            <ul className="deals">
              {state.deals.map((deal) => (
                <DealRow key={deal.item.id} deal={deal} />
              ))}
            </ul>
          </div>
        </div>
      )}

      <Subscription
        preference={state.preference}
        labels={state.labels}
        buckets={state.buckets}
        busy={busy}
        onChange={(body) => send(() => api.updateHotDealPreference(body, view))}
      />

      {isAdmin && state.settings && (
        <Controls
          settings={state.settings}
          choices={state.interval_choices}
          busy={busy}
          onChange={(body) => send(() => api.updateHotDealSettings(body, view))}
          onRefresh={() => send(() => api.refreshHotDeals(view))}
        />
      )}
    </div>
  );
}
