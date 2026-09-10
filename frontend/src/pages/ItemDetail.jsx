/**
 * One listing: photo gallery, structured facts, description, and price history.
 */
import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api.js";
import { useTitle } from "../hooks.js";
import { formatDateTime, formatMoney, formatRelative, timeTitle } from "../format.js";
import AuthImage from "../components/AuthImage.jsx";

/** "percussion_revolver" as a person would write it.
 *
 * Derived rather than looked up: the armory's own labels come from an
 * admin-only endpoint, and this page is for everybody. */
function kindLabel(kind) {
  if (!kind) return null;
  const words = kind.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
import { ChevronLeft, External, Sparkle, TrendDown, X } from "../components/Icons.jsx";

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
function Fact({ label, children, always = false }) {
  const empty = children === null || children === undefined || children === "";
  if (empty && !always) return null;
  return (
    <div>
      <div className="fact__label">{label}</div>
      <div className={`fact__value ${empty ? "fact__value--unknown" : ""}`}>
        {empty ? "Unknown" : children}
      </div>
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

export default function ItemDetail() {
  const { itemId } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [activePhoto, setActivePhoto] = useState(0);
  const [lightbox, setLightbox] = useState(false);

  useTitle(item?.title);

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
              <AuthImage
                src={current.url}
                alt={item.title}
                onClick={() => setLightbox(true)}
              />
            ) : (
              <div className="item-card__noimg">No photos captured</div>
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
                )}
                {item.model_reference_url && (
                  <>
                    {" "}
                    <a
                      href={item.model_reference_url}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      reference
                    </a>
                  </>
                )}
              </Fact>
            )}
            <Fact label="Manufacturer" always>
              {item.manufacturer}
            </Fact>
            <Fact label="Caliber" always>
              {item.caliber}
            </Fact>
            <Fact label="Country" always>
              {item.country}
            </Fact>
            <Fact label="Bore condition" always>
              {item.condition}
            </Fact>
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
        </div>
      </div>

      {lightbox && current && (
        <div
          className="lightbox"
          onClick={() => setLightbox(false)}
          role="dialog"
          aria-modal="true"
          aria-label={item.title}
        >
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
