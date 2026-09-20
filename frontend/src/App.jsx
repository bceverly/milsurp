import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import Shell from "./components/Shell.jsx";
import Login from "./pages/Login.jsx";
import Browse from "./pages/Browse.jsx";
import ItemDetail from "./pages/ItemDetail.jsx";
import Sites from "./pages/Sites.jsx";
import SiteDetail from "./pages/SiteDetail.jsx";
import ScanDetail from "./pages/ScanDetail.jsx";
import UsersPage from "./pages/Users.jsx";
import ArmoryPage from "./pages/Armory.jsx";
import ClassificationPage from "./pages/Classification.jsx";
import ChangesPage from "./pages/Changes.jsx";
import HotDealsPage from "./pages/HotDeals.jsx";
import MarketPage from "./pages/Market.jsx";
import SettingsPage from "./pages/Settings.jsx";
import AuditLogPage from "./pages/AuditLog.jsx";
import BackupsPage from "./pages/Backups.jsx";
import SavedSearches from "./pages/SavedSearches.jsx";
import Watchlist from "./pages/Watchlist.jsx";
import SecurityPage from "./pages/Security.jsx";
import ResetPassword from "./pages/ResetPassword.jsx";

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
  const { user, loading } = useAuth();
  if (loading) return <FullPageSpinner />;
  if (!user) return <Navigate to="/login" replace />;
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
      <Route path="/reset/:token" element={<ResetPassword />} />
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
