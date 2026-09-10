/**
 * Inventory browser: keyword search, faceted filters, and a responsive grid.
 *
 * Filter state lives in the URL query string rather than component state, so a
 * filtered view can be bookmarked, shared, and survives the back button.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useDebounced, useOptimisticSearchParams, useTitle } from "../hooks.js";
import { formatMoney, formatRelative, timeTitle } from "../format.js";
import AuthImage from "../components/AuthImage.jsx";
import {
  Bookmark,
  ChevronLeft,
  ChevronRight,
  Filter as FilterIcon,
  Grid as GridIcon,
  List as ListIcon,
  Search as SearchIcon,
  Sparkle,
  TrendDown,
  X,
} from "../components/Icons.jsx";

/**
 * "Save this search" — a name, and the filters currently in the URL.
 *
 * The query it saves is the URL's, minus paging: `page` and `per_page` say how
 * much is shown at a time, not which listings match, so two searches that
 * differ only in those are one search. The API canonicalizes and validates
 * what arrives here, so this does not have to.
 */
function SaveSearch({ params }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);

  const query = useMemo(() => {
    const next = new URLSearchParams(params);
    for (const drop of ["page", "per_page", "view"]) next.delete(drop);
    return next.toString();
  }, [params]);

  async function save(event) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setState(null);
    try {
      await api.createSavedSearch({ name: name.trim(), query });
      setState({ ok: true, message: `Saved as “${name.trim()}”.` });
      setName("");
      setOpen(false);
    } catch (error) {
      setState({ ok: false, message: error.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="save-search">
      <button
        type="button"
        className="btn btn--secondary"
        onClick={() => {
          setOpen((was) => !was);
          setState(null);
        }}
        aria-expanded={open}
      >
        <Bookmark size={15} /> Save this search
      </button>

      {open && (
        <form className="save-search__form" onSubmit={save}>
          <label className="visually-hidden" htmlFor="save-search-name">
            Name for this search
          </label>
          <input
            id="save-search-name"
            className="input"
            placeholder="Mosins under $400"
            value={name}
            maxLength={80}
            autoFocus
            onChange={(event) => setName(event.target.value)}
          />
          <button
            type="submit"
            className="btn btn--primary"
            disabled={!name.trim() || busy}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </form>
      )}

      {state && (
        <p
          className={state.ok ? "alert alert--success" : "alert alert--error"}
          role="status"
        >
          {state.message}
          {state.ok && (
            <>
              {" "}
              <Link to="/saved-searches">Manage saved searches</Link>
            </>
          )}
        </p>
      )}
    </div>
  );
}

const SORTS = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
  { value: "price_drop", label: "Recently reduced" },
  { value: "title", label: "Title A–Z" },
];

const AVAILABILITY = [
  { value: "available", label: "Available" },
  { value: "sold", label: "Sold" },
  { value: "delisted", label: "De-listed" },
  { value: "all", label: "Everything" },
];

//: One at a time. These read as a single question — "what am I looking for?" —
//: and a set of checkboxes invited the answer "rifles and handguns and parts",
//: which is the same as asking nothing.
const KINDS = [
  { value: "", label: "Anything" },
  { value: "rifle", label: "Rifles" },
  { value: "pistol", label: "Handguns" },
  { value: "bayonet", label: "Bayonets" },
  { value: "parts_kit", label: "Parts kits" },
  //: Its own Type rather than scattered through Rifles and Handguns. A
  //: department trade-in is a different thing to be looking for, and the
  //: vendors sell them as their own named sections, so the catalog can say so.
  { value: "police_surplus", label: "Police surplus" },
  { value: "other", label: "Other parts & accessories" },
];

//: Price reduced sits under Availability because that is the question it
//: answers — what state is this listing in — rather than what kind of thing it
//: is. It is a radio for the same reason the rest of that group is.
const PRICE_STATE = [
  { value: "", label: "Any price" },
  { value: "true", label: "Price reduced" },
];

const PER_PAGE_CHOICES = [24, 48, 96, 192];
const DEFAULT_PER_PAGE = 48;

const VIEWS = [
  { value: "grid", label: "Cards" },
  { value: "list", label: "List" },
];

