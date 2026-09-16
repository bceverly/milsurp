/**
 * The classification rules: countries, caliber designations, and the words
 * that decide whether a listing is a part or a gun.
 *
 * Everything this application knows beyond a vendor's own words is derived,
 * and until now every one of these lists lived in the source. Teaching it that
 * "Ishapore" means India, or that a Mauser ES340 is a .22 trainer, was a code
 * change, a review and a deploy — for a fact about rifles that the person
 * running the site knows and the programmer does not.
 *
 * One page with three tabs rather than three pages, for the reason the Armory
 * is one page: these are three views of one decision, which is "what is this
 * listing?", and an operator who has just corrected a caliber is exactly the
 * person about to correct a country.
 *
 * **Nothing here rewrites the catalog.** A rule change takes effect on the
 * next scan, or on a scoped `reclassify recompute=1`. That is said on the page
 * itself, because the alternative — an edit that silently touches eleven
 * thousand rows — is not something to find out about afterwards.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import Modal from "../components/Modal.jsx";
import Field from "../components/Field.jsx";
import { Plus, Refresh, Trash } from "../components/Icons.jsx";

const TABS = [
  { key: "countries", label: "Countries" },
  { key: "designations", label: "Caliber designations" },
  { key: "keywords", label: "Part or gun" },
];

const EMPTY = {
  countries: { name: "", aliases: "", position: 1000, enabled: true, notes: "" },
  designations: {
    caliber: "",
    spellings: "",
    requires: "",
    whole_word: true,
    position: 1000,
    enabled: true,
    notes: "",
  },
  keywords: {
    kind: "accessory",
    keyword: "",
    match: "word",
    enabled: true,
    notes: "",
  },
};

/** What each tab calls a row, for the dialog titles and the delete warning. */
const NOUN = {
  countries: "country",
  designations: "designation",
  keywords: "word",
};

/**
 * The three lists on the "Part or gun" tab, in the order the classifier reads
 * them. Two vetoes, then the words themselves — and the order is the rule, so
 * it is said on the page rather than left to be inferred from a table sort.
 */
const KEYWORD_KINDS = [
  {
    key: "promotional",
    label: "Sold with a gun",
    blurb:
      "Checked first. A gun thrown in with something is still a gun — “Mosin-Nagant w/ free bayonet” is a rifle.",
  },
  {
    key: "firearm",
    label: "Names a gun",
    blurb:
      "Checked second. A title carrying one of these is a firearm whatever else it mentions.",
  },
  {
    key: "accessory",
    label: "Names a part",
    blurb:
      "Checked last, and only if neither veto fired. These decide that the listing is an accessory.",
  },
];

const KIND_LABEL = Object.fromEntries(
  KEYWORD_KINDS.map((entry) => [entry.key, entry.label]),
);

const MATCH_LABEL = {
  word: "the whole word",
  suffix: "any word ending in it",
  substring: "anywhere in the title",
};

const LOAD = {
  countries: (search) => api.countries(search ? { search } : {}),
  designations: (search) => api.caliberDesignations(search ? { search } : {}),
  keywords: () => api.classifierKeywords(),
};

const CREATE = {
  countries: api.createCountry,
  designations: api.createCaliberDesignation,
  keywords: api.createClassifierKeyword,
};

const UPDATE = {
  countries: api.updateCountry,
  designations: api.updateCaliberDesignation,
  keywords: api.updateClassifierKeyword,
};

const REMOVE = {
  countries: api.deleteCountry,
  designations: api.deleteCaliberDesignation,
  keywords: api.deleteClassifierKeyword,
};

/** The row's own name, for a dialog title or a confirmation. */
function labelOf(tab, row) {
  if (tab === "countries") return row.name;
  if (tab === "designations") return row.caliber;
  return row.keyword;
}

/**
 * A newline-separated list as a readable line.
 *
 * Shown in full rather than truncated at a fixed width: "gew 71 / gew. 71 /
 * gew71 / …" is eighteen spellings for one rule, and a reader deciding whether
 * to add a nineteenth needs to see that they are all already there.
 */
function Spellings({ text }) {
  const parts = (text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!parts.length) return <span style={{ color: "var(--ink-400)" }}>—</span>;
  return (
    <span className="classify-spellings">
      {parts.map((part) => (
        <code key={part}>{part}</code>
      ))}
    </span>
  );
}

