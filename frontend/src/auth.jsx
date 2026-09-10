/**
 * Authentication context.
 *
 * Holds the signed-in user and exposes sign in / sign out. On mount it
 * revalidates any token left in sessionStorage against /auth/me, so a token
 * that expired, was revoked by a password change, or belongs to a since-disabled
 * account never produces a half-working UI.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  // Any 401 anywhere in the app drops the session rather than leaving the user
  // clicking around a UI whose requests all fail.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    let canceled = false;
    if (!getToken()) {
      setLoading(false);
      return undefined;
    }
    api
      .me()
      .then((me) => {
        if (!canceled) setUser(me);
      })
      .catch(() => {
        if (!canceled) {
          setToken(null);
          setUser(null);
        }
      })
      .finally(() => {
        if (!canceled) setLoading(false);
      });
    return () => {
      canceled = true;
    };
  }, []);

  const signIn = useCallback(async (username, password) => {
    const result = await api.login(username, password);
    setToken(result.access_token);
    setUser(result.user);
    return result.user;
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      signIn,
      signOut,
      isAdmin: user?.role === "admin",
      refresh: () => api.me().then(setUser),
    }),
    [user, loading, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside an AuthProvider");
  }
  return context;
}
