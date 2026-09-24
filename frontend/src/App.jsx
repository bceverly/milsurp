import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import PageLoading from "./components/PageLoading.jsx";
import Shell from "./components/Shell.jsx";
// In the first download: the sign-in screen and the inventory everybody
// lands on after it.
import Login from "./pages/Login.jsx";
import Browse from "./pages/Browse.jsx";

// Everything else is fetched the first time it is opened. The administrator's
// pages are most of the code -- the armory alone is over two thousand lines --
// and a reader who only browses and keeps a watchlist never opens them, so
// shipping them in the first download was weight every phone paid for nothing.
// Shell wraps the page area in Suspense, so the navigation stays put while a
// page loads rather than the whole screen blanking.
const ItemDetail = lazy(() => import("./pages/ItemDetail.jsx"));
const Sites = lazy(() => import("./pages/Sites.jsx"));
const SiteDetail = lazy(() => import("./pages/SiteDetail.jsx"));
const ScanDetail = lazy(() => import("./pages/ScanDetail.jsx"));
const UsersPage = lazy(() => import("./pages/Users.jsx"));
const ArmoryPage = lazy(() => import("./pages/Armory.jsx"));
const ClassificationPage = lazy(() => import("./pages/Classification.jsx"));
const ChangesPage = lazy(() => import("./pages/Changes.jsx"));
const HotDealsPage = lazy(() => import("./pages/HotDeals.jsx"));
const MarketPage = lazy(() => import("./pages/Market.jsx"));
const SettingsPage = lazy(() => import("./pages/Settings.jsx"));
const AuditLogPage = lazy(() => import("./pages/AuditLog.jsx"));
const BackupsPage = lazy(() => import("./pages/Backups.jsx"));
const SavedSearches = lazy(() => import("./pages/SavedSearches.jsx"));
const Watchlist = lazy(() => import("./pages/Watchlist.jsx"));
const SecurityPage = lazy(() => import("./pages/Security.jsx"));
const ResetPassword = lazy(() => import("./pages/ResetPassword.jsx"));

function FullPageSpinner() {
  return (
    <div className="boot">
      <div className="spinner" />
      <p>Loading…</p>
    </div>
  );
}

/** Routes that need any signed-in user. */
function Protected({ children }) {
  const { user, loading, leftOnPurpose } = useAuth();
  const location = useLocation();
  if (loading) return <FullPageSpinner />;
  // Where they were is carried to the sign-in screen so signing back in
  // returns them to it. Being dropped is rarely something the reader did on
  // purpose -- a session expires, or the server has a bad few minutes -- and
  // landing on the inventory afterwards loses their place every time.
  //
  // Pressing Sign out is the exception, and the only one: then the last page
  // they had open is the thing they have just said they were done with.
  if (!user) {
    const from = leftOnPurpose ? null : location.pathname + location.search;
    return <Navigate to="/login" replace state={from ? { from } : null} />;
  }
  return children;
}

/**
 * Routes that additionally need an administrator.
 *
 * This is a usability guard, not the security boundary — every admin endpoint
 * is enforced server-side. Hiding the pages just avoids showing a normal user
 * controls that would only ever return 403.
 */
function AdminOnly({ children }) {
  const { isAdmin } = useAuth();
  if (!isAdmin) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Outside the signed-in shell, like the login page: whoever
          followed this link cannot sign in, which is the point of it. */}
      <Route
        path="/reset/:token"
        element={
          <Suspense fallback={<PageLoading />}>
            <ResetPassword />
          </Suspense>
        }
      />
      <Route
        path="/"
        element={
          <Protected>
            <Shell />
          </Protected>
        }
      >
        <Route index element={<Browse />} />
        <Route path="items/:itemId" element={<ItemDetail />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="security" element={<SecurityPage />} />
        <Route path="backups" element={<BackupsPage />} />
        <Route path="audit" element={<AuditLogPage />} />
        <Route path="changes" element={<ChangesPage />} />
        <Route path="market" element={<MarketPage />} />
        <Route path="hot-deals" element={<HotDealsPage />} />
        <Route path="saved-searches" element={<SavedSearches />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route
          path="sites"
          element={
            <AdminOnly>
              <Sites />
            </AdminOnly>
          }
        />
        <Route path="sites/:siteId" element={<SiteDetail />} />
        <Route path="scans/:runId" element={<ScanDetail />} />
        {/* The old standalone Makers page. Kept as a redirect rather than a
            404, because it is bookmarked and linked from the release notes. */}
        <Route path="manufacturers" element={<Navigate to="/armory" replace />} />
        <Route
          path="armory"
          element={
            <AdminOnly>
              <ArmoryPage />
            </AdminOnly>
          }
        />
        <Route
          path="classification"
          element={
            <AdminOnly>
              <ClassificationPage />
            </AdminOnly>
          }
        />
        <Route
          path="users"
          element={
            <AdminOnly>
              <UsersPage />
            </AdminOnly>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
