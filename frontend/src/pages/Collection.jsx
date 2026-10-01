/**
 * Your collection: what you own, what you paid, and what it is worth now.
 *
 * Everything else here is about buying; this is about having bought. Each gun
 * is matched to an armory model from its title, the way a listing is, and
 * valued against that model's listings -- what they were asking when they left
 * the shelf where there is a sample of that, what they are asking now where
 * there is not. See services/collection.py.
 *
 * The worth is always said with its basis beside it. "About $450" means
 * nothing without "what K31s were asking when they left the shelf", and a gun
 * the market cannot price says so rather than showing a number.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { useDebounced, useTitle } from "../hooks.js";
import { formatDate, formatMoney } from "../format.js";
import Modal from "../components/Modal.jsx";
import Field from "../components/Field.jsx";
import { Box, Download, Plus, Trash } from "../components/Icons.jsx";

const GRADES = [
  { value: "", label: "Not graded" },
  { value: "like_new", label: "Like new" },
  { value: "excellent", label: "Excellent" },
  { value: "very_good", label: "Very good" },
  { value: "good", label: "Good" },
  { value: "fair", label: "Fair" },
  { value: "poor", label: "Poor" },
];

const EMPTY = {
  title: "",
  caliber: "",
  manufacturer: "",
  condition_grade: "",
  acquired_on: "",
  paid: "",
  acquired_from: "",
  notes: "",
};

/** The form's strings as the API wants them: blanks become nulls. */
function payloadOf(form) {
  const text = (value) => (value.trim() === "" ? null : value.trim());
  return {
    title: form.title.trim(),
    caliber: text(form.caliber),
    manufacturer: text(form.manufacturer),
    condition_grade: form.condition_grade || null,
    acquired_on: form.acquired_on || null,
    paid: form.paid === "" ? null : Number(form.paid),
    acquired_from: text(form.acquired_from),
    notes: text(form.notes),
  };
}

function formOf(row) {
  return Object.fromEntries(
    Object.keys(EMPTY).map((key) => [key, row[key] == null ? "" : String(row[key])]),
  );
}

/**
 * The inventory search that returns the listings a value was drawn from.
 *
 * The same conditions the valuation used: this model, priced guns and no
 * parts kits (`guns_only`), in the owner's condition when the value was
 * narrowed to it, and either for sale now or sold or taken down. The server
 * holds the two to the same listings in test_departures_delivered_collection.
 */
function comparablesSearch(row, departed) {
  const params = new URLSearchParams({
    model: String(row.firearm_model_id),
    guns_only: "true",
  });
  if (row.valuation?.like_for_like && row.condition_grade) {
    params.set("grade", row.condition_grade);
  }
  if (departed) params.set("availability", "left");
  return `/?${params.toString()}`;
}

/** What the worth figure was worked out from, in words. */
function basisOf(valuation, model) {
  const like = valuation.like_for_like ? " in the same condition" : "";
  return valuation.basis === "left"
    ? `What ${model}s${like} were asking when they left the shelf`
    : `What ${model}s${like} are asking now`;
}

/**
 * The estimate, the range around it, and a link to the listings behind it.
 *
 * The range is the middle half of whichever set of listings set the number
 * -- the same quartiles the Market uses -- so "about $995" arrives with how
 * much the listings it came from disagree.
 */
function Worth({ row }) {
  const valuation = row.valuation;
  const departed = valuation.basis === "left";
  const band = departed ? valuation.departed : valuation.shelf;
  return (
    <>
      <strong>{formatMoney(valuation.estimate)}</strong>
      {band && (
        <div className="collection-range">
          {formatMoney(band.low)}–{formatMoney(band.high)}
        </div>
      )}
      <div className="muted collection-sub">{basisOf(valuation, row.model)}</div>
      {band && (
        <Link className="collection-sub" to={comparablesSearch(row, departed)}>
          See the {band.listings} listing{band.listings === 1 ? "" : "s"}
        </Link>
      )}
    </>
  );
}