/** Multi-select facets, keyed by the query parameter the API expects.
 *
 *  Ordered the way somebody narrows a search out loud: the maker, then which
 *  of its models, then the cartridge. Category and country are the coarse ones
 *  and sit at the bottom, where they are a second thought rather than the
 *  first thing in the way.
 */
const FACETS = [
  { param: "manufacturer", facet: "manufacturers", title: "Manufacturer" },
  // Backed by a fact somebody vouched for in the armory, rather than a string
  // a vendor happened to type — which is why it filters by id.
  { param: "model", facet: "models", title: "Model" },
  { param: "caliber", facet: "calibers", title: "Caliber" },
  { param: "site_id", facet: "sites", title: "Site" },
  { param: "category", facet: "categories", title: "Category" },
  { param: "country", facet: "countries", title: "Country" },
];

function FacetGroup({ title, options, selected, onToggle }) {
  const [expanded, setExpanded] = useState(false);
  if (!options?.length) return null;
  // Show the top eight; the long tail is behind "Show all" so the rail stays
  // scannable when a facet has fifty values.
  const visible = expanded ? options : options.slice(0, 8);

  return (
    <details className="facet" open={selected.length > 0}>
      <summary className="facet__summary">
        {title}
        {selected.length > 0 && <span className="facet__count">{selected.length}</span>}
      </summary>
      <div className="facet__options">
        {visible.map((option) => (
          <label className="facet__option" key={option.value}>
            <input
              type="checkbox"
              checked={selected.includes(option.value)}
              onChange={() => onToggle(option.value)}
            />
            <span className="facet__option-label" title={option.label || option.value}>
              {option.label || option.value}
            </span>
            <span className="facet__option-count">{option.count}</span>
          </label>
        ))}
        {options.length > 8 && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Show fewer" : `Show all ${options.length}`}
          </button>
        )}
      </div>
    </details>
  );
}

function ItemCard({ item }) {
  const dropped = item.price_drop > 0;
  // "New" is scoped to the last 72 hours, which is roughly a scan cycle or two
  // across sites and keeps the badge meaningful rather than permanent.
  const isNew =
    item.first_seen_at &&
    Date.now() - new Date(item.first_seen_at).getTime() < 72 * 3600 * 1000;

  return (
    <Link to={`/items/${item.id}`} className="item-card">
      <div className="item-card__media">
        <AuthImage src={item.thumbnail_url} alt={item.title} loading="lazy" />
        <div className="item-card__badges">
          {isNew && (
            <span className="chip chip--info">
              <Sparkle size={12} />
              New
            </span>
          )}
          {dropped && (
            <span className="chip chip--success">
              <TrendDown size={12} />
              Reduced
            </span>
          )}
          {item.is_sold && <span className="chip chip--danger">Sold</span>}
          {!item.is_active && <span className="chip chip--neutral">De-listed</span>}
        </div>
      </div>

      <div className="item-card__body">
        <div className="item-card__title">{item.title}</div>
        <div className="item-card__meta">
          {item.caliber && <span>{item.caliber}</span>}
          {item.country && <span>· {item.country}</span>}
        </div>
        <div className="item-card__foot">
          <span className={`item-card__price ${dropped ? "item-card__price--drop" : ""}`}>
            {formatMoney(item.current_price, item.currency)}
          </span>
          {dropped && (
            <span className="item-card__was">
              {formatMoney(item.previous_price, item.currency)}
            </span>
          )}
        </div>
        <div className="item-card__meta">
          <span title={timeTitle(item.first_seen_at)}>
            {item.site_name} · {formatRelative(item.first_seen_at)}
          </span>
        </div>
      </div>
    </Link>
  );
}

/**
 * One listing as a row, with enough of the description to tell it apart.
 *
 * The card grid answers "what is there?" and this answers "which one is it?".
 * A wall of near-identical Mosin-Nagants is exactly where the photograph stops
 * helping and the first two lines of the dealer's prose start.
 */
