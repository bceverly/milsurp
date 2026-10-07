/**
 * Application shell: header, navigation and the routed content area.
 *
 * Responsive by structure rather than by duplication — the same nav markup is
 * a fixed sidebar on desktop and a slide-in drawer on phones, driven entirely
 * by CSS. Only the drawer's open/closed state lives in JavaScript.
 */
import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { setReachabilityHandler } from "../api.js";
import { useAuth } from "../auth.jsx";
import {
  Bookmark,
  Cart,
  ChevronDown,
  Box as BoxIcon,
  Flame,
  Logout,
  Mail,
  Menu,
  Rifle,
  Shield,
  Sieve,
  Sparkle,
  TrendDown,
  Sites as SitesIcon,
  Store as StoreIcon,
  Star,
  Tag as TagIcon,
  Database as DatabaseIcon,
  History as HistoryIcon,
  Users as UsersIcon,
  Warning,
  X,
} from "./Icons.jsx";
import Insignia from "./Insignia.jsx";
import PageLoading from "./PageLoading.jsx";

/**
 * The rail, in four sections, in the order somebody uses them.
 *
 * It had grown to fourteen entries in one list, in the order they were built:
 * personal settings sat below six admin pages, and "Email digest" was the
 * last thing a reader saw after Backups. Grouped now by whose it is --
 * the catalog everybody reads, the things you asked for, your account, and the
 * administration -- with each group ordered by how often it is opened.
 */
const NAV = [
  {
    heading: "Catalog",
    entries: [
      { to: "/", label: "Inventory", icon: Rifle, end: true },
      // Directly under Inventory: it is the thing somebody opens first after
      // being away. The digest says what you asked for; this says what
      // happened.
      { to: "/changes", label: "What changed", icon: TrendDown },
      // Then what the catalog worked out while you were away, before the
      // reference page it is worked out from.
      { to: "/hot-deals", label: "Hot deals", icon: Flame },
      // Last in the group: a reference, what things are worth in general,
      // rather than news.
      { to: "/market", label: "Market", icon: Sparkle },
      // After the Market, and for the same kind of question one level down:
      // not what a gun costs, but how each dealer prices, stocks and sells.
      { to: "/shops", label: "Shops", icon: StoreIcon },
    ],
  },
  {
    // The things you asked for, from widest to narrowest: a standing question
    // about the catalog, a standing question about particular guns, the guns
    // you mean to buy, and the guns that are already yours.
    heading: "Yours",
    entries: [
      { to: "/saved-searches", label: "Saved searches", icon: Bookmark },
      { to: "/watchlist", label: "Watchlist", icon: Star },
      { to: "/wishlist", label: "Wishlist", icon: Cart },
      { to: "/collection", label: "Collection", icon: BoxIcon },
    ],
  },
  {
    heading: "Account",
    entries: [
      { to: "/settings", label: "Email digest", icon: Mail },
      // Its own entry. The password panel lived under "Email digest" since it
      // was written, and putting two-factor there too made that worse: nobody
      // looking for either clicks Email digest.
      { to: "/security", label: "Security settings", icon: Shield },
    ],
  },
  {
    heading: "Administration",
    adminOnly: true,
    entries: [
      { to: "/sites", label: "Sites", icon: SitesIcon },
      // One entry, not two. Makers, models and calibers are three views of
      // one body of knowledge, and having "Makers" beside "Armory" invited
      // exactly the split it took a rewrite to remove.
      { to: "/armory", label: "Armory", icon: TagIcon },
      // Directly after the Armory: the Armory is what the catalog is allowed
      // to say, and this is the rules that decide what any one listing says.
      { to: "/classification", label: "Classification", icon: Sieve },
      // People, then what people did, then the safety net.
      { to: "/users", label: "Users", icon: UsersIcon },
      { to: "/audit", label: "Audit log", icon: HistoryIcon },
      { to: "/backups", label: "Backups", icon: DatabaseIcon },
    ],
  },
];

/** The section a path belongs to, so the page you are on is never hidden. */
function sectionOf(sections, pathname) {
  const owns = ({ to, end }) =>
    end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
  return sections.find(({ entries }) => entries.some(owns))?.heading;
}