function Totals({ totals }) {
  if (!totals.count) return null;
  const change =
    totals.compared_count > 0 && totals.compared_paid > 0
      ? (totals.compared_value - totals.compared_paid) / totals.compared_paid
      : null;
  return (
    <div className="week-stats collection-totals" data-testid="collection-totals">
      <div className="week-stat">
        <span className="week-stat__value">{totals.count}</span>
        <span className="week-stat__label">{totals.count === 1 ? "gun" : "guns"}</span>
      </div>
      <div className="week-stat">
        <span className="week-stat__value">{formatMoney(totals.paid)}</span>
        <span className="week-stat__label">
          paid{totals.paid_count < totals.count ? ` (${totals.paid_count} say)` : ""}
        </span>
      </div>
      <div className="week-stat">
        <span className="week-stat__value">{formatMoney(totals.value)}</span>
        <span className="week-stat__label">
          worth about
          {totals.valued_count < totals.count
            ? ` (${totals.valued_count} the market can price)`
            : ""}
        </span>
      </div>
      {change !== null && (
        <div className="week-stat">
          <span className="week-stat__value">
            {change >= 0 ? "+" : "−"}
            {Math.abs(Math.round(change * 100))}%
          </span>
          <span className="week-stat__label">
            on what you paid, over the {totals.compared_count} with both
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Which armory model the gun is, chosen by its owner.
 *
 * A row used to be matched from its title and nothing else, so "Carcano
 * Carbine" -- a fair name for a Moschetto -- matched no model and could not be
 * valued, and the only way forward was guessing the words the armory happens
 * to use. The owner knows what the gun is. Typing searches the armory's
 * approved models by name and by every spelling on them.
 */
function ModelPicker({ model, onChoose }) {
  const [open, setOpen] = useState(!model);
  const [search, setSearch] = useState("");
  const [choices, setChoices] = useState([]);
  const term = useDebounced(search, 250);

  useEffect(() => {
    if (!open) return undefined;
    let live = true;
    api
      .collectionModels(term)
      .then((rows) => live && setChoices(rows))
      .catch(() => live && setChoices([]));
    return () => {
      live = false;
    };
  }, [open, term]);

  if (!open && model) {
    return (
      <div className="model-picker">
        <span className="model-picker__label">Model</span>
        <div className="model-picker__current">
          <strong>{model.name}</strong>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => setOpen(true)}
          >
            Change
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => {
              onChoose(null);
              setOpen(true);
            }}
          >
            Not this model
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="model-picker">
      <label className="model-picker__label" htmlFor="model-search">
        Model
      </label>
      <input
        id="model-search"
        className="input"
        placeholder="Search the armory: Carcano, K31, Mosin…"
        value={search}
        autoComplete="off"
        onChange={(event) => setSearch(event.target.value)}
      />
      <ul className="model-picker__choices" aria-label="Search results">
        {choices.map((choice) => (
          <li key={choice.id}>
            <button
              type="button"
              className="model-picker__choice"
              onClick={() => {
                onChoose(choice);
                setOpen(false);
                setSearch("");
              }}
            >
              {choice.name}
              {choice.country && <span className="muted"> · {choice.country}</span>}
            </button>
          </li>
        ))}
        {choices.length === 0 && <li className="muted">No model by that name.</li>}
      </ul>
      <p className="field__hint">
        {model === null
          ? "Not matched to a model, so it cannot be valued. Pick the one it is."
          : "Pick the one it is, or leave it to be matched from what it is called."}
      </p>
    </div>
  );
}

function Editor({ row, onClose, onSaved }) {
  const [form, setForm] = useState(row ? formOf(row) : EMPTY);
  //: undefined: left as it is (matched from the title on a new row). null:
  //: deliberately none. Otherwise the {id, name} the owner picked.
  const [model, setModel] = useState(
    row?.firearm_model_id ? { id: row.firearm_model_id, name: row.model } : undefined,
  );
  const [modelTouched, setModelTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = payloadOf(form);
      const saved = row
        ? await api.updateCollectionItem(row.id, {
            ...body,
            ...(modelTouched ? { firearm_model_id: model ? model.id : null } : {}),
          })
        : await api.addToCollection(
            model ? { ...body, firearm_model_id: model.id } : body,
          );
      onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const input = (key, label, props = {}, hint = undefined) => (
    <Field label={label} hint={hint}>
      {(id, describedBy) => (
        <input
          id={id}
          aria-describedby={describedBy}
          className="input"
          value={form[key]}
          onChange={set(key)}
          {...props}
        />
      )}
    </Field>
  );

  return (
    <Modal
      title={row ? `Edit ${row.title}` : "Add a gun"}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn--primary"
            type="submit"
            form="collection-form"
            disabled={busy || !form.title.trim()}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <form id="collection-form" onSubmit={save}>
        {error && <p className="alert alert--error">{error}</p>}
        {input(
          "title",
          "What it is",
          { autoFocus: true, maxLength: 200, placeholder: "Swiss K31, 1943" },
          "Written the way a dealer would title it. The model is matched from this.",
        )}
        <ModelPicker
          model={model === undefined && row ? null : model}
          onChoose={(choice) => {
            setModel(choice);
            setModelTouched(true);
          }}
        />
        <div className="collection-form__row">
          {input("manufacturer", "Maker", { maxLength: 128 })}
          {input("caliber", "Caliber", { maxLength: 64 })}
        </div>
        <Field
          label="Condition"
          hint="Your own grade. The value is compared against guns in the same condition where there are enough."
        >
          {(id, describedBy) => (
            <select
              id={id}
              aria-describedby={describedBy}
              className="select"
              value={form.condition_grade}
              onChange={set("condition_grade")}
            >
              {GRADES.map((grade) => (
                <option key={grade.value} value={grade.value}>
                  {grade.label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <div className="collection-form__row">
          {input("paid", "Paid", { inputMode: "decimal", placeholder: "$" })}
          {input("acquired_on", "When", { type: "date" })}
        </div>
        {input("acquired_from", "Where from", { maxLength: 128 })}
        <Field
          label="Notes"
          hint="Anything you want to keep with it. There is deliberately no serial number field."
        >
          {(id, describedBy) => (
            <textarea
              id={id}
              aria-describedby={describedBy}
              className="input"
              rows={3}
              maxLength={4000}
              value={form.notes}
              onChange={set("notes")}
            />
          )}
        </Field>
      </form>
    </Modal>
  );
}

/** One list of comparables: the listings, cheapest or latest first. */
function ComparableList({ rows, departed, limit }) {
  if (!rows.length) {
    return (
      <p className="muted">
        {departed ? "None have left the shelf yet." : "None are for sale right now."}
      </p>
    );
  }
  return (
    <div className="table-wrap">
      <table className="table comparables-table">
        <thead>
          <tr>
            <th>Listing</th>
            <th>Shop</th>
            <th>Condition</th>
            <th>{departed ? "Last asked" : "Asking"}</th>
            {departed && <th>Left</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.item_id}>
              <td>
                <Link to={`/items/${row.item_id}`}>{row.title}</Link>
              </td>
              <td>{row.site_name || "—"}</td>
              <td>{row.condition_grade_label || "—"}</td>
              <td>{row.price != null ? formatMoney(row.price, row.currency) : "—"}</td>
              {departed && (
                <td>
                  {row.left_at ? formatDate(row.left_at) : "—"}
                  <div className="muted collection-sub">
                    {row.marked_sold ? "marked sold" : "taken down"}
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length >= limit && (
        <p className="muted collection-sub">
          Showing the first {limit}; the value is worked out from all of them.
        </p>
      )}
    </div>
  );
}

/**
 * The listings a gun's value was worked out from.
 *
 * Chosen by the server with the value's own rules -- the same model, and the
 * same condition when the value was narrowed to it -- so what is listed here
 * is what the number came from, not a second opinion. Both lists are shown,
 * with the one that set the number said to have done so.
 */
function Comparables({ row, onClose }) {
  const [found, setFound] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    api
      .collectionComparables(row.id)
      .then((answer) => live && setFound(answer))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, [row.id]);

  const basis = found?.valuation?.basis;
  const band = (value) =>
    value
      ? `${value.listings} listings, typically ${formatMoney(value.median)} (${formatMoney(
          value.low,
        )}–${formatMoney(value.high)})`
      : null;

  return (
    <Modal
      title={`Comparables for ${row.title}`}
      onClose={onClose}
      wide
      footer={
        <button className="btn btn--secondary" onClick={onClose}>
          Close
        </button>
      }
    >
      {error && <p className="alert alert--error">{error}</p>}
      {!found && !error && <p className="muted">Loading…</p>}
      {found && (
        <div className="comparables" data-testid="comparables">
          <p>
            {found.model ? (
              <>
                Compared with <strong>{found.model}</strong> listings
                {found.grade_label ? (
                  <>
                    {" "}
                    in <strong>{found.grade_label.toLowerCase()}</strong> condition, like
                    yours
                  </>
                ) : (
                  " in any condition"
                )}
                .
              </>
            ) : (
              "Not matched to a model, so there is nothing to compare it with."
            )}
            {found.valuation && (
              <>
                {" "}
                Worth about <strong>{formatMoney(found.valuation.estimate)}</strong>.
              </>
            )}
          </p>

          <h3 className="comparables__heading">
            Left the shelf
            {basis === "left" && <span className="chip chip--info">sets the value</span>}
          </h3>
          {found.valuation?.departed && (
            <p className="muted collection-sub">{band(found.valuation.departed)}</p>
          )}
          <ComparableList rows={found.departed} departed limit={found.limit} />
          {found.departed.length > 0 && (
            <Link className="collection-sub" to={comparablesSearch(row, true)}>
              Open these in the inventory
            </Link>
          )}

          <h3 className="comparables__heading">
            On the shelf now
            {basis === "shelf" && <span className="chip chip--info">sets the value</span>}
          </h3>
          {found.valuation?.shelf && (
            <p className="muted collection-sub">{band(found.valuation.shelf)}</p>
          )}
          <ComparableList rows={found.shelf} limit={found.limit} />
          {found.shelf.length > 0 && (
            <Link className="collection-sub" to={comparablesSearch(row, false)}>
              Open these in the inventory
            </Link>
          )}
        </div>
      )}
    </Modal>
  );
}

/**
 * The collection's worth at each weekly snapshot, as a line.
 *
 * Drawn by hand in SVG rather than with a charting library: one line, two
 * labels, and a bundle that does not grow for it. One point is not a line, so
 * a first snapshot is said in words until the second arrives.
 */
function WorthChart({ history }) {
  if (!history?.length) return null;
  if (history.length === 1) {
    const [only] = history;
    return (
      <p className="muted worth-note" data-testid="worth-chart">
        Worth about {formatMoney(only.value)} on {formatDate(only.day)}. A line appears
        here once a second weekly snapshot is recorded.
      </p>
    );
  }
  const width = 600;
  const height = 120;
  const pad = 8;
  const values = history.map((point) => point.value);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const x = (index) => pad + (index * (width - pad * 2)) / (history.length - 1);
  const y = (value) => height - pad - ((value - low) / span) * (height - pad * 2);
  const points = history.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const first = history[0];
  const last = history[history.length - 1];
  return (
    <figure className="worth-chart" data-testid="worth-chart">
      <figcaption>
        Worth, week by week: {formatMoney(first.value)} on {formatDate(first.day)} to{" "}
        <strong>{formatMoney(last.value)}</strong> on {formatDate(last.day)}
      </figcaption>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Collection worth from ${formatMoney(first.value)} to ${formatMoney(last.value)}`}
      >
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2.5" />
        {history.map((point, index) => (
          <circle
            key={point.day}
            cx={x(index)}
            cy={y(point.value)}
            r="3.5"
            fill="currentColor"
          >
            <title>
              {formatDate(point.day)}: {formatMoney(point.value)} ({point.guns} valued)
            </title>
          </circle>
        ))}
      </svg>
    </figure>
  );
}

/** One gun's matches of one kind, as a short list of links. */
function FitList({ title, items, total }) {
  if (!items.length) return null;
  return (
    <div className="fits__group">
      <h4>
        {title} <span className="muted">({total})</span>
      </h4>
      <ul>
        {items.map((item) => (
          <li key={item.id}>
            <Link to={`/items/${item.id}`}>{item.title}</Link>{" "}
            <span className="muted">
              {item.current_price != null ? formatMoney(item.current_price) : "No price"}{" "}
              · {item.site_name}
            </span>
          </li>
        ))}
      </ul>
      {total > items.length && (
        <p className="muted collection-sub">
          Showing {items.length} of {total}, newest first.
        </p>
      )}
    </div>
  );
}

/**
 * What is for sale that fits the guns in the collection.
 *
 * Ammunition and clips by caliber, and accessories and parts that name the
 * gun's model -- matched with the armory's own spellings and precedence, so
 * a Mosin bayonet is not offered to the owner of a Carcano. See
 * services/foryourguns.py.
 */
function ForYourGuns() {
  const [fits, setFits] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    api
      .forYourGuns()
      .then((rows) => live && setFits(rows))
      .catch((err) => live && setError(err.message));
    return () => {
      live = false;
    };
  }, []);

  if (error) return <p className="alert alert--error">{error}</p>;
  if (!fits) return <p className="muted">Loading…</p>;
  if (!fits.length) {
    return <p className="muted">Add a gun and what fits it shows up here.</p>;
  }
  const found = fits.filter((fit) => fit.ammo.length || fit.accessories.length);
  const quiet = fits.filter((fit) => !fit.ammo.length && !fit.accessories.length);
  return (
    <div className="fits" data-testid="for-your-guns">
      <p className="muted" style={{ marginTop: 0 }}>
        Ammunition and clips in your guns&rsquo; calibers, and parts and accessories that
        name their models, for sale now. New ones are in your digest too.
      </p>
      {found.map((fit) => (
        <div className="panel fits__gun" key={fit.row_id}>
          <div className="panel__head">
            <h3>{fit.title}</h3>
            <span className="muted collection-sub">
              {[fit.model, ...fit.calibers].filter(Boolean).join(" · ")}
            </span>
          </div>
          <div className="panel__body">
            <FitList
              title="Ammunition and clips"
              items={fit.ammo}
              total={fit.ammo_total}
            />
            <FitList
              title="Parts and accessories"
              items={fit.accessories}
              total={fit.accessories_total}
            />
          </div>
        </div>
      ))}
      {quiet.length > 0 && (
        <p className="muted">
          Nothing for sale right now for {quiet.map((fit) => fit.title).join(", ")}.
          {quiet.some((fit) => !fit.model) &&
            " A gun with no model only matches ammunition, by its caliber."}
        </p>
      )}
    </div>
  );
}

const VIEWS = [
  { key: "guns", label: "Your guns", hash: "" },
  { key: "fits", label: "For your guns", hash: "#for-your-guns" },
];

export default function Collection() {
  useTitle("Collection");
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [comparing, setComparing] = useState(null);
  const location = useLocation();
  const navigate = useNavigate();
  //: The fragment is the only copy of the view, as on the armory, so the
  //: digest's "See all" lands on the right one and Back walks between them.
  const view = location.hash === "#for-your-guns" ? "fits" : "guns";

  const load = useCallback(async () => {
    setError(null);
    try {
      setState(await api.collection());
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function remove(row) {
    await api.removeFromCollection(row.id);
    setConfirming(null);
    load();
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h1>Collection</h1>
          <p>
            What you own, what you paid, and what the market says each is worth — valued
            against the same model&rsquo;s listings, and in the same condition where there
            are enough. Use &ldquo;I bought this&rdquo; on a listing to add one from here.
          </p>
        </div>
        <div className="page-head__actions">
          {state?.items?.length > 0 && (
            <a className="btn btn--secondary" href={api.collectionExportUrl()} download>
              <Download size={15} /> Download
            </a>
          )}
          <button className="btn btn--primary" onClick={() => setEditing("new")}>
            <Plus size={15} /> Add a gun
          </button>
        </div>
      </div>

      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      {!state && !error && <p className="muted">Loading…</p>}

      {state && state.items.length > 0 && (
        <div className="armory-tabs" role="tablist" aria-label="Collection view">
          {VIEWS.map((entry) => (
            <button
              key={entry.key}
              type="button"
              role="tab"
              aria-selected={view === entry.key}
              className={`btn ${view === entry.key ? "btn--primary" : "btn--ghost"} btn--sm`}
              onClick={() => navigate(`/collection${entry.hash}`)}
            >
              {entry.label}
            </button>
          ))}
        </div>
      )}

      {state && state.items.length > 0 && view === "fits" && <ForYourGuns />}

      {state && state.items.length === 0 && (
        <div className="empty">
          <Box size={28} />
          <h3>Nothing here yet</h3>
          <p>
            Add a gun you own, or choose &ldquo;I bought this&rdquo; on a{" "}
            <Link to="/">listing</Link> you bought.
          </p>
        </div>
      )}

      {state && state.items.length > 0 && view === "guns" && (
        <>
          <Totals totals={state.totals} />
          <WorthChart history={state.history} />
          <div className="panel">
            <div className="table-wrap">
              <table className="table" data-testid="collection-table">
                <thead>
                  <tr>
                    <th>Gun</th>
                    <th>Condition</th>
                    <th>Acquired</th>
                    <th>Paid</th>
                    <th>Worth about</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {state.items.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => setEditing(row)}
                        >
                          {row.title}
                        </button>
                        <div className="muted collection-sub">
                          {[row.model, row.manufacturer, row.caliber]
                            .filter(Boolean)
                            .join(" · ")}
                        </div>
                      </td>
                      <td>{row.condition_grade_label || "—"}</td>
                      <td>
                        {row.acquired_on ? formatDate(row.acquired_on) : "—"}
                        {row.acquired_from && (
                          <div className="muted collection-sub">{row.acquired_from}</div>
                        )}
                      </td>
                      <td>{row.paid != null ? formatMoney(row.paid) : "—"}</td>
                      <td>
                        {row.valuation ? (
                          <Worth row={row} />
                        ) : (
                          <span className="muted">
                            {row.model
                              ? "Too few listings to say"
                              : "Not matched to a model"}
                          </span>
                        )}
                        {row.model && (
                          <div>
                            <button
                              type="button"
                              className="btn btn--ghost btn--sm comparables__open"
                              onClick={() => setComparing(row)}
                            >
                              Show comparables
                            </button>
                          </div>
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          aria-label={`Remove ${row.title}`}
                          onClick={() => setConfirming(row)}
                        >
                          <Trash size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {editing && (
        <Editor
          row={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}

      {comparing && <Comparables row={comparing} onClose={() => setComparing(null)} />}

      {confirming && (
        <Modal
          title={`Remove ${confirming.title}?`}
          onClose={() => setConfirming(null)}
          footer={
            <>
              <button className="btn btn--secondary" onClick={() => setConfirming(null)}>
                Keep it
              </button>
              <button className="btn btn--danger" onClick={() => remove(confirming)}>
                Remove
              </button>
            </>
          }
        >
          <p>
            It comes off your collection and out of the totals. This cannot be undone.
          </p>
        </Modal>
      )}
    </section>
  );
}