function ItemRow({ item }) {
  const dropped = item.price_drop > 0;
  // Already truncated on the server, on a word boundary: a page of 192 of these
  // should not carry 192 full descriptions to render two lines each.
  const blurb = item.blurb;

  return (
    <Link to={`/items/${item.id}`} className="item-row">
      <div className="item-row__media">
        <AuthImage src={item.thumbnail_url} alt={item.title} loading="lazy" />
      </div>

      <div className="item-row__body">
        <div className="item-row__head">
          <span className="item-row__title">{item.title}</span>
          <span className={`item-row__price ${dropped ? "item-row__price--drop" : ""}`}>
            {formatMoney(item.current_price, item.currency)}
            {dropped && (
              <span className="item-row__was">
                {formatMoney(item.previous_price, item.currency)}
              </span>
            )}
          </span>
        </div>

        <div className="item-card__meta">
          {item.caliber && <span>{item.caliber}</span>}
          {item.manufacturer && <span>· {item.manufacturer}</span>}
          {item.country && <span>· {item.country}</span>}
          <span title={timeTitle(item.first_seen_at)}>
            · {item.site_name} · {formatRelative(item.first_seen_at)}
          </span>
        </div>

        {blurb && <p className="item-row__blurb">{blurb}</p>}

        <div className="item-row__badges">
          {dropped && (
            <span className="chip chip--success">
              <TrendDown size={12} />
              Reduced
            </span>
          )}
          {item.is_sold && <span className="chip chip--danger">Sold</span>}
          {!item.is_active && <span className="chip chip--neutral">De-listed</span>}
        </div>
      </div>
    </Link>
  );
}