function CountryForm({ row, onSubmit, error }) {
  const [form, setForm] = useState({ ...EMPTY.countries, ...(row || {}) });
  const set = (key) => (event) =>
    setForm((current) => ({
      ...current,
      [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value,
    }));

  return (
    <form
      id="classify-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          name: form.name,
          aliases: form.aliases || "",
          position: Number(form.position),
          enabled: form.enabled,
          notes: form.notes || "",
        });
      }}
    >
      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}
      <Field label="Country" hint="Stored on the listing exactly as written here.">
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            value={form.name}
            onChange={set("name")}
            required
            maxLength={128}
          />
        )}
      </Field>
      <Field
        label="Spellings"
        hint="One per line. Matched as whole words, never as patterns. The country's own name is not assumed — if you want listings that say “Finland” to match, put it here."
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={6}
            value={form.aliases || ""}
            onChange={set("aliases")}
          />
        )}
      </Field>
      <PositionField form={form} set={set} />
      <NotesAndSwitch form={form} set={set} />
    </form>
  );
}

function DesignationForm({ row, onSubmit, error }) {
  const [form, setForm] = useState({ ...EMPTY.designations, ...(row || {}) });
  const set = (key) => (event) =>
    setForm((current) => ({
      ...current,
      [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value,
    }));

  return (
    <form
      id="classify-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          caliber: form.caliber,
          spellings: form.spellings,
          requires: form.requires || "",
          whole_word: form.whole_word,
          position: Number(form.position),
          enabled: form.enabled,
          notes: form.notes || "",
        });
      }}
    >
      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}
      <Field
        label="Caliber"
        hint="Written onto the listing as-is, so spell it the way the rest of the catalog does."
      >
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            value={form.caliber}
            onChange={set("caliber")}
            required
            maxLength={64}
          />
        )}
      </Field>
      <Field
        label="Designations"
        hint="One per line; any of them matching is enough. Literal text, never patterns — write “kar 98” and “kar98” as two lines if both should match."
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={5}
            value={form.spellings}
            onChange={set("spellings")}
            required
          />
        )}
      </Field>
      <Field
        label="Only when the listing also says (optional)"
        hint="One per line, any of them. This is how a rule says “Mauser and 8mm in the same listing” — leave it empty and the designations alone decide."
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={3}
            value={form.requires || ""}
            onChange={set("requires")}
          />
        )}
      </Field>
      <label className="checkbox">
        <input type="checkbox" checked={form.whole_word} onChange={set("whole_word")} />
        <span>
          Whole words only
          <span className="field__hint">
            On, “ak” will not match Krakow. Off, “walther pp” also catches a Walther PPK.
          </span>
        </span>
      </label>
      <PositionField
        form={form}
        set={set}
        hint="Rules are tried in this order and the first match wins. It matters here more than anywhere: a rule that only asks for two words in the same listing will match most descriptions, so the precise rules go first."
      />
      <NotesAndSwitch form={form} set={set} />
    </form>
  );
}

