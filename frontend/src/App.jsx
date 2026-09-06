import React from "react";
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
import ManufacturersPage from "./pages/Manufacturers.jsx";
import SettingsPage from "./pages/Settings.jsx";

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
        <Route
          path="manufacturers"
          element={
            <AdminOnly>
              <ManufacturersPage />
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