export default function Browse() {
  useTitle("Inventory");
  const [params, setParams] = useOptimisticSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showFilters, setShowFilters] = useState(false);

  // The search box is local state so typing feels instant; the debounced value
  // is what actually reaches the URL and the API.
  const [searchText, setSearchText] = useState(params.get("search") || "");
  const debouncedSearch = useDebounced(searchText, 350);

  const page = Number(params.get("page") || 1);
  const sort = params.get("sort") || "newest";
  const availability = params.get("availability") || "available";
  const kind = params.get("kind") || "";
  // How many each Type would show. Counted by the API over every other filter
  // but not over the Type itself, so switching between them does not change
  // the numbers -- and so "Anything" is the sum of the ones below it.
  const kindCounts = useMemo(
    () => new Map((data?.facets?.kinds || []).map((k) => [k.value, k.count])),
    [data],
  );
  const priceState = params.get("price_drops_only") === "true" ? "true" : "";
  const perPage = PER_PAGE_CHOICES.includes(Number(params.get("per_page")))
    ? Number(params.get("per_page"))
    : DEFAULT_PER_PAGE;
  const view = params.get("view") === "list" ? "list" : "grid";

  useEffect(() => {
    const current = params.get("search") || "";
    if (debouncedSearch === current) return;
    const next = new URLSearchParams(params);
    if (debouncedSearch) next.set("search", debouncedSearch);
    else next.delete("search");
    next.delete("page");
    setParams(next, { replace: true });
  }, [debouncedSearch, params, setParams]);

  const query = useMemo(() => {
    const built = {
      page,
      per_page: perPage,
      sort,
      availability,
      search: params.get("search") || undefined,
      price_drops_only: priceState === "true",
      kind: kind ? [kind] : [],
    };
    for (const { param } of FACETS) {
      const values = params.getAll(param);
      if (values.length) built[param] = values;
    }
    return built;
  }, [params, page, sort, availability, kind, priceState, perPage]);

  useEffect(() => {
    let canceled = false;
    setLoading(true);
    setError(null);
    api
      .items(query)
      .then((result) => {
        if (!canceled) setData(result);
      })
      .catch((err) => {
        if (!canceled) setError(err.message);
      })
      .finally(() => {
        if (!canceled) setLoading(false);
      });
    return () => {
      canceled = true;
    };
  }, [query]);

  // For FILTER changes only. Narrowing the result set renumbers the pages, so
  // whatever page you were on no longer means anything and is dropped.
  const update = useCallback(
    (mutate) => {
      const next = new URLSearchParams(params);
      mutate(next);
      next.delete("page");
      setParams(next);
    },
    [params, setParams],
  );

  // Paging is the one change that must NOT clear the page, so it cannot go
  // through update(). Routing the pager through it set page=2 and then deleted
  // it on the very next line, which is why Next never advanced.
  const goToPage = useCallback(
    (target) => {
      const next = new URLSearchParams(params);
      // Page 1 is the default; keeping it out of the URL keeps links tidy and
      // makes "no page param" and "page=1" the same place.
      if (target <= 1) next.delete("page");
      else next.set("page", String(target));
      setParams(next);

      // You click Next from the bottom of the grid, so without this the new
      // page arrives already scrolled past its own first rows. Instant rather
      // than smooth: the content underneath is being replaced as it animates,
      // and a long page makes the scroll itself a wait.
      window.scrollTo({ top: 0 });
    },
    [params, setParams],
  );

  const toggleMulti = useCallback(
    (param, value) => {
      update((next) => {
        const existing = next.getAll(param);
        next.delete(param);
        const kept = existing.includes(value)
          ? existing.filter((entry) => entry !== value)
          : [...existing, value];
        kept.forEach((entry) => next.append(param, entry));
      });
    },
    [update],
  );

  const activeChips = useMemo(() => {
    const chips = [];
    for (const { param, facet, title } of FACETS) {
      for (const value of params.getAll(param)) {
        const match = data?.facets?.[facet]?.find((o) => o.value === value);
        chips.push({
          key: `${param}:${value}`,
          label: `${title}: ${match?.label || value}`,
          clear: () => toggleMulti(param, value),
        });
      }
    }
    if (kind) {
      chips.push({
        key: `kind:${kind}`,
        label: KINDS.find((k) => k.value === kind)?.label || kind,
        clear: () => update((next) => next.delete("kind")),
      });
    }
    if (params.get("price_drops_only") === "true") {
      chips.push({
        key: "drops",
        label: "Price reduced",
        clear: () => update((next) => next.delete("price_drops_only")),
      });
    }
    return chips;
  }, [params, data, toggleMulti, update]);

  const clearAll = () => {
    setSearchText("");
    setParams(new URLSearchParams());
  };

  const totalPages = data?.pages || 1;

  return (
    <div className="browse">
      <div className="page-head">
        <div>
          <h1>Inventory</h1>
          <p>
            {loading && !data
              ? "Loading listings…"
              : `${(data?.total ?? 0).toLocaleString()} listing${
                  data?.total === 1 ? "" : "s"
                } match your filters`}
          </p>
        </div>
      </div>

      <div className="browse__toolbar">
        <div className="search">
          <SearchIcon size={17} className="search__icon" />
          <input
            className="input"
            type="search"
            placeholder="Search titles and descriptions…"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            aria-label="Search listings"
          />
          {searchText && (
            <button
              className="search__clear"
              onClick={() => setSearchText("")}
              aria-label="Clear search"
            >
              <X size={15} />
            </button>
          )}
        </div>

        <select
          className="select"
          style={{ width: "auto", flex: "0 0 auto" }}
          value={sort}
          onChange={(event) => update((next) => next.set("sort", event.target.value))}
          aria-label="Sort listings"
        >
          {SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <select
          className="select"
          style={{ width: "auto", flex: "0 0 auto" }}
          value={perPage}
          onChange={(event) =>
            update((next) => {
              const chosen = Number(event.target.value);
              if (chosen === DEFAULT_PER_PAGE) next.delete("per_page");
              else next.set("per_page", String(chosen));
            })
          }
          aria-label="Listings per page"
        >
          {PER_PAGE_CHOICES.map((size) => (
            <option key={size} value={size}>
              {size} per page
            </option>
          ))}
        </select>

        <SaveSearch params={params} />

        <div className="view-switch" role="group" aria-label="Layout">
          {VIEWS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`view-switch__button ${
                view === option.value ? "view-switch__button--on" : ""
              }`}
              aria-pressed={view === option.value}
              onClick={() =>
                update((next) => {
                  if (option.value === "grid") next.delete("view");
                  else next.set("view", option.value);
                })
              }
            >
              {option.value === "grid" ? <GridIcon size={16} /> : <ListIcon size={16} />}
              <span className="view-switch__label">{option.label}</span>
            </button>
          ))}
        </div>

        <button
          className="btn btn--secondary filters__toggle"
          onClick={() => setShowFilters((value) => !value)}
          aria-expanded={showFilters}
        >
          <FilterIcon size={17} />
          Filters
          {activeChips.length > 0 && (
            <span className="chip chip--info">{activeChips.length}</span>
          )}
        </button>
      </div>

      {activeChips.length > 0 && (
        <div className="active-filters">
          {activeChips.map((chip) => (
            <span className="active-filters__chip" key={chip.key}>
              {chip.label}
              <button onClick={chip.clear} aria-label={`Remove ${chip.label}`}>
                <X size={13} />
              </button>
            </span>
          ))}
          <button className="btn btn--ghost btn--sm" onClick={clearAll}>
            Clear all
          </button>
        </div>
      )}

      <div className="browse__layout">
        <aside className="filters" hidden={!showFilters}>
          <details className="facet" open>
            <summary className="facet__summary">Availability</summary>
            <div className="facet__options">
              {AVAILABILITY.map((option) => (
                <label className="facet__option" key={option.value}>
                  <input
                    type="radio"
                    name="availability"
                    checked={availability === option.value}
                    onChange={() =>
                      update((next) => next.set("availability", option.value))
                    }
                  />
                  <span className="facet__option-label">{option.label}</span>
                </label>
              ))}
              <hr className="facet__rule" />
              {PRICE_STATE.map((option) => (
                <label className="facet__option" key={option.value || "any"}>
                  <input
                    type="radio"
                    name="price_state"
                    checked={priceState === option.value}
                    onChange={() =>
                      update((next) => {
                        if (option.value) next.set("price_drops_only", "true");
                        else next.delete("price_drops_only");
                      })
                    }
                  />
                  <span className="facet__option-label">{option.label}</span>
                </label>
              ))}
            </div>
          </details>

          <details className="facet" open>
            <summary className="facet__summary">Type</summary>
            <div className="facet__options">
              {KINDS.map((option) => (
                <label className="facet__option" key={option.value || "any"}>
                  <input
                    type="radio"
                    name="kind"
                    checked={kind === option.value}
                    onChange={() =>
                      update((next) => {
                        if (option.value) next.set("kind", option.value);
                        else next.delete("kind");
                      })
                    }
                  />
                  <span className="facet__option-label">{option.label}</span>
                  {kindCounts.has(option.value) && (
                    <span className="facet__option-count">
                      {kindCounts.get(option.value).toLocaleString()}
                    </span>
                  )}
                </label>
              ))}
            </div>
          </details>

          {FACETS.map(({ param, facet, title }) => (
            <FacetGroup
              key={param}
              title={title}
              options={data?.facets?.[facet]}
              selected={params.getAll(param)}
              onToggle={(value) => toggleMulti(param, value)}
            />
          ))}
        </aside>

        <div>
          {error && (
            <div className="alert alert--error" role="alert">
              {error}
            </div>
          )}

          {loading && (
            <div className="loading-row">
              <div className="spinner" />
              Loading listings…
            </div>
          )}

          {!loading && data?.items?.length === 0 && (
            <div className="empty">
              <h3>No listings match</h3>
              <p>
                Try a broader search, or clear some filters. If the database is empty, an
                administrator needs to run a scan first.
              </p>
              {activeChips.length > 0 && (
                <button className="btn btn--secondary" onClick={clearAll}>
                  Clear all filters
                </button>
              )}
            </div>
          )}

          {data?.items?.length > 0 &&
            (view === "list" ? (
              <div className="item-rows">
                {data.items.map((item) => (
                  <ItemRow item={item} key={item.id} />
                ))}
              </div>
            ) : (
              <div className="grid">
                {data.items.map((item) => (
                  <ItemCard item={item} key={item.id} />
                ))}
              </div>
            ))}

          {totalPages > 1 && (
            <div className="pagination">
              <button
                className="btn btn--secondary btn--sm"
                disabled={page <= 1}
                onClick={() => goToPage(page - 1)}
              >
                <ChevronLeft size={16} />
                Previous
              </button>
              <span className="pagination__status">
                Page {page} of {totalPages}
              </span>
              <button
                className="btn btn--secondary btn--sm"
                disabled={page >= totalPages}
                onClick={() => goToPage(page + 1)}
              >
                Next
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