function KeywordForm({ row, onSubmit, error }) {
  const [form, setForm] = useState({ ...EMPTY.keywords, ...(row || {}) });
  const set = (key) => (event) =>
    setForm((current) => ({
      ...current,
      [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value,
    }));

  return (
    <form
      id="classify-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          kind: form.kind,
          keyword: form.keyword,
          match: form.match,
          enabled: form.enabled,
          notes: form.notes || "",
        });
      }}
    >
      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}
      <Field
        label="List"
        hint="The two vetoes are checked before the accessory words, and in that order. A word in the wrong list does the opposite of what you meant."
      >
        {(id, describedBy) => (
          <select
            id={id}
            aria-describedby={describedBy}
            className="select"
            value={form.kind}
            onChange={set("kind")}
          >
            {KEYWORD_KINDS.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.label}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field
        label="Word or phrase"
        hint="Stored lowercase; titles are matched lowercase too."
      >
        {(id, describedBy) => (
          <input
            id={id}
            aria-describedby={describedBy}
            className="input"
            value={form.keyword}
            onChange={set("keyword")}
            required
            minLength={2}
            maxLength={64}
          />
        )}
      </Field>
      <Field
        label="How to match it"
        hint="“The whole word” is almost always right: “spring” matched inside Springfield once, and every Springfield in the catalog lost its caliber for it. “Any word ending in it” exists for an optic — telescope, periscope, riflescope. “Anywhere in the title” is what the two veto lists have always done, and why “gun” reaches shotgun."
      >
        {(id, describedBy) => (
          <select
            id={id}
            aria-describedby={describedBy}
            className="select"
            value={form.match}
            onChange={set("match")}
          >
            {Object.entries(MATCH_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        )}
      </Field>
      <NotesAndSwitch form={form} set={set} />
    </form>
  );
}

function PositionField({ form, set, hint }) {
  return (
    <Field
      label="Position"
      hint={
        hint ||
        "Lower numbers are tried first. Leave gaps so a rule can be slipped between two others later."
      }
    >
      {(id, describedBy) => (
        <input
          id={id}
          aria-describedby={describedBy}
          className="input"
          type="number"
          value={form.position}
          onChange={set("position")}
          required
        />
      )}
    </Field>
  );
}

function NotesAndSwitch({ form, set }) {
  return (
    <>
      <Field
        label="Notes (optional)"
        hint="Why this rule exists, or what it broke last time. Nobody reading it later will be the person who wrote it."
      >
        {(id, describedBy) => (
          <textarea
            id={id}
            aria-describedby={describedBy}
            className="input"
            rows={2}
            value={form.notes || ""}
            onChange={set("notes")}
          />
        )}
      </Field>
      <label className="checkbox">
        <input type="checkbox" checked={form.enabled} onChange={set("enabled")} />
        <span>
          Enabled
          <span className="field__hint">
            Turning a rule off stops it matching. Listings it already labeled keep their
            answer until the next scan.
          </span>
        </span>
      </label>
    </>
  );
}

const FORMS = {
  countries: CountryForm,
  designations: DesignationForm,
  keywords: KeywordForm,
};

export default function Classification() {
  useTitle("Classification");
  const [tab, setTab] = useState("countries");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [formError, setFormError] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setRows(null);
    setError(null);
    try {
      setRows(await LOAD[tab](search.trim()));
    } catch (err) {
      setError(err.message);
      setRows([]);
    }
  }, [tab, search]);

  useEffect(() => {
    load();
  }, [load]);

  async function save(payload) {
    setBusy(true);
    setFormError(null);
    try {
      if (editing === "new") await CREATE[tab](payload);
      else await UPDATE[tab](editing.id, payload);
      setEditing(null);
      load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(row) {
    setBusy(true);
    try {
      await REMOVE[tab](row.id);
      setConfirmDelete(null);
      load();
    } catch (err) {
      setError(err.message);
      setConfirmDelete(null);
    } finally {
      setBusy(false);
    }
  }

  /** Flip the enabled switch from the table, without opening the dialog. */
  async function toggle(row) {
    try {
      await UPDATE[tab](row.id, { enabled: !row.enabled });
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  const FormForTab = FORMS[tab];

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Classification</h1>
          <p>
            The rules that turn a vendor&rsquo;s words into a country, a caliber and a
            kind. Edits take effect on the next scan. To reach the listings already
            stored, run <code>make reclassify recompute=1 fields=caliber,country</code> —
            scoped to the fields the change affects, because an unscoped recompute also
            clears makers the vendors supplied. Nothing here rewrites stored listings on
            its own.
          </p>
        </div>
        <div className="page-head__actions">
          <button className="btn btn--secondary" onClick={load}>
            <Refresh size={16} />
            Refresh
          </button>
          <button
            className="btn btn--primary"
            onClick={() => {
              setFormError(null);
              setEditing("new");
            }}
          >
            <Plus size={16} />
            Add {NOUN[tab]}
          </button>
        </div>
      </div>

      <div className="armory-tabs" role="tablist">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            className={`btn ${tab === entry.key ? "btn--primary" : "btn--ghost"} btn--sm`}
            onClick={() => {
              setTab(entry.key);
              setSearch("");
            }}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab !== "keywords" && (
        <label className="field">
          <span className="field__label">Search</span>
          <input
            className="input"
            value={search}
            placeholder={
              tab === "countries" ? "Country or spelling…" : "Caliber or designation…"
            }
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      )}

      {tab === "keywords" && (
        <div className="alert alert--info">
          <p style={{ margin: "0 0 6px" }}>
            Three lists, read in this order. The first one that matches decides, so a word
            in the wrong list does the opposite of what you meant.
          </p>
          <ol className="classify-order">
            {KEYWORD_KINDS.map((entry) => (
              <li key={entry.key}>
                <strong>{entry.label}</strong> — {entry.blurb}
              </li>
            ))}
          </ol>
        </div>
      )}

      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}

      <div className="panel">
        {!rows && (
          <div className="loading-row" style={{ padding: 20 }}>
            <div className="spinner" />
            Loading rules…
          </div>
        )}

        {rows && rows.length === 0 && (
          <p style={{ padding: 20, margin: 0, color: "var(--ink-500)" }}>Nothing here.</p>
        )}

        {rows && rows.length > 0 && (
          <div className="table-wrap">
            <table className="table classify-table">
              <thead>
                {tab === "countries" && (
                  <tr>
                    <th>Order</th>
                    <th>Country</th>
                    <th>Spellings</th>
                    <th>Listings</th>
                    <th>Status</th>
                    <th />
                  </tr>
                )}
                {tab === "designations" && (
                  <tr>
                    <th>Order</th>
                    <th>Caliber</th>
                    <th>Designations</th>
                    <th>Also needs</th>
                    <th>Matches</th>
                    <th>Listings</th>
                    <th>Status</th>
                    <th />
                  </tr>
                )}
                {tab === "keywords" && (
                  <tr>
                    <th>List</th>
                    <th>Word</th>
                    <th>Matches</th>
                    <th>Status</th>
                    <th />
                  </tr>
                )}
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    {tab !== "keywords" && (
                      <td style={{ color: "var(--ink-500)" }}>{row.position}</td>
                    )}
                    {tab === "keywords" && (
                      <td>
                        <span className="chip chip--neutral">{KIND_LABEL[row.kind]}</span>
                      </td>
                    )}
                    <td>
                      <strong>{labelOf(tab, row)}</strong>
                      {row.notes && (
                        <div style={{ fontSize: 12, color: "var(--ink-400)" }}>
                          {row.notes}
                        </div>
                      )}
                    </td>
                    {tab === "countries" && (
                      <td>
                        <Spellings text={row.aliases} />
                      </td>
                    )}
                    {tab === "designations" && (
                      <>
                        <td>
                          <Spellings text={row.spellings} />
                        </td>
                        <td>
                          <Spellings text={row.requires} />
                        </td>
                        <td style={{ color: "var(--ink-500)" }}>
                          {row.whole_word ? "whole words" : "part of a word"}
                        </td>
                      </>
                    )}
                    {tab === "keywords" && (
                      <td style={{ color: "var(--ink-500)" }}>
                        {MATCH_LABEL[row.match]}
                      </td>
                    )}
                    {tab !== "keywords" && (
                      <td
                        style={{ color: "var(--ink-500)" }}
                        title={
                          tab === "designations"
                            ? "Listings carrying this caliber, from any rule"
                            : "Listings filed under this country"
                        }
                      >
                        {row.listing_count.toLocaleString()}
                      </td>
                    )}
                    <td>
                      <button
                        type="button"
                        className={`chip ${row.enabled ? "chip--success" : "chip--neutral"}`}
                        onClick={() => toggle(row)}
                        title={row.enabled ? "Turn this rule off" : "Turn this rule on"}
                      >
                        {row.enabled ? "On" : "Off"}
                      </button>
                    </td>
                    <td className="table__actions">
                      <button
                        className="btn btn--ghost btn--sm"
                        onClick={() => {
                          setFormError(null);
                          setEditing(row);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="btn btn--ghost btn--sm"
                        style={{ color: "var(--red-600)" }}
                        title={`Delete ${NOUN[tab]}`}
                        onClick={() => setConfirmDelete(row)}
                      >
                        <Trash size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && (
        <Modal
          title={editing === "new" ? `Add ${NOUN[tab]}` : `Edit ${labelOf(tab, editing)}`}
          onClose={() => setEditing(null)}
          footer={
            <>
              <button className="btn btn--secondary" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button
                className="btn btn--primary"
                type="submit"
                form="classify-form"
                disabled={busy}
              >
                {busy ? "Saving…" : "Save"}
              </button>
            </>
          }
        >
          <FormForTab
            row={editing === "new" ? null : editing}
            onSubmit={save}
            error={formError}
          />
        </Modal>
      )}

      {confirmDelete && (
        <Modal
          title={`Delete ${NOUN[tab]}`}
          onClose={() => setConfirmDelete(null)}
          footer={
            <>
              <button
                className="btn btn--secondary"
                onClick={() => setConfirmDelete(null)}
              >
                Cancel
              </button>
              <button
                className="btn btn--danger"
                onClick={() => remove(confirmDelete)}
                disabled={busy}
              >
                Delete permanently
              </button>
            </>
          }
        >
          <p style={{ margin: 0 }}>
            Delete <strong>{labelOf(tab, confirmDelete)}</strong>? This removes the rule
            that assigns the answer, not the answer itself — listings already labeled keep
            it until the next scan. If you only want it to stop matching, turn it off
            instead.
          </p>
        </Modal>
      )}
    </div>
  );
}
