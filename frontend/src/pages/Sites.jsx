/**
 * Site administration: at-a-glance status for every vendor, with controls to
 * enable/disable a site, set its scan frequency, and start a scan now.
 *
 * The list polls while any scan is running so progress appears without the
 * admin reloading; polling stops as soon as everything is idle.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useInterval, useTitle } from "../hooks.js";
import {
  formatCountdown,
  formatDuration,
  formatInterval,
  formatRelative,
  parseUtc,
  timeTitle,
} from "../format.js";
import Modal from "../components/Modal.jsx";
import { ScanStatusChip } from "../components/StatusChip.jsx";
import {
  Browser,
  Check,
  History,
  Image as ImageIcon,
  Mail,
  Pause,
  Play,
  Refresh,
  Stop,
  Warning,
  X,
} from "../components/Icons.jsx";

/** Offered cadences. The API floor is 5 minutes; nothing below an hour is
 *  polite to a vendor, so the shortest option here is hourly. The ceiling is
 *  the API's 30 days.
 *
 *  Spelled "Every 2 weeks" rather than "biweekly" on purpose: that word means
 *  both "every two weeks" and "twice a week" and half the readers of a select
 *  box would pick the wrong one. Same reason "Every 2 days" is not "bidaily".
 *
 *  A fortnight is here for the vendors whose scan is genuinely expensive —
 *  Collectors Firearms ask for a 10-second crawl delay and refuse it at 10, so
 *  a first pass over their 691 listings is hours of somebody else's bandwidth
 *  and their stock does not turn over in a day. */
const INTERVALS = [
  { value: 60, label: "Every hour" },
  { value: 180, label: "Every 3 hours" },
  { value: 360, label: "Every 6 hours" },
  { value: 720, label: "Every 12 hours" },
  { value: 1440, label: "Daily" },
  { value: 2880, label: "Every 2 days" },
  { value: 10080, label: "Weekly" },
  { value: 20160, label: "Every 2 weeks" },
];

/**
 * The outcome of a scan the operator just started.
 *
 * Shown until dismissed or until it ages out, so the answer to "did that
 * work?" does not disappear the instant the status chip flips back.
 */
function ScanResult({ result, onDismiss }) {
  const failed = result.status === "failed" || result.status === "canceled";
  const partial = result.status === "partial";
  const tone = failed ? "error" : partial ? "info" : "success";

  return (
    <div className={`site-card__result site-card__result--${tone}`} role="status">
      <span className="site-card__result-icon">
        {failed ? <X size={15} /> : partial ? <Warning size={15} /> : <Check size={15} />}
      </span>
      <div className="site-card__result-body">
        <strong>
          {failed
            ? result.status === "canceled"
              ? "Scan canceled"
              : "Scan failed"
            : partial
              ? "Scan finished with warnings"
              : "Scan complete"}
        </strong>
        {failed ? (
          <div className="site-card__result-detail">
            {result.error_message || "No further detail was recorded."}
          </div>
        ) : (
          <div className="site-card__result-detail">
            {result.items_found.toLocaleString()} found · {result.items_new} new ·{" "}
            {result.items_delisted} de-listed · {result.price_changes} price change
            {result.price_changes === 1 ? "" : "s"}
            {partial && result.error_message ? ` — ${result.error_message}` : ""}
          </div>
        )}
      </div>
      <button
        className="site-card__result-close"
        onClick={onDismiss}
        aria-label="Dismiss scan result"
      >
        <X size={14} />
      </button>
    </div>
  );
}

/**
 * Explain a scan time, because the number alone invites the wrong conclusion.
 *
 * A re-scan of Empire Arms is two static pages with every photo already on
 * disk, so it finishes in about two seconds — which reads as "it cannot have
 * done anything" until you see that it checked 58 listings and had no photos
 * left to fetch. Royal Tiger's quarter of an hour is mostly image downloads.
 * The counts are what make the difference legible.
 */
function scanTimeDetail(run) {
  if (!run || run.duration_seconds == null) return undefined;
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const parts = [`${run.duration_seconds.toFixed(1)} seconds end to end`];
  parts.push(`${plural(run.items_found, "listing")} checked`);
  if (run.items_new) parts.push(`${run.items_new} new`);
  parts.push(
    run.images_downloaded
      ? `${plural(run.images_downloaded, "photo")} downloaded`
      : "no photos needed downloading",
  );
  return parts.join(" · ");
}

