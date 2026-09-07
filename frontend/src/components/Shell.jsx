/**
 * Application shell: header, navigation and the routed content area.
 *
 * Responsive by structure rather than by duplication — the same nav markup is
 * a fixed sidebar on desktop and a slide-in drawer on phones, driven entirely
 * by CSS. Only the drawer's open/closed state lives in JavaScript.
 */
import React, { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth.jsx";
import {
  Logout,
  Mail,
  Menu,
  Rifle,
  Sites as SitesIcon,
  Tag as TagIcon,
  Users as UsersIcon,
  X,
} from "./Icons.jsx";
import Insignia from "./Insignia.jsx";

const NAV = [
  { to: "/", label: "Inventory", icon: Rifle, end: true },
  { to: "/sites", label: "Sites", icon: SitesIcon, adminOnly: true },
  // One entry, not two. Makers, models and calibers are three views of one
  // body of knowledge, and having "Makers" beside "Armory" invited exactly
  // the split it took a rewrite to remove: a maker carrying its own flat list
  // of models that nothing else could see.
  { to: "/armory", label: "Armory", icon: TagIcon, adminOnly: true },
  { to: "/users", label: "Users", icon: UsersIcon, adminOnly: true },
  { to: "/settings", label: "Email digest", icon: Mail },
];

export default function Shell() {
  const { user, isAdmin, signOut } = useAuth();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

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
        <Outlet />
      </main>
    </div>
  );
}
