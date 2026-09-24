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

const NAV = [
  { to: "/", label: "Inventory", icon: Rifle, end: true },
  // Directly under Inventory, because a saved search *is* the inventory with
  // filters on it and belongs beside the page it came from — not down with
  // the email settings, which is only one of the things it can do.
  // Above the saved searches, because it is the thing somebody opens first
  // after being away: the email digest says what you asked for, this says what
  // happened.
  { to: "/changes", label: "What changed", icon: TrendDown },
  // Beside it, because the two are the same instinct at different scales:
  // what moved this week, and what things are worth in general.
  { to: "/market", label: "Market", icon: Sparkle },
  // And directly under the Market, because it is the Market's answer applied
  // to the shelves: that page says what a gun is worth, this one says which
  // listings are well under it. Above the saved searches for the same reason
  // "What changed" is — it is something the catalog worked out while you were
  // away, rather than a question you left behind.
  { to: "/hot-deals", label: "Hot deals", icon: Flame },
  { to: "/saved-searches", label: "Saved searches", icon: Bookmark },
  // Beside saved searches, and after it: a saved search is a standing question
  // about the catalog, a watchlist a standing question about particular guns.
  // Both are "things I asked for", and both belong above the admin entries.
  { to: "/watchlist", label: "Watchlist", icon: Star },
  { to: "/sites", label: "Sites", icon: SitesIcon, adminOnly: true },
  // One entry, not two. Makers, models and calibers are three views of one
  // body of knowledge, and having "Makers" beside "Armory" invited exactly
  // the split it took a rewrite to remove: a maker carrying its own flat list
  // of models that nothing else could see.
  { to: "/armory", label: "Armory", icon: TagIcon, adminOnly: true },
  // Directly after the Armory, because the two answer the same question from
  // opposite ends: the Armory is what the catalog is allowed to say, and this
  // is the rules that decide what any one listing says.
  { to: "/classification", label: "Classification", icon: Sieve, adminOnly: true },
  { to: "/users", label: "Users", icon: UsersIcon, adminOnly: true },
  { to: "/backups", label: "Backups", icon: DatabaseIcon, adminOnly: true },
  { to: "/audit", label: "Audit log", icon: HistoryIcon, adminOnly: true },
  { to: "/settings", label: "Email digest", icon: Mail },
  // Its own entry. The password panel lived under "Email digest" since it was
  // written, and putting two-factor there too made that worse rather than
  // better: nobody looking for either clicks Email digest, and somebody went
  // looking and did not find it.
  { to: "/security", label: "Security settings", icon: Shield },
];

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

  const items = NAV.filter((entry) => !entry.adminOnly || isAdmin);

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

        <ul className="rail__list">
          {items.map(({ to, label, icon: Icon, end }) => (
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