//: How many product pages one capped "re-read" queues.
//:
//: A round number rather than a measured one, and the reason it exists at all
//: is measured: Legacy Collectibles is 976 listings carrying about a dozen
//: photographs each, so re-reading the site in one go queues five figures of
//: downloads behind it. Two hundred and fifty is a bite somebody can watch
//: finish.
const REFETCH_BATCH = 250;

//: What re-reading a listing an email named found.
const OUTCOME = {
  changed: "new price",
  same: "price unchanged",
  sold: "sold",
  unreadable: "its page publishes no price we can read",
  failed: "could not be re-read",
};

/**
 * Which shops' mail the reader has followed onto their sites, and which it
 * has not heard from yet. A shop "waiting" has sent no newsletter to test
 * against; its links are followed as soon as one arrives, and this list is
 * where to see that it worked.
 */
function ShopLinkStatus({ shops }) {
  if (!shops?.length) return null;
  const followed = shops.filter((shop) => shop.state === "followed");
  const unresolved = shops.filter((shop) => shop.state === "unresolved");
  const waiting = shops.filter((shop) => shop.state === "waiting");
  return (
    <details className="mailing-panel__shops">
      <summary>
        Links followed for {followed.length} shop{followed.length === 1 ? "" : "s"}
        {unresolved.length > 0 && `, ${unresolved.length} to look at`}, {waiting.length}{" "}
        waiting for a first newsletter
      </summary>
      {unresolved.length > 0 && (
        <p>
          <strong>Mail read, but no link reached the shop:</strong>{" "}
          {unresolved.map((shop) => shop.site_name).join(", ")}
        </p>
      )}
      <ul>
        {followed.map((shop) => (
          <li key={shop.site_id}>
            <strong>{shop.site_name}</strong> — {shop.followed} link
            {shop.followed === 1 ? "" : "s"} from {shop.emails} email
            {shop.emails === 1 ? "" : "s"}, via {shop.services.join(", ")}
          </li>
        ))}
      </ul>
      {waiting.length > 0 && (
        <p className="muted">
          Waiting: {waiting.map((shop) => shop.site_name).join(", ")}
        </p>
      )}
    </details>
  );
}

/**
 * The inbox reader: whether the notification account's inbox is checked for
 * the shops' mail, how often, and what the last check found. The account and
 * its password stay in config.yaml; this is only the switch and the result.
 */