export default function Shell() {
  const { user, isAdmin, signOut } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // **Coming back from a forced sign-out, without landing on the same wreck.**
  //
  // Being thrown out is usually the site's fault rather than the reader's, so
  // signing back in returns them to the page they were on. But if that page is
  // *why* they were thrown out -- it asked for more than the server could give
  // and the proxy answered with a 504 -- sending them straight back to it
  // hands them the same dead screen and no way to tell what went wrong.
  //
  // So the restored page is watched until it either loads or does not. The
  // first answer wins: anything that comes back disarms this, and a gateway
  // status or a dead connection takes them to the inventory with a note
  // naming the address that would not open. The note travels in the location
  // rather than in state here, so it survives the navigation that carries it.
  const restoring = location.state?.restoring;
  useEffect(() => {
    if (!restoring) return undefined;
    setReachabilityHandler((reachable) => {
      setReachabilityHandler(null);
      if (reachable) {
        // It loaded. Drop the marker so a later bad minute on this same page
        // -- or a plain browser reload of it -- is not treated as this.
        navigate(location.pathname + location.search, { replace: true, state: null });
      } else {
        navigate("/", { replace: true, state: { restoreFailed: restoring } });
      }
    });
    return () => setReachabilityHandler(null);
  }, [restoring, navigate, location.pathname, location.search]);

  const restoreFailed = location.state?.restoreFailed;

  // Any navigation closes the drawer; otherwise it stays over the new page.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  // Escape closes the drawer, matching the expectation for any overlay.
  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const sections = NAV.filter((section) => !section.adminOnly || isAdmin);

  // **Each section folds**, and a reader starts with the catalog open and the
  // rest closed: the catalog is what nearly every visit is for, and the four
  // groups open at once are taller than a laptop's screen. Held here rather
  // than in storage, so signing in again starts from the catalog -- the shell
  // is gone while signed out -- while moving between pages keeps whatever was
  // opened. And the section of the page on screen always opens, so a link
  // into the armory never lands on a rail with its own entry hidden.
  const [openSections, setOpenSections] = useState(() => new Set(["Catalog"]));
  const current = sectionOf(sections, location.pathname);
  useEffect(() => {
    if (current)
      setOpenSections((was) => (was.has(current) ? was : new Set([...was, current])));
  }, [current]);
  const toggle = (heading) =>
    setOpenSections((was) => {
      const next = new Set(was);
      if (next.has(heading)) next.delete(heading);
      else next.add(heading);
      return next;
    });

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="topbar">
        <button
          className="topbar__menu"
          onClick={() => setDrawerOpen((open) => !open)}
          aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={drawerOpen}
        >
          {drawerOpen ? <Menu size={22} /> : <Menu size={22} />}
        </button>

        <NavLink to="/" className="topbar__brand">
          <Insignia size={30} />
          <span className="topbar__title">Milsurp Monitor</span>
        </NavLink>

        <div className="topbar__spacer" />

        <div className="topbar__user">
          <span className="topbar__username">{user?.username}</span>
          {isAdmin && <span className="chip chip--info">Admin</span>}
        </div>
        <button className="topbar__signout" onClick={signOut} aria-label="Sign out">
          <Logout size={19} />
        </button>
      </header>

      {drawerOpen && (
        <button
          className="scrim"
          onClick={() => setDrawerOpen(false)}
          aria-label="Close navigation"
          tabIndex={-1}
        />
      )}

      <nav
        className={`rail ${drawerOpen ? "rail--open" : ""}`}
        aria-label="Main navigation"
      >
        <div className="rail__head">
          <span>Menu</span>
          <button
            className="btn btn--ghost btn--sm rail__close"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close navigation"
          >
            <X size={17} />
          </button>
        </div>

        <div className="rail__list">
          {sections.map(({ heading, entries }) => (
            // A label and a list rather than a heading: the page's own headings
            // are what a screen reader's outline should offer, not the rail's.
            <div className="rail__section" key={heading}>
              <button
                type="button"
                className={`rail__heading rail__toggle ${openSections.has(heading) ? "rail__toggle--open" : ""}`}
                id={`rail-${heading}`}
                aria-expanded={openSections.has(heading)}
                aria-controls={`rail-list-${heading}`}
                onClick={() => toggle(heading)}
              >
                <span>{heading}</span>
                <ChevronDown size={14} />
              </button>
              <ul
                id={`rail-list-${heading}`}
                aria-labelledby={`rail-${heading}`}
                hidden={!openSections.has(heading)}
              >
                {entries.map(({ to, label, icon: Icon, end }) => (
                  <li key={to}>
                    <NavLink
                      to={to}
                      end={end}
                      className={({ isActive }) =>
                        `rail__link ${isActive ? "rail__link--active" : ""}`
                      }
                    >
                      <Icon size={19} />
                      <span>{label}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="rail__foot">
          <button className="btn btn--secondary btn--block btn--sm" onClick={signOut}>
            <Logout size={16} />
            Sign out
          </button>
        </div>
      </nav>

      <main className="content" id="main">
        {restoreFailed && (
          <div className="alert alert--warning" role="status">
            <Warning size={16} /> You were signed back in, but{" "}
            <code>{restoreFailed}</code> would not load — the server did not answer in
            time. This is the inventory instead; try that page again in a minute.
          </div>
        )}
        {/* Pages other than the inventory are fetched when first opened (see
            App.jsx). Here rather than around the routes, so the navigation
            stays on screen while one arrives. */}
        <Suspense fallback={<PageLoading />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
