/**
 * How hot deals are found: the schedule, the thresholds, and "Look again now".
 * An administrator's, on the Site settings page since 2026-10-12 -- it sat at
 * the foot of the Hot deals page until the settings were gathered in one place.
 */
import { useEffect, useState } from "react";
import { formatRelative } from "../format.js";
import { Refresh } from "./Icons.jsx";

/** The administrator's half: how often to look, and what counts as a deal. */
export default function HotDealControls({
  settings,
  choices,
  onChange,
  onRefresh,
  busy,
}) {
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
    {
      // The second signal: a listing linked to one variant whose new price
      // is known, far enough under it. The ceiling above applies to it too.
      key: "min_under_new_percent",
      label: "Or be at least",
      suffix: "% under the price new (same ceiling)",
      min: 5,
      max: 60,
    },
    {
      // Covers watchlist target alerts as well as these emails: one answer to
      // "how long do we stay quiet about a price we already mentioned".
      key: "renotify_after_days",
      label: "Mention an unchanged price again after",
      suffix: " days (0 = never; also applies to watchlist alerts)",
      min: 0,
      max: 365,
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
          Raising it fills the Hot deals page with parts.
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