function MailingListsPanel({ onChecked }) {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .inbox()
      .then(setState)
      .catch((err) => setError(err.message));
  }, []);

  async function act(call) {
    setBusy(true);
    setError(null);
    try {
      setState(await call());
      onChecked();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!state) return error ? <div className="alert alert--error">{error}</div> : null;
  const { settings } = state;
  const outcome = {
    ok: `Looked at ${settings.last_looked_at ?? 0} message(s); ${settings.last_recorded ?? 0} new from the shops.`,
    not_configured: "There is no email account in config.yaml to sign in with.",
    failed: `The check failed: ${settings.last_error || "no reason given"}.`,
  }[settings.last_status];

  return (
    <section className="panel mailing-panel" aria-labelledby="mailing-heading">
      <div className="panel__head">
        <h2 id="mailing-heading">Vendor mailing lists</h2>
        <button
          className="btn btn--ghost"
          type="button"
          disabled={busy}
          onClick={() => act(api.checkInbox)}
        >
          <Mail size={15} /> Check the inbox now
        </button>
      </div>
      <div className="panel__body">
        <label className="switch">
          <input
            type="checkbox"
            checked={settings.enabled}
            disabled={busy}
            onChange={(event) =>
              act(() => api.updateInbox({ enabled: event.target.checked }))
            }
          />
          <span className="switch__track" />
          <span>
            Check {state.account || "the notification account"} for the shops&apos; mail
          </span>
        </label>
        <label className="field mailing-panel__field">
          <span className="field__label">Every</span>
          <select
            value={settings.interval_hours}
            disabled={busy}
            onChange={(event) =>
              act(() => api.updateInbox({ interval_hours: Number(event.target.value) }))
            }
          >
            {state.interval_choices.map((hours) => (
              <option key={hours} value={hours}>
                {hours} hour{hours === 1 ? "" : "s"}
              </option>
            ))}
          </select>
        </label>
        {error && <div className="alert alert--error">{error}</div>}
        <p className="muted mailing-panel__status" role="status">
          {settings.last_run_at
            ? `Last checked ${formatRelative(settings.last_run_at)}. ${outcome || ""}`
            : "Not checked yet."}{" "}
          Read-only: nothing is marked read, and only mail from the shops is kept.
        </p>
        {state.recent.length > 0 && (
          <ul className="mailing-panel__recent">
            {state.recent.slice(0, 8).map((mail) => (
              <li key={`${mail.received_at}-${mail.subject}`}>
                <span className="muted">{formatRelative(mail.received_at)}</span>{" "}
                <strong>{mail.site_name}</strong> — {mail.subject}
                {mail.asks_to_confirm && (
                  <span className="chip chip--warning">asks you to confirm</span>
                )}
                {mail.links_followed !== null && (
                  <span className="muted">
                    {" "}
                    · {mail.links_followed} link{mail.links_followed === 1 ? "" : "s"}{" "}
                    followed
                  </span>
                )}
                {mail.listings.length > 0 && (
                  <ul className="mailing-panel__listings">
                    {mail.listings.map((listing) => (
                      <li key={listing.item_id}>
                        <Link to={`/items/${listing.item_id}`}>{listing.title}</Link>
                        {listing.outcome && (
                          <span className="muted"> — {OUTCOME[listing.outcome]}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
        <ShopLinkStatus shops={state.shops} />
      </div>
    </section>
  );
}

/**
 * The vendor's mailing-list signup, and whether their mail has reached us.
 *
 * Green once a marketing email from this shop has arrived at the notification
 * account, red until then: the red ones are the lists still to join. The inbox
 * reader that records arrivals is on the roadmap ("Vendor mailing lists"), so
 * until it runs every shop is red, which is true -- nothing has been received.
 */
function MailingListChip({ site, onConfirm }) {
  if (!site.newsletter_url) {
    return (
      <span className="chip chip--neutral" title={site.newsletter_note || undefined}>
        <Mail size={12} />
        No mailing list
      </span>
    );
  }
  // A double opt-in list sends "please confirm" first, and nothing else until
  // somebody clicks it. That is its own state: signed up, not yet receiving.
  const confirming = Boolean(site.confirmation_requested_at);
  // Confirmed by hand, for a list that sends no "you're confirmed" message
  // (Mailchimp's default) and nothing else until its next newsletter.
  const confirmedByHand =
    !site.marketing_email_at && Boolean(site.newsletter_confirmed_at);
  const received = !confirming && (Boolean(site.marketing_email_at) || confirmedByHand);
  const [tone, label, when] = confirming
    ? [
        "chip--warning",
        "Confirm subscription",
        `They asked ${formatRelative(site.confirmation_requested_at)} for the ` +
          "subscription to be confirmed. Open that email in the notification " +
          "account's inbox and follow its link.",
      ]
    : received
      ? [
          "chip--success",
          "Mailing list",
          confirmedByHand
            ? `Marked confirmed ${formatRelative(site.newsletter_confirmed_at)}; ` +
              "no marketing email yet."
            : `Last marketing email ${formatRelative(site.marketing_email_at)}.`,
        ]
      : [
          "chip--danger",
          "Join mailing list",
          "No marketing email received yet. Join the list so the inbox reader hears about sales.",
        ];
  const chip = (
    <a
      className={`chip ${tone}`}
      href={site.newsletter_url}
      target="_blank"
      rel="noopener noreferrer"
      title={[site.newsletter_note, when].filter(Boolean).join(" ")}
    >
      <Mail size={12} />
      {label}
    </a>
  );
  if (!confirming) return chip;
  return (
    <>
      {chip}
      <button
        className="btn btn--ghost btn--sm"
        type="button"
        onClick={onConfirm}
        title="Say the subscription is confirmed, for a list that sends nothing until its next newsletter"
      >
        <Check size={12} /> Mark confirmed
      </button>
    </>
  );
}

function SiteCard({ site, result, onChange, onError, onNotice, onDismissResult }) {
  const [busy, setBusy] = useState(false);
  // Both halves of the queue, because the button fetches both. A photograph
  // that has been given up on is still a photograph this site is missing, and
  // hiding it behind a separate control would leave a site reading "0 waiting"
  // while its listings show no pictures.
  const waitingPhotos = (site.photos_pending || 0) + (site.photos_failed || 0);
  // Listings whose product page has already been read, and which a scan will
  // therefore skip. This is what a fix to how a page is parsed cannot reach.
  const alreadyRead = site.details_fetched || 0;
  const [confirmRefetch, setConfirmRefetch] = useState(false);

  async function patch(body) {
    setBusy(true);
    try {
      const updated = await api.updateSite(site.id, body);
      onChange(updated);
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  /** Lift the pause early, once whatever caused it is known and fixed.
   *
   * Deliberately a separate button rather than a confirmation on "Scan now":
   * the pause exists because the vendor's server refused us, so going back
   * before they asked is a decision about them, not a local preference.
   */
  async function wakeUp() {
    setBusy(true);
    try {
      await api.clearResting(site.id);
      onChange({ ...site, resting_seconds: null, resting_reason: null });
    } catch (err) {
      // onError, not setError: this is the card, and the page owns the alert.
      // The wrong one was a ReferenceError sitting in the one branch nobody
      // exercises — a failed request would have replaced the error message
      // with a crash.
      onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function scanNow() {
    setBusy(true);
    try {
      await api.startScan(site.id);
      onChange({ ...site, is_scanning: true });
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      await api.cancelScan(site.id);
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  /** Fetch the photographs this site has URLs for but no files for.
   *
   * Not a scan. A scan caps how many photographs it downloads so a first pass
   * over a large catalog cannot run for hours, and carries the rest to the
   * next run -- which on a shop that gained eight hundred listings at once is
   * a backlog measured in days. This is that download step by itself.
   */
  async function updatePhotos() {
    setBusy(true);
    try {
      onNotice((await api.updateSitePhotos(site.id)).message);
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  /** Queue this site's product pages to be read again on its next scan.
   *
   * Marks only. Nothing is fetched here, and nothing happens at all until the
   * site is scanned -- which is why the message says so rather than leaving
   * somebody watching for photographs that are not coming yet.
   */
  async function refetchDetails(limit) {
    setBusy(true);
    setConfirmRefetch(false);
    try {
      const marked = await api.refetchDetails(site.id, limit);
      onNotice(marked.message);
      onChange({ ...site, details_fetched: marked.remaining });
    } catch (error) {
      onError(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`panel site-card ${site.is_scanning ? "site-card--scanning" : ""}`}>
      {/* An indeterminate bar: a scan has no meaningful percentage until it
          finishes, so this signals "working" rather than faking progress. */}
      {site.is_scanning && (
        <div
          className="site-card__progress"
          role="progressbar"
          aria-label={`Scanning ${site.name}`}
        >
          <span className="site-card__progress-bar" />
        </div>
      )}

      <div className="site-card__top">
        <div style={{ minWidth: 0 }}>
          <div className="site-card__name">{site.name}</div>
          <a
            className="site-card__url"
            href={site.base_url}
            target="_blank"
            // noreferrer as well as noopener: the vendor does not need to
            // learn that the click came from here, which is the same rule the
            // item page follows for its "View on ..." link.
            rel="noopener noreferrer"
          >
            {site.base_url}
          </a>
          <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
            {/*
              Two independent facts, so two chips. Resting is a property of the
              *host* — it outlives the scan that provoked it — while the status
              chip is what the last scan did. Showing resting instead of the
              status hid the outcome exactly when it mattered: a scan stopped
              by hand looked like a scan that had lost its Stop button.
            */}
            {site.is_scanning ? (
              <span className="chip chip--info">
                <span className="spinner spinner--sm" />
                Scanning…
              </span>
            ) : site.last_run ? (
              <ScanStatusChip status={site.last_run.status} />
            ) : (
              <span className="chip chip--neutral">Never scanned</span>
            )}
            {Boolean(site.resting_seconds) && (
              <span
                className="chip chip--warning"
                title={site.resting_reason || "This host refused our requests"}
              >
                <Pause size={12} />
                Resting {formatCountdown(site.resting_seconds)}
              </span>
            )}
            {/*
              Neutral, not a warning. This states how the site is scraped — it
              is a permanent property of the vendor, not a problem and not a
              diagnosis. Styled as a warning next to a red "Failed" chip, it
              read as the cause of the failure and sent someone off to install
              a browser that was already working.
            */}
            {site.requires_browser && (
              <span
                className="chip chip--neutral"
                title="Scraped with headless Chrome, because this site renders its catalog in JavaScript"
              >
                <Browser size={12} />
                Browser
              </span>
            )}
            {!site.is_available && <span className="chip chip--danger">No scraper</span>}
            <MailingListChip
              site={site}
              onConfirm={() =>
                api
                  .confirmNewsletter(site.id)
                  .then(onChange)
                  .catch((err) => onError(err.message))
              }
            />
          </div>
        </div>

        <label className="switch" title={site.enabled ? "Disable site" : "Enable site"}>
          <input
            type="checkbox"
            checked={site.enabled}
            disabled={busy || !site.is_available}
            onChange={(event) => patch({ enabled: event.target.checked })}
          />
          <span className="switch__track" />
          <span className="visually-hidden">
            {site.enabled ? "Disable" : "Enable"} {site.name}
          </span>
        </label>
      </div>

      <div className="site-card__stats">
        <div className="site-card__stat">
          <div className="site-card__stat-value">
            {site.active_item_count.toLocaleString()}
          </div>
          <div className="site-card__stat-label">Active</div>
        </div>
        <div className="site-card__stat">
          <div className="site-card__stat-value">{site.item_count.toLocaleString()}</div>
          <div className="site-card__stat-label">Total seen</div>
        </div>
        <div className="site-card__stat">
          <div
            className="site-card__stat-value"
            style={{ fontSize: 13, fontWeight: 600 }}
            title={timeTitle(site.last_scan_at)}
          >
            {site.last_scan_at ? formatRelative(site.last_scan_at) : "never"}
          </div>
          <div className="site-card__stat-label">Last scan</div>
        </div>
        <div className="site-card__stat">
          <div
            className="site-card__stat-value"
            style={{ fontSize: 13, fontWeight: 600 }}
            title={scanTimeDetail(site.last_run)}
          >
            {formatDuration(site.last_run?.duration_seconds)}
          </div>
          <div className="site-card__stat-label">Scan time</div>
        </div>
      </div>

      <div className="site-card__controls">
        <label className="visually-hidden" htmlFor={`interval-${site.id}`}>
          Scan frequency for {site.name}
        </label>
        <select
          id={`interval-${site.id}`}
          className="select"
          style={{ width: "auto", flex: "1 1 150px" }}
          value={site.scan_interval_minutes}
          disabled={busy}
          onChange={(event) =>
            patch({ scan_interval_minutes: Number(event.target.value) })
          }
        >
          {/* A cadence set elsewhere (config or CLI) still needs to display. */}
          {!INTERVALS.some((i) => i.value === site.scan_interval_minutes) && (
            <option value={site.scan_interval_minutes}>
              Every {formatInterval(site.scan_interval_minutes)}
            </option>
          )}
          {INTERVALS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        {/*
          Both, always, in the same order — disabled rather than absent when
          they do not apply. They used to swap places, and a control that
          exists only in one state is a control nobody can find in the other:
          Stop vanished the moment a scan ended, which read as a scan that
          could not be stopped, and whatever came next inherited its position
          and its click.
        */}
        <button
          className="btn btn--primary btn--sm"
          onClick={scanNow}
          disabled={
            busy ||
            !site.is_available ||
            site.is_scanning ||
            Boolean(site.resting_seconds)
          }
          title={
            site.is_scanning
              ? "A scan is already running."
              : site.resting_seconds
                ? "This host asked to be left alone. Scanning it now would ignore that."
                : undefined
          }
        >
          <Play size={14} />
          Scan now
        </button>

        <button
          className="btn btn--secondary btn--sm"
          onClick={cancel}
          disabled={busy || !site.is_scanning}
          title={
            site.is_scanning
              ? "Stop this scan at its next checkpoint. Everything already saved is kept."
              : "No scan is running."
          }
        >
          <Stop size={14} />
          Stop
        </button>

        {/*
          Named for the state it ends, not for what it permits. "Fetch anyway"
          read as a third way to start a scan, which left the rest itself
          looking like something with no control at all — the one visible
          countdown on the card and no button admitting to it. Conditional
          because the state is: it ends a pause, and there is usually no pause.
        */}
        {Boolean(site.resting_seconds) && (
          <button
            className="btn btn--secondary btn--sm"
            onClick={wakeUp}
            disabled={busy}
            title="Clear the pause and let scans and photo downloads reach this host again"
          >
            <Pause size={14} />
            Stop resting
          </button>
        )}

        {/*
          Always here, like Scan now and Stop, and carrying its own count so
          it is not a button that might do nothing. The number is the honest
          one: photographs this site has an address for and no file for.
        */}
        <button
          className="btn btn--secondary btn--sm"
          onClick={updatePhotos}
          disabled={busy || waitingPhotos === 0}
          title={
            waitingPhotos === 0
              ? "Every photograph for this site is already stored."
              : `Fetch ${waitingPhotos} photograph(s) already listed for this site. ` +
                "No re-scrape: the addresses are stored, only the pictures are missing."
          }
        >
          <ImageIcon size={14} />
          Update photos{waitingPhotos ? ` (${waitingPhotos})` : ""}
        </button>

        {/*
          A fix to how a product page is *read* reaches only the listings that
          have not been read yet, because a scan skips a product page it has
          already fetched. This is the control that says "those ones too" --
          and the count is the honest one: listings whose page has been read
          and which a scan would otherwise leave alone.
        */}
        <button
          className="btn btn--secondary btn--sm"
          onClick={() => setConfirmRefetch(true)}
          disabled={busy || alreadyRead === 0}
          title={
            alreadyRead === 0
              ? "No listing here has had its product page read yet, so the next scan reads them all anyway."
              : `Queue ${alreadyRead} product page(s) to be read again on the next scan.`
          }
        >
          <Refresh size={14} />
          Re-read details{alreadyRead ? ` (${alreadyRead})` : ""}
        </button>

        <Link className="btn btn--secondary btn--sm" to={`/sites/${site.id}`}>
          <History size={14} />
          History
        </Link>
      </div>

      {confirmRefetch && (
        <Modal
          title="Re-read product pages"
          onClose={() => setConfirmRefetch(false)}
          footer={
            <>
              <button
                className="btn btn--secondary"
                onClick={() => setConfirmRefetch(false)}
              >
                Cancel
              </button>
              {alreadyRead > REFETCH_BATCH && (
                <button
                  className="btn btn--secondary"
                  onClick={() => refetchDetails(REFETCH_BATCH)}
                  disabled={busy}
                >
                  Oldest {REFETCH_BATCH}
                </button>
              )}
              <button
                className="btn btn--primary"
                onClick={() => refetchDetails(undefined)}
                disabled={busy}
              >
                All {alreadyRead}
              </button>
            </>
          }
        >
          <p>
            {alreadyRead} listing{alreadyRead === 1 ? "" : "s"} on {site.name} have had
            their product page read already, so the next scan will skip them. Marking them
            queues those pages to be read again.
          </p>
          <p className="muted">
            Nothing is fetched now — the reading happens on the next scan, and any new
            photographs it finds are downloaded after that. A large site can mean a lot of
            both, which is what “Oldest {REFETCH_BATCH}” is for: it takes the stalest
            first, so pressing it again carries on rather than repeating itself.
          </p>
        </Modal>
      )}

      {result && <ScanResult result={result} onDismiss={onDismissResult} />}

      {Boolean(site.resting_seconds) && (
        <div className="site-card__resting">
          Every scan and photo download is leaving this host alone for another{" "}
          {formatCountdown(site.resting_seconds)}
          {site.resting_reason ? ` — ${site.resting_reason}.` : "."} It refused our
          requests, so nothing will ask it again until then. “Stop resting” lifts it now.
        </div>
      )}

      {site.next_scan_at && site.enabled && !site.is_scanning && (
        <div
          style={{
            padding: "0 16px 13px",
            fontSize: 12,
            color: "var(--ink-500)",
          }}
          title={timeTitle(site.next_scan_at)}
        >
          {/* "Next scan 3 hours ago". formatRelative reads both directions and
              this label only makes sense in one of them. A due time in the past
              is a normal state, not a glitch: the scheduler is off, or the
              database was restored from a machine whose schedule stopped there.
              The honest word for it is overdue. */}
          {parseUtc(site.next_scan_at) < new Date()
            ? `Scan overdue — was due ${formatRelative(site.next_scan_at)}`
            : `Next scan ${formatRelative(site.next_scan_at)}`}
        </div>
      )}
    </div>
  );
}

//: How long a finished scan's result stays on screen before clearing itself.
const RESULT_TIMEOUT_MS = 45_000;

/**
 * A vendor the roadmap intends to read and nothing can scan yet.
 *
 * Deliberately not a disabled SiteCard. There is no row behind it — no id, no
 * history, nothing to enable — and dressing it as one would offer controls
 * that cannot work. What it does carry is the honest part: what is standing
 * between here and there, which is different for every one of them.
 */
function PlannedCard({ site }) {
  return (
    <div className="panel site-card site-card--planned">
      <div className="site-card__top">
        <div style={{ minWidth: 0 }}>
          <div className="site-card__name">{site.name}</div>
          <a
            className="site-card__url"
            href={site.base_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {site.base_url}
          </a>
          <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
            <span className="chip chip--neutral">Coming soon</span>
            <span className="chip chip--neutral">{site.platform}</span>
          </div>
        </div>
      </div>
      <div className="site-card__planned-blocker">{site.blocker}</div>
    </div>
  );
}

export default function Sites() {
  useTitle("Sites");
  const [sites, setSites] = useState(null);
  const [planned, setPlanned] = useState([]);
  const [error, setError] = useState(null);
  // What the photo buttons reported. Separate from `error` because it is not
  // one: the fetching happens off-request, so this line is the only evidence
  // the button did anything at all.
  const [notice, setNotice] = useState("");
  const [photoBusy, setPhotoBusy] = useState(false);
  // siteId -> the ScanRun that just finished, for the outcome banner.
  const [results, setResults] = useState({});
  // Mirrors watchingRef's size into state so a change re-renders and restarts
  // the poll interval; the ref remains the source of truth.
  const [watchCount, setWatchCount] = useState(0);
  // Sites whose scan we are waiting on. An id goes in when a scan is started or
  // observed running, and comes out only once its outcome has been recorded.
  //
  // Deliberately not "what was scanning last poll": a poll already in flight
  // when the operator clicks Scan now lands afterwards and would overwrite that,
  // losing the watch so the outcome banner never appears.
  const watchingRef = useRef(new Set());
  const timersRef = useRef({});

  //: Every photograph any site is missing, whether or not anything would try
  //: for it again on its own. The button fetches both, so it counts both.
  const waitingEverywhere = (sites || []).reduce(
    (total, site) => total + (site.photos_pending || 0) + (site.photos_failed || 0),
    0,
  );

  async function updateAllPhotos() {
    setPhotoBusy(true);
    setError(null);
    try {
      setNotice((await api.updateAllPhotos()).message);
    } catch (err) {
      setError(err.message);
    } finally {
      setPhotoBusy(false);
    }
  }

  const dismissResult = useCallback((siteId) => {
    setResults((current) => {
      if (!(siteId in current)) return current;
      const next = { ...current };
      delete next[siteId];
      return next;
    });
    clearTimeout(timersRef.current[siteId]);
    delete timersRef.current[siteId];
  }, []);

  const load = useCallback(() => {
    api
      .sites()
      .then((next) => {
        setSites(next);

        // Anything currently running is worth watching, however it started —
        // including a scan the scheduler kicked off, or one begun in another tab.
        next.forEach((site) => {
          if (site.is_scanning) watchingRef.current.add(site.id);
        });

        // A watched site that is no longer scanning has finished, so its
        // last_run is the outcome.
        const finished = next.filter(
          (site) =>
            watchingRef.current.has(site.id) && !site.is_scanning && site.last_run,
        );
        if (finished.length) {
          setResults((current) => {
            const merged = { ...current };
            finished.forEach((site) => {
              merged[site.id] = site.last_run;
            });
            return merged;
          });
          finished.forEach((site) => {
            watchingRef.current.delete(site.id);
            clearTimeout(timersRef.current[site.id]);
            timersRef.current[site.id] = setTimeout(
              () => dismissResult(site.id),
              RESULT_TIMEOUT_MS,
            );
          });
        }
        setWatchCount(watchingRef.current.size);
      })
      .catch((err) => setError(err.message));
  }, [dismissResult]);

  useEffect(load, [load]);

  // Once. These come from a registry rather than a table, so there is nothing
  // for the scan poll to pick up and no reason for it to keep asking.
  useEffect(() => {
    api
      .plannedSites()
      .then(setPlanned)
      .catch(() => setPlanned([]));
  }, []);

  // Drop any pending auto-dismiss timers when leaving the page.
  useEffect(() => {
    const timers = timersRef.current;
    return () => Object.values(timers).forEach(clearTimeout);
  }, []);

  // Poll while anything is running *or* still being waited on. Keying only on
  // is_scanning would stop polling at the moment a scan finished — which is
  // exactly the poll that needs to record the outcome.
  const anyScanning = sites?.some((site) => site.is_scanning);
  useInterval(load, anyScanning || watchCount > 0 ? 1500 : null);

  const replace = (updated) =>
    setSites((current) =>
      current.map((site) => (site.id === updated.id ? { ...site, ...updated } : site)),
    );

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Sites</h1>
          <p>
            Enable or disable each vendor, set how often it is scanned, and drill into its
            scan history.
          </p>
        </div>
        <div className="page-head__actions">
          {/*
            The whole backlog at once. Deliberately beside Refresh rather than
            among the per-site controls: it is an action on the list, and a
            copy of it on every card would be twenty-eight ways to start the
            same one job.
          */}
          <button
            className="btn btn--secondary"
            onClick={updateAllPhotos}
            disabled={photoBusy || waitingEverywhere === 0}
            title={
              waitingEverywhere === 0
                ? "Every photograph on every site is already stored."
                : `Fetch ${waitingEverywhere} photograph(s) that are listed but not ` +
                  "stored, across every site. Nothing is re-scraped."
            }
          >
            <ImageIcon size={16} />
            Update photos{waitingEverywhere ? ` (${waitingEverywhere})` : ""}
          </button>
          <button className="btn btn--secondary" onClick={load}>
            <Refresh size={16} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert--error" role="alert">
          {error}
        </div>
      )}

      {/* The photographs arrive in the background, so this is the only thing
          that says the button did anything. Dismissible, because it stays
          true for as long as the fetching runs and nobody wants it pinned to
          the page afterwards. */}
      {notice && (
        <div className="alert alert--info" role="status">
          {notice}
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setNotice("")}
            aria-label="Dismiss"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {!sites && (
        <div className="loading-row">
          <div className="spinner" />
          Loading sites…
        </div>
      )}

      {sites?.length === 0 && (
        <div className="empty">
          <h3>No sites registered</h3>
          <p>Run `make init` to seed the site list from the scraper registry.</p>
        </div>
      )}

      <MailingListsPanel onChecked={load} />

      {sites?.length > 0 && (
        <div className="site-list">
          {sites.map((site) => (
            <SiteCard
              key={site.id}
              site={site}
              result={results[site.id]}
              onChange={(updated) => {
                // Starting a scan clears any previous outcome and registers the
                // site as watched, so the poll that sees it finish can record
                // the result.
                if (updated.is_scanning) {
                  dismissResult(site.id);
                  watchingRef.current.add(site.id);
                  setWatchCount(watchingRef.current.size);
                }
                replace(updated);
              }}
              onError={setError}
              onNotice={setNotice}
              onDismissResult={() => dismissResult(site.id)}
            />
          ))}
        </div>
      )}

      {planned.length > 0 && (
        <>
          <div className="page-head page-head--section">
            <div>
              <h2>Coming soon</h2>
              <p>
                Vendors this project intends to read. Nothing scans them yet, and each one
                says what is standing in the way — a platform nothing here speaks, a
                catalog with no entry URL, or a door that will not open. A vendor measured
                and turned down is not on this list.
              </p>
            </div>
          </div>
          <div className="site-list">
            {planned.map((site) => (
              <PlannedCard key={site.slug} site={site} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
