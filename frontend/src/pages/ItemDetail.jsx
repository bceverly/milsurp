/**
 * One listing: photo gallery, structured facts, description, and price history.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { useAuth } from "../auth.jsx";
import { formatDateTime, formatMoney, formatRelative, timeTitle } from "../format.js";
import AuthImage from "../components/AuthImage.jsx";
import NoPhoto from "../components/NoPhoto.jsx";

/** "percussion_revolver" as a person would write it.
 *
 * Derived rather than looked up: the armory's own labels come from an
 * admin-only endpoint, and this page is for everybody. */
function kindLabel(kind) {
  if (!kind) return null;
  const words = kind.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
import Modal from "../components/Modal.jsx";
import {
  Box,
  ChevronLeft,
  External,
  Eye,
  Star,
  TrendDown,
  X,
} from "../components/Icons.jsx";

/**
 * One labeled value.
 *
 * An empty one is normally left out entirely — a listing with no photograph
 * count should not say "Photos: none". The four fields describing the firearm
 * itself pass `always`, because for those the absence is the interesting part:
 * they are what the classifier failed on, and hiding them makes the listings
 * worth looking at the hardest ones to find. "Unknown" is the same word the
 * filter uses for them.
 */
/**
 * Where a derived value came from, said in the fewest words that are true.
 *
 * It is the difference between a caliber worth correcting and one worth
 * trusting. The shop published it, with the gun in front of them — or this
 * application read it out of a title, which is a guess. Somebody deciding
 * whether to override a field cannot tell those apart without being told, and
 * the six listings this shipped alongside were all of the second kind.
 *
 * Nothing is shown for a value of unrecorded origin. Every row written before
 * the sources existed has none, and inventing a label for "we do not know"
 * would put a confident word on the page where the honest answer is silence.
 */
const SOURCE_LABEL = {
  vendor: ["from the shop", "Published by the vendor in their own catalog"],
  derived: ["read from the listing", "Worked out from the title and description"],
  catalog: ["from the armory", "Filled in from the model this listing names"],
  override: ["corrected by hand", "Someone overrode this, knowing what the rules said"],
};

function Source({ source }) {
  const entry = source ? SOURCE_LABEL[source] : null;
  if (!entry) return null;
  return (
    <span className="fact__source" title={entry[1]}>
      {entry[0]}
    </span>
  );
}

//: How a curio reading was arrived at, in words, for the chip under it.
//:
//: Explanatory prose rather than a classification, which is why it lives here
//: and the *verdict* wording does not: "Not eligible by age" is sent by the
//: server so this page and the browse facet cannot come to say different
//: things, and these three sentences have nothing to drift from.
const CURIO_WHY = {
  vendor: ["the shop says so", "The listing itself calls this a C&R."],
  dated: ["from a stated date", "The listing gives a manufacture date."],
  year: [
    "from a year in the listing",
    "A year in the listing that is not the model's own designation — so it reads as a date rather than a pattern.",
  ],
};

//: Why a gun under fifty is not simply "not a C&R".
const CURIO_CAVEAT =
  "Worked out from what the shop wrote, against the fifty-year rule, and not a " +
  "compliance determination. A firearm under fifty may still be a curio — the " +
  "other tests are a museum curator's certification and being novel, rare or " +
  "bizarre, and neither is visible here. Check before you buy.";

function CurioFact({ item }) {
  if (!item.curio) return null;
  const why = CURIO_WHY[item.curio_evidence];
  const unknown = item.curio === "unknown";
  return (
    <div>
      <div className="fact__label">C&amp;R</div>
      <div
        className={`fact__value ${unknown ? "fact__value--unknown" : ""}`}
        title={CURIO_CAVEAT}
      >
        {item.curio_label}
      </div>
      <span className="fact__source" title={why ? why[1] : CURIO_CAVEAT}>
        {why ? why[0] : "nothing in the listing says"}
      </span>
    </div>
  );
}

function Fact({ label, children, always = false, source = null }) {
  const empty = children === null || children === undefined || children === "";
  if (empty && !always) return null;
  return (
    <div>
      <div className="fact__label">{label}</div>
      <div className={`fact__value ${empty ? "fact__value--unknown" : ""}`}>
        {empty ? "Unknown" : children}
      </div>
      {!empty && <Source source={source} />}
    </div>
  );
}

/**
 * One of the collector details, with the vendor's own words under it.
 *
 * The words are the point. "All matching" read out of "matching serial numbers
 * except the bolt" would be a claim the vendor never made; quoting the
 * sentence it came from lets whoever is about to spend the money see that it
 * was read right -- or that it was not.
 */
function Quoted({ label, value, quote }) {
  if (!value) return null;
  return (
    <div>
      <div className="fact__label">{label}</div>
      <div className="fact__value">{value}</div>
      {quote && <div className="fact__quote">“{quote}”</div>}
    </div>
  );
}

/** Yes, no, or nothing said -- in words that say which way round it is. */
function said(answer, yes, no) {
  if (answer === true) return yes;
  if (answer === false) return no;
  return null;
}

/** The whole gun's stated condition, which comes before the bore's. */
function ConditionFact({ item }) {
  return (
    <Quoted
      label="Condition"
      value={item.condition_grade_label}
      quote={(item.trait_quotes || {}).condition}
    />
  );
}

function CollectorFacts({ item }) {
  const quotes = item.trait_quotes || {};
  const finish = said(item.refinished, "Refinished", "Original");
  const remaining = item.finish_percent
    ? `${item.finish_percent}% of the finish remains`
    : null;
  return (
    <>
      <Quoted
        label="Import marks"
        value={said(item.import_marked, "Import marked", "None")}
        quote={quotes.import}
      />
      <Quoted
        label="Numbers"
        value={said(item.numbers_match, "All matching", "Not all matching")}
        quote={quotes.numbers}
      />
      <Quoted
        label="Finish"
        value={[finish, remaining].filter(Boolean).join(", ") || null}
        quote={quotes.finish}
      />
    </>
  );
}

/**
 * What the armory knows about the model this listing was matched to.
 *
 * A panel rather than more lines in the facts list, because it answers a
 * different question. The facts beside it describe *this listing*: the caliber
 * this rifle is, the country this one is said to be from. These describe the
 * **pattern** — what the row states about every gun of that design, whoever
 * is selling one — and the two genuinely disagree sometimes. A Steyr M95 in
 * 8x56mmR sold by a dealer who wrote 8x50mmR is not a bug in either place, and
 * putting both in one list would read as one.
 *
 * It also shows whether a person has vouched for the row. A pending model
 * decided nothing about this listing, and "awaiting approval" is the
 * difference between an answer and an unanswered question.
 */
/**
 * Correcting what the rules concluded about one listing.
 *
 * Everything on this page beyond the vendor's own words is derived and
 * recomputed on every scan -- which is what lets one rule fix reach eleven
 * thousand listings, and what made a correction typed into the database last
 * exactly until the next scan. An override outranks all of it.
 *
 * **A blank box means "no opinion", not "clear the field".** Only what is
 * filled in gets sent, so correcting a caliber never asserts that the country
 * is unknown. Emptying a box that had an override removes that one.
 *
 * Admin-only, because an override set by mistake is invisible afterwards: the
 * listing simply reads wrong and nothing on the page says why.
 */
function OverridePanel({ item, onChanged }) {
  const FIELDS = [
    ["caliber", "Caliber"],
    ["country", "Country"],
    ["manufacturer", "Manufacturer"],
    ["model", "Model"],
  ];
  const [saved, setSaved] = useState(null);
  const [form, setForm] = useState(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let canceled = false;
    api
      .itemOverride(item.id)
      .then((row) => {
        if (canceled) return;
        setSaved(row);
        setForm(Object.fromEntries(FIELDS.map(([k]) => [k, (row && row[k]) || ""])));
        setNote((row && row.note) || "");
      })
      .catch(() => {
        if (!canceled) setForm(Object.fromEntries(FIELDS.map(([k]) => [k, ""])));
      });
    return () => {
      canceled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const row = await api.setItemOverride(item.id, { ...form, note });
      setSaved(row);
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function drop() {
    setError(null);
    setBusy(true);
    try {
      await api.clearItemOverride(item.id);
      setSaved(null);
      setForm(Object.fromEntries(FIELDS.map(([k]) => [k, ""])));
      setNote("");
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (form === null) return null;

  return (
    <div className="panel">
      <div className="panel__head">
        <h2>Correct this listing</h2>
        {saved && (
          <button type="button" className="btn btn--ghost" onClick={drop} disabled={busy}>
            Remove correction
          </button>
        )}
      </div>
      <div className="panel__body">
        {error && <p className="alert alert--danger">{error}</p>}
        <p className="muted">
          These outrank everything the scan works out, and survive a re-scrape. Leave a
          box empty to let the rules answer for that field.
        </p>
        <form onSubmit={submit}>
          {FIELDS.map(([key, label]) => (
            <label className="field" key={key}>
              <span>{label}</span>
              <input
                className="input"
                value={form[key]}
                onChange={(event) => setForm({ ...form, [key]: event.target.value })}
              />
            </label>
          ))}
          <label className="field">
            <span>Why</span>
            <input
              className="input"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="So whoever reads this later knows"
            />
          </label>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? "Saving…" : "Save correction"}
          </button>
          {saved?.set_by_name && (
            <p className="muted">Last set by {saved.set_by_name}.</p>
          )}
        </form>
      </div>
    </div>
  );
}

function ArmoryPanel({ item, onClose }) {
  const rows = [
    ["Kind", item.model_kind ? kindLabel(item.model_kind) : null],
    ["Country of the pattern", item.model_country],
    ["Chambered in", item.model_calibers?.join(" · ")],
    ["Built by", item.model_makers?.join(" · ")],
  ];
  return (
    <Modal title={item.model} onClose={onClose}>
      <p className="armory-panel__lead">
        What the armory states about this pattern — not about this particular listing.
        Where the two disagree, the listing keeps its own answer.
      </p>
      <div className="detail__facts">
        {rows.map(([label, value]) => (
          <Fact key={label} label={label} always>
            {value || null}
          </Fact>
        ))}
      </div>
      {item.model_notes && <p className="armory-panel__notes">{item.model_notes}</p>}
      {item.model_status && item.model_status !== "approved" && (
        <p className="armory-panel__pending">
          This row is <strong>awaiting approval</strong>, so it filled nothing in on this
          listing. Nothing pending decides anything until somebody says yes.
        </p>
      )}
      <div className="armory-panel__actions">
        {item.model_reference_url && (
          <a
            className="btn btn--secondary btn--sm"
            href={item.model_reference_url}
            target="_blank"
            rel="noreferrer noopener"
          >
            <External size={14} />
            Reference
          </a>
        )}
        <Link
          className="btn btn--secondary btn--sm"
          to={`/?model=${item.firearm_model_id ?? ""}&availability=all`}
        >
          Every listing of this model
        </Link>
      </div>
    </Modal>
  );
}

/**
 * Where this listing sits among the others of the same gun.
 *
 * **The bar is scaled by rank, not by dollars**, and that is the whole design.
 * Surplus prices are skewed hard enough to make a dollar axis useless: the 95
 * Walther PPs in this catalog run $280 to $11,995 with a median of $600, so a
 * dollar-scaled bar puts nine of them in ten inside its leftmost tenth. Scaled
 * by rank, every distribution draws legibly, the median is always the middle
 * of the bar — one reading to learn — and the marker's position *is* the
 * sentence underneath it: cheaper than N% of them.
 *
 * The ends carry the true cheapest and dearest, so nothing about the range is
 * hidden by the choice; the graduations carry the dollar values a quarter,
 * half and three-quarters of the way along.
 */
/**
 * Watch this listing, and optionally name the price you would pay.
 *
 * The star is a *state*, not an event: it renders filled or empty from the
 * item's own response, and clicking it is idempotent server-side, so a double
 * click leaves one watch rather than an error.
 *
 * The target is deliberately behind the star rather than beside it. Most
 * watches have no number on them — "keep an eye on this" — and putting a price
 * field in front of everybody asks a question they have not got to yet.
 */
function WatchControl({ item }) {
  const [watching, setWatching] = useState(Boolean(item.watched));
  const [target, setTarget] = useState(
    item.watch_target_price == null ? "" : String(item.watch_target_price),
  );
  const [note, setNote] = useState(item.watch_note || "");
  const [alertNow, setAlertNow] = useState(Boolean(item.watch_alert_immediately));
  const [alertBack, setAlertBack] = useState(Boolean(item.watch_alert_restock));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // The item can change under this component when the route does.
  useEffect(() => {
    setWatching(Boolean(item.watched));
    setTarget(item.watch_target_price == null ? "" : String(item.watch_target_price));
    setNote(item.watch_note || "");
    setAlertNow(Boolean(item.watch_alert_immediately));
    setAlertBack(Boolean(item.watch_alert_restock));
    setOpen(false);
    setError("");
  }, [
    item.id,
    item.watched,
    item.watch_target_price,
    item.watch_note,
    item.watch_alert_immediately,
    item.watch_alert_restock,
  ]);

  const save = async (body) => {
    setBusy(true);
    setError("");
    try {
      await api.watch(item.id, body);
      setWatching(true);
    } catch (err) {
      setError(err?.message || "Could not save that.");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async () => {
    if (!watching) return save({});
    setBusy(true);
    setError("");
    try {
      await api.unwatch(item.id);
      setWatching(false);
      setTarget("");
      setNote("");
      setAlertNow(false);
      setOpen(false);
    } catch (err) {
      setError(err?.message || "Could not stop watching.");
    } finally {
      setBusy(false);
    }
    return undefined;
  };

  return (
    <div className="watch">
      <div className="watch__row">
        <button
          type="button"
          className={`btn btn--sm ${watching ? "btn--primary" : "btn--ghost"}`}
          onClick={toggle}
          disabled={busy}
          aria-pressed={watching}
        >
          <Star filled={watching} size={16} />
          {watching ? "Watching" : "Watch"}
        </button>
        {watching && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => setOpen((was) => !was)}
            aria-expanded={open}
          >
            {target === ""
              ? "Set a target"
              : `Target ${formatMoney(Number(target), item.currency)}`}
          </button>
        )}
      </div>

      {watching && open && (
        <div className="watch__form">
          <label className="watch__field">
            <span>Tell me if it drops below</span>
            <input
              className="input"
              type="number"
              min="0"
              step="1"
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              placeholder="Any change"
            />
          </label>
          <label className="watch__field">
            <span>Note to yourself</span>
            <input
              className="input"
              type="text"
              maxLength={200}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Optional"
            />
          </label>
          {/* Only offered with a target named: "tell me the moment it reaches
              nothing" is not a request, and an alert with no threshold would
              fire on every price change forever. */}
          <label className="watch__check">
            <input
              type="checkbox"
              checked={alertNow && target !== ""}
              disabled={target === ""}
              onChange={(event) => setAlertNow(event.target.checked)}
            />
            <span>Email me the moment it gets there, without waiting for a digest</span>
          </label>
          {/* No target needed: for a sold-out CMP grade there is no price to
              wait for, only its return. One email per return. */}
          <label className="watch__check">
            <input
              type="checkbox"
              checked={alertBack}
              onChange={(event) => setAlertBack(event.target.checked)}
            />
            <span>Email me the moment it is back in stock</span>
          </label>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            disabled={busy}
            onClick={() =>
              save({
                target_price: target === "" ? null : Number(target),
                note: note || null,
                alert_immediately: alertNow && target !== "",
                alert_restock: alertBack,
              }).then(() => setOpen(false))
            }
          >
            Save
          </button>
          {/* Said plainly, because it is the surprising half: a target means
              "do not tell me until then", so ordinary movement goes quiet. */}
          <p className="watch__hint">
            With a target set, only a price at or below it is emailed — and a sale always
            is.
          </p>
        </div>
      )}
      {error && <p className="watch__error">{error}</p>}
    </div>
  );
}

/**
 * Other listings worth looking at, each saying why it is there.
 *
 * The spectrum above answers "is this a good deal?" and stops one step short:
 * it says *cheaper than 8% of them* and offers no way to reach the them. A
 * reader told their rifle is dear had to retype the model into the search box.
 *
 * One list rather than sections, with the reason on the row. Sections would
 * put a heading above a single card on most pages, and the reason is a
 * property of the row anyway: two rows from different bands sit together
 * happily as long as each says which it came in on.
 */
function SimilarListings({ rows }) {
  if (!rows.length) return null;
  return (
    <div className="panel" style={{ marginTop: 20 }}>
      <div className="panel__head">
        <h2>Similar listings</h2>
        <span className="chip chip--neutral">{rows.length}</span>
      </div>
      <div className="panel__body">
        <ul className="similar">
          {rows.map(({ item, rung, label }) => (
            <li key={item.id} className="similar__row">
              <Link className="similar__link" to={`/items/${item.id}`}>
                {/* AuthImage, not <img>: the photo store needs an
                    Authorization header, so a plain src renders a broken
                    icon. See components/AuthImage.jsx. */}
                <AuthImage
                  className="similar__thumb"
                  src={item.thumbnail_url}
                  alt=""
                  loading="lazy"
                />
                <span className="similar__text">
                  <span className="similar__title">{item.title}</span>
                  <span className="similar__meta">
                    {item.site_name}
                    {/* The band, in words the server chose. Kept out of the
                        link's accessible name: it repeats down the list and a
                        screen reader reading it on every row is noise. */}
                    <span className="similar__why" data-rung={rung}>
                      {label}
                    </span>
                  </span>
                </span>
                <span className="similar__price">
                  {item.current_price == null
                    ? "Call for price"
                    : formatMoney(item.current_price, item.currency)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/**
 * What this gun costs at your dealer, not on the shelf.
 *
 * Price, the shop's own firearm shipping and your transfer fee, added up. A
 * part nobody stated is named as missing and the total marked "at least",
 * never treated as free. The fee is set right here, where the question comes
 * up, rather than on a settings page nobody would look for it on.
 */
function DeliveredPrice({ item, onFeeSaved }) {
  const [editing, setEditing] = useState(false);
  const [fee, setFee] = useState("");
  const [error, setError] = useState(null);
  if (item.delivered_price == null) return null;

  async function save(event) {
    event.preventDefault();
    setError(null);
    const value = fee.trim() === "" ? null : Number(fee);
    if (value !== null && (Number.isNaN(value) || value < 0)) {
      setError("A dollar amount, or blank to clear it.");
      return;
    }
    try {
      await api.saveCosts({ ffl_transfer_fee: value });
      setEditing(false);
      onFeeSaved();
    } catch (err) {
      setError(err.message);
    }
  }

  const money = (value) => formatMoney(value, item.currency);
  return (
    <div className="delivered" data-testid="delivered-price">
      <div className="delivered__total">
        {item.delivered_complete ? "About " : "At least "}
        <strong>{money(item.delivered_price)}</strong> delivered to your dealer
      </div>
      <div className="delivered__parts">
        {money(item.current_price)} +{" "}
        {item.shipping != null ? (
          <>{money(item.shipping)} shipping</>
        ) : (
          <span className="delivered__missing" title={item.shipping_note || undefined}>
            shipping the shop does not state
          </span>
        )}{" "}
        +{" "}
        {item.transfer_fee != null ? (
          <>{money(item.transfer_fee)} transfer</>
        ) : (
          <span className="delivered__missing">your transfer fee</span>
        )}{" "}
        {!editing && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => {
              setFee(item.transfer_fee != null ? String(item.transfer_fee) : "");
              setEditing(true);
            }}
          >
            {item.transfer_fee != null ? "Change fee" : "Set your fee"}
          </button>
        )}
      </div>
      {item.shipping_note && (
        <div className="delivered__note">
          {item.site_name}: {item.shipping_note}
        </div>
      )}
      {editing && (
        <form className="delivered__form" onSubmit={save}>
          <label className="visually-hidden" htmlFor="ffl-fee">
            Your dealer&rsquo;s transfer fee
          </label>
          <input
            id="ffl-fee"
            className="input"
            inputMode="decimal"
            placeholder="e.g. 25"
            value={fee}
            autoFocus
            onChange={(event) => setFee(event.target.value)}
          />
          <button type="submit" className="btn btn--primary btn--sm">
            Save
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => setEditing(false)}
          >
            Cancel
          </button>
          <span className="field__hint">
            What your dealer charges to receive a gun for you. 0 if you receive curios on
            a C&amp;R license. Used on every listing.
          </span>
        </form>
      )}
      {error && <p className="alert alert--error">{error}</p>}
    </div>
  );
}

/**
 * "Will it drop?" -- how this shop cuts prices, beside how long this has been up.
 *
 * Only for a shop that has cut prices often enough to have a habit (ten
 * listings or more), and only while this one is for sale. Said as what the
 * shop has done, not as a forecast: "usually around day 18" next to "this one
 * is on day 12" lets the reader weigh waiting against losing it.
 */
function WillItDrop({ item }) {
  const habit = item.markdown_habit;
  if (!habit) return null;
  const day = Math.round(habit.median_day);
  const listed = habit.listed_days;
  const past = listed != null && listed > day;
  return (
    <p className="will-it-drop" data-testid="will-it-drop">
      <TrendDown size={14} /> {habit.site_name || "This shop"} cuts prices: {habit.drops}{" "}
      listings reduced since we started watching, usually by about{" "}
      {Math.round(habit.median_pct)}% around day {day}.{" "}
      {listed != null &&
        (past
          ? `This one has been up ${listed} days and has not been cut yet.`
          : `This one is on day ${listed}.`)}
    </p>
  );
}

/**
 * What guns like this one were asking when they left the shelf.
 *
 * Beside the spectrum, which places this listing among the ones still for
 * sale: those over-represent whatever has not sold, and this is the other
 * half. Worded as an asking price, because it is one.
 */
function LeftTheShelf({ item }) {
  const band = item.departures;
  if (!band) return null;
  const money = (value) => formatMoney(value, band.currency);
  const what = item.departures_by === "model" ? band.value : `${band.value} guns`;
  return (
    <p className="departures" data-testid="departures">
      <strong>{band.listings}</strong> {what} left the shelf recently, typically asking{" "}
      <strong>{money(band.median)}</strong> ({money(band.low)}–{money(band.high)}) when
      they went.
      {band.concentrated && (
        <span className="chip chip--warning market-chip">mostly one shop</span>
      )}
    </p>
  );
}

/**
 * "I bought this": adds it to your collection, filled in from the listing.
 */
function BoughtThis({ item }) {
  const [state, setState] = useState(null);
  async function add() {
    setState({ busy: true });
    try {
      await api.boughtThis(item.id);
      setState({ done: true });
    } catch (err) {
      setState({ error: err.message });
    }
  }
  if (state?.done) {
    return (
      <p className="alert alert--success" role="status">
        Added to your collection. <Link to="/collection">Open it</Link> to correct the
        price or the date.
      </p>
    );
  }
  return (
    <>
      <button
        type="button"
        className="btn btn--secondary"
        onClick={add}
        disabled={state?.busy}
      >
        <Box size={15} /> I bought this
      </button>
      {state?.error && <p className="alert alert--error">{state.error}</p>}
    </>
  );
}

function PriceSpectrum({ position, currency }) {
  if (!position) return null;
  // Two different numbers, and mixing them up caused both of this widget's
  // bugs. `position` is where the marker goes — rank across the whole bar, so
  // the extremes reach the ends. `cheaper_than` is the statistic the sentence
  // quotes, and it counts the peers this one *undercuts*: naming it
  // "percentile" and filling it with the fraction below the price made a $350
  // pistol with 24 dearer peers read "cheaper than 7%".
  const {
    count,
    vendors,
    low,
    high,
    q1,
    median,
    q3,
    cheaper_than: cheaperThan,
  } = position;
  const at = position.position;
  const marks = [
    { at: 25, value: q1 },
    { at: 50, value: median },
    { at: 75, value: q3 },
  ];

  return (
    <div className="spectrum">
      <div className="spectrum__head">
        <strong>Where this sits</strong>
        <span className="spectrum__peers">
          {count} listing{count === 1 ? "" : "s"} of this model
          {vendors > 1 ? ` across ${vendors} vendors` : ""}
        </span>
      </div>

      <div className="spectrum__rail">
        {marks.map((mark) => (
          <span
            key={mark.at}
            className={`spectrum__tick ${mark.at === 50 ? "spectrum__tick--median" : ""}`}
            style={{ left: `${mark.at}%` }}
          />
        ))}
        {/* aria-hidden: the sentence below says the same thing in words, and
            a screen reader reading a decorative bar adds nothing. */}
        <span
          className="spectrum__marker"
          style={{ left: `${at}%` }}
          aria-hidden="true"
        />
      </div>

      <div className="spectrum__scale">
        {marks.map((mark) => (
          <span key={mark.at} className="spectrum__label" style={{ left: `${mark.at}%` }}>
            {formatMoney(mark.value, currency)}
          </span>
        ))}
      </div>

      <div className="spectrum__ends">
        <span>{formatMoney(low, currency)}</span>
        <span>{formatMoney(high, currency)}</span>
      </div>

      <p className="spectrum__verdict">
        {at <= 0
          ? "The cheapest one listed."
          : at >= 100
            ? "The dearest one listed."
            : `Cheaper than ${cheaperThan}% of them.`}{" "}
        <span className="spectrum__note">
          Spaced by rank, not by price — the middle of the bar is the median.
        </span>
      </p>
    </div>
  );
}

/**
 * Price-over-time sparkline.
 *
 * Hand-drawn SVG rather than a charting library: this is a single series of a
 * handful of points, and a chart package would be a large dependency for one
 * polyline.
 */
function PriceSparkline({ history }) {
  if (!history || history.length < 2) return null;

  const width = 100;
  const height = 100;
  const prices = history.map((point) => point.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  // A flat series would divide by zero; give it a nominal range so the line
  // renders through the middle instead of collapsing.
  const span = max - min || Math.max(1, max * 0.1);

  const points = history.map((point, index) => {
    const x = (index / (history.length - 1)) * width;
    const y = height - ((point.price - min) / span) * (height * 0.82) - height * 0.09;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const dropped = prices[prices.length - 1] < prices[0];
  const stroke = dropped ? "var(--green-600)" : "var(--navy-600)";

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Price history: ${formatMoney(prices[0])} to ${formatMoney(
        prices[prices.length - 1],
      )}`}
    >
      <polyline
        points={`0,${height} ${points.join(" ")} ${width},${height}`}
        fill={dropped ? "var(--green-100)" : "var(--navy-50)"}
        stroke="none"
      />
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={stroke}
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * What the shop's emails offer right now: a discount, a code, until when.
 * Never applied to the price above -- a price you get only at checkout with a
 * code is not the shelf price. A personal one is a welcome code sent to the
 * notification account, and only administrators are ever sent those.
 */
function ShopOffers({ offers, siteName }) {
  if (!offers?.length) return null;
  return (
    <div className="panel offers-panel" style={{ marginTop: 20 }}>
      <div className="panel__head">
        <h2>From {siteName || "the shop"}&apos;s emails</h2>
      </div>
      <div className="panel__body">
        <ul className="offers-panel__list">
          {offers.map((offer) => (
            <li key={`${offer.received_at}-${offer.code || offer.discount}`}>
              <strong>{offer.discount || "An offer"}</strong>
              {offer.code && (
                <>
                  {" "}
                  with code <code className="offers-panel__code">{offer.code}</code>
                </>
              )}
              {offer.terms && <span className="muted"> — {offer.terms}</span>}
              <div className="muted offers-panel__meta">
                {offer.ends_at
                  ? `Ends ${formatDateTime(offer.ends_at)}.`
                  : `No end date given; shown until ${formatDateTime(offer.shown_until)}.`}{" "}
                From their email of {formatRelative(offer.received_at)}, “{offer.subject}
                ”.
                {offer.personal && (
                  <span className="chip chip--neutral offers-panel__personal">
                    welcome code for the notification account
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function ItemDetail() {
  const { itemId } = useParams();
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [activePhoto, setActivePhoto] = useState(0);
  const [lightbox, setLightbox] = useState(false);
  const [armoryOpen, setArmoryOpen] = useState(false);
  const [spectrum, setSpectrum] = useState(null);
  const [similar, setSimilar] = useState([]);

  useTitle(item?.title);

  const reloadItem = useCallback(() => {
    api
      .item(itemId)
      .then(setItem)
      .catch((err) => setError(err.message));
  }, [itemId]);

  useEffect(() => {
    let canceled = false;
    setItem(null);
    setActivePhoto(0);
    api
      .item(itemId)
      .then((result) => {
        if (!canceled) setItem(result);
      })
      .catch((err) => {
        if (!canceled) setError(err.message);
      });
    return () => {
      canceled = true;
    };
  }, [itemId]);

  // Fetched separately, and allowed to fail quietly. It answers "nothing to
  // say" for most listings — it needs a matched model, a maker, a cartridge
  // and three peers — so the page must not wait on it or complain about it.
  useEffect(() => {
    let canceled = false;
    setSpectrum(null);
    api
      .itemPricePosition(itemId)
      .then((result) => !canceled && setSpectrum(result))
      .catch(() => !canceled && setSpectrum(null));
    return () => {
      canceled = true;
    };
  }, [itemId]);

  // Same shape as the spectrum above: separate, and allowed to fail quietly.
  // It answers with nothing for a listing that states neither a model nor a
  // cartridge, and the page is complete without it.
  useEffect(() => {
    let canceled = false;
    setSimilar([]);
    api
      .itemSimilar(itemId)
      .then((rows) => !canceled && setSimilar(rows || []))
      .catch(() => !canceled && setSimilar([]));
    return () => {
      canceled = true;
    };
  }, [itemId]);

  // Arrow keys move through the gallery; Escape closes the lightbox.
  useEffect(() => {
    if (!item?.photos?.length) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape" && lightbox) setLightbox(false);
      if (event.key === "ArrowRight") {
        setActivePhoto((index) => Math.min(index + 1, item.photos.length - 1));
      }
      if (event.key === "ArrowLeft") {
        setActivePhoto((index) => Math.max(index - 1, 0));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, lightbox]);

  if (error) {
    return (
      <div>
        <div className="alert alert--error" role="alert">
          {error}
        </div>
        <button className="btn btn--secondary" onClick={() => navigate(-1)}>
          <ChevronLeft size={16} />
          Back
        </button>
      </div>
    );
  }

  if (!item) {
    return (
      <div className="loading-row">
        <div className="spinner" />
        Loading listing…
      </div>
    );
  }

  const photos = item.photos || [];
  // Only the fields whose origin was recorded; the rest are simply absent,
  // which is every row written before the sources existed.
  const sources = item.sources || {};
  const current = photos[activePhoto];
  const dropped = item.price_drop > 0;
  const history = [...(item.price_history || [])].sort(
    (a, b) => new Date(a.observed_at) - new Date(b.observed_at),
  );

  return (
    <div>
      <div className="page-head">
        <button className="btn btn--ghost" onClick={() => navigate(-1)}>
          <ChevronLeft size={17} />
          Back to inventory
        </button>
      </div>

      <div className="detail">
        <div>
          <div className="gallery__main">
            {current ? (
              <button
                type="button"
                className="gallery__zoom"
                onClick={() => setLightbox(true)}
                aria-label={`View ${item.title} full size`}
              >
                <AuthImage src={current.url} alt={item.title} />
              </button>
            ) : (
              <figure className="gallery__none">
                <NoPhoto className="gallery__none-image" caption="No photos captured" />
                <figcaption>No photos captured</figcaption>
              </figure>
            )}
          </div>

          {photos.length > 1 && (
            <div className="gallery__thumbs">
              {photos.map((photo, index) => (
                <button
                  key={photo.id}
                  className={`gallery__thumb ${
                    index === activePhoto ? "gallery__thumb--active" : ""
                  }`}
                  onClick={() => setActivePhoto(index)}
                  aria-label={`Photo ${index + 1} of ${photos.length}`}
                  aria-current={index === activePhoto}
                >
                  <AuthImage
                    src={photo.thumbnail_url || photo.url}
                    alt=""
                    loading="lazy"
                  />
                </button>
              ))}
            </div>
          )}
        </div>

        <div>
          <h1 className="detail__title">{item.title}</h1>

          <div className="detail__chips">
            {item.site_name && <span className="chip chip--info">{item.site_name}</span>}
            {item.category && <span className="chip chip--neutral">{item.category}</span>}
            {/* The vendor's own category is often the same word as the inferred
                type ("Rifle"), so only show the inferred one when it adds
                something the category did not already say. */}
            {item.is_rifle && !/rifle/i.test(item.category || "") && (
              <span className="chip chip--neutral">Rifle</span>
            )}
            {item.is_pistol && !/handgun|pistol/i.test(item.category || "") && (
              <span className="chip chip--neutral">Handgun</span>
            )}
            {item.is_sold && <span className="chip chip--danger">Sold</span>}
            {!item.is_active && <span className="chip chip--warning">De-listed</span>}
            {dropped && (
              <span className="chip chip--success">
                <TrendDown size={13} />
                Reduced {formatMoney(item.price_drop, item.currency)}
              </span>
            )}
          </div>

          <div className="detail__price">
            <span
              className={`detail__price-now ${dropped ? "detail__price-now--drop" : ""}`}
            >
              {formatMoney(item.current_price, item.currency)}
            </span>
            {dropped && (
              <span className="detail__price-was">
                {formatMoney(item.previous_price, item.currency)}
              </span>
            )}
          </div>
          {/* Directly under the shelf price, because it is the same question
              answered honestly: what this costs by the time it is yours. */}
          <DeliveredPrice item={item} onFeeSaved={reloadItem} />
          {/* Beside the price, because it is a question about the price:
              whether waiting is likely to make it smaller. */}
          <WillItDrop item={item} />

          <div className="detail__facts">
            {/* The armory's answer first, when it has one. It is the only
                line here that somebody vouched for rather than the software
                inferring it, so it says so, and it links to whatever is
                known about the gun. */}
            {item.model && (
              <Fact label="Model" always>
                <Link
                  to={`/?model=${item.firearm_model_id ?? ""}`}
                  className="detail__model"
                >
                  {item.model}
                </Link>
                {item.model_kind && (
                  <span className="detail__model-kind">{kindLabel(item.model_kind)}</span>
                )}{" "}
                {/* The reference link used to sit here on its own, which put
                    the least of what the armory knows on the page and left
                    the rest — the pattern's country, what it chambers, who
                    built it — reachable only by going to the admin page and
                    searching for the row by name. */}
                <button
                  type="button"
                  className="btn btn--ghost btn--sm detail__armory-open"
                  onClick={() => setArmoryOpen(true)}
                >
                  <Eye size={13} />
                  What the armory knows
                </button>
              </Fact>
            )}
            {/* Ahead of the rest: for somebody buying to their own license
                it decides whether the listing is reachable at all. */}
            <CurioFact item={item} />
            <Fact label="Made">{item.manufacture_year}</Fact>
            <Fact label="Manufacturer" always source={sources.manufacturer}>
              {item.manufacturer}
            </Fact>
            <Fact label="Caliber" always source={sources.caliber}>
              {item.caliber}
            </Fact>
            <Fact label="Country" always source={sources.country}>
              {item.country}
            </Fact>
            {/* The whole gun, then its bore, then the details a collector
                checks next -- what sets the price within a model. Only where
                the vendor said, and in their words. */}
            <ConditionFact item={item} />
            <Fact label="Bore condition" always source={sources.condition}>
              {item.condition}
            </Fact>
            <CollectorFacts item={item} />
            <Fact label="Lowest seen">
              {item.lowest_price ? formatMoney(item.lowest_price, item.currency) : null}
            </Fact>
            <Fact label="First seen">
              <span title={timeTitle(item.first_seen_at)}>
                {formatRelative(item.first_seen_at)}
              </span>
            </Fact>
            <Fact label="Last seen">
              <span title={timeTitle(item.last_seen_at)}>
                {formatRelative(item.last_seen_at)}
              </span>
            </Fact>
            <Fact label="Photos">{photos.length || null}</Fact>
          </div>

          {/* Directly under the facts and above the buy button, because it is
              the thing somebody is about to act on: it answers "is this a good
              deal?", which is the question the catalog exists for. */}
          <PriceSpectrum position={spectrum} currency={item.currency} />
          <LeftTheShelf item={item} />

          {/* Under the spectrum and above the buy button: the spectrum says
              whether this is a good price, and watching is what somebody does
              when the answer is "not yet". */}
          <WatchControl item={item} />

          <a
            className="btn btn--primary"
            href={item.url}
            target="_blank"
            // noreferrer also stops the vendor learning where the click came from.
            rel="noopener noreferrer"
          >
            <External size={16} />
            View on {item.site_name || "vendor site"}
          </a>
          {/* After the buy button, for the step that comes after it. Only for
              a firearm: a collection is a list of guns. */}
          {item.delivered_price != null && <BoughtThis item={item} />}

          <ShopOffers offers={item.offers} siteName={item.site_name} />

          {item.description && (
            <div className="panel" style={{ marginTop: 20 }}>
              <div className="panel__head">
                <h2>Description</h2>
              </div>
              <div className="panel__body">
                <div className="detail__description">{item.description}</div>
              </div>
            </div>
          )}

          <div className="panel">
            <div className="panel__head">
              <h2>Price history</h2>
              <span className="chip chip--neutral">
                {history.length} observation{history.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="panel__body">
              {history.length === 0 && (
                <p style={{ color: "var(--ink-500)", margin: 0, fontSize: 14 }}>
                  No price observations recorded yet.
                </p>
              )}
              {history.length === 1 && (
                <p style={{ color: "var(--ink-500)", margin: 0, fontSize: 14 }}>
                  Seen at {formatMoney(history[0].price, history[0].currency)} on{" "}
                  {formatDateTime(history[0].observed_at)}. A second observation appears
                  the first time the price changes.
                </p>
              )}
              {history.length > 1 && (
                <>
                  <PriceSparkline history={history} />
                  <table className="price-table">
                    <tbody>
                      {[...history].reverse().map((point, index) => (
                        // The index is a tiebreaker, not the key: two
                        // observations can share a timestamp, and PricePointOut
                        // carries no id to use instead. Safe here where the
                        // rule usually is not, because these rows hold no state
                        // of their own -- nothing to attach to the wrong row
                        // when the list grows.
                        // eslint-disable-next-line react/no-array-index-key
                        <tr key={`${point.observed_at}-${index}`}>
                          <td>{formatMoney(point.price, point.currency)}</td>
                          <td title={timeTitle(point.observed_at)}>
                            {formatDateTime(point.observed_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          </div>

          <SimilarListings rows={similar} />
        </div>
      </div>

      {isAdmin && <OverridePanel item={item} onChanged={reloadItem} />}

      {armoryOpen && item.model && (
        <ArmoryPanel item={item} onClose={() => setArmoryOpen(false)} />
      )}

      {lightbox && current && (
        <div className="lightbox" role="dialog" aria-modal="true" aria-label={item.title}>
          {/* Click-anywhere-to-close, as its own presentational layer. The
              dialog itself must not carry the handler: a click listener on a
              non-interactive role is one no keyboard can reach, and the
              surround is decoration. Escape closes it and the button below is
              the control a screen reader announces, so this is a convenience
              and not the only way out. */}
          <div
            className="lightbox__backdrop"
            role="presentation"
            onClick={() => setLightbox(false)}
          />
          <button
            className="lightbox__close"
            onClick={() => setLightbox(false)}
            aria-label="Close photo"
          >
            <X size={20} />
          </button>
          <AuthImage src={current.url} alt={item.title} />
        </div>
      )}
    </div>
  );
}
