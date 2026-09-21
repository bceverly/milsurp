/**
 * Authentication context.
 *
 * Holds the signed-in user and exposes sign in / sign out. The session itself
 * is an `HttpOnly` cookie this code cannot see -- which is the point of it --
 * so "are we signed in?" is a question only the server can answer. On mount it
 * asks, via /auth/me, and a session that expired, was revoked by a password
 * change, or belongs to a since-disabled account never produces a half-working
 * UI.
 *
 * That ask now happens on every load rather than only when a stored token
 * existed, because there is no longer anything on this side to check first.
 * One request, and it is the same one that used to run whenever a token was
 * present.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api, setUnauthorizedHandler } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  // **Whether leaving was their idea.** Signing back in returns a reader to
  // the page they were on, which is right when the session expired underneath
  // them and wrong when they pressed Sign out -- then the last page they had
  // open is the one thing they have just said they were finished with, and
  // reopening it is the app arguing. Defaults to false, so arriving at a deep
  // link with no session still counts as somewhere they meant to go.
  const [deliberate, setDeliberate] = useState(false);

  const signOut = useCallback(() => {
    setDeliberate(true);
    // The server has to do it: a cookie belongs to the browser, and only a
    // response can ask it to let go. Forgetting the user locally without this
    // leaves the session alive and the next reload signed straight back in.
    // The local state is cleared either way -- a network failure on the way
    // out must not leave somebody looking at a page they asked to leave.
    api.logout().finally(() => setUser(null));
  }, []);

  // Any 401 anywhere in the app drops the session rather than leaving the user
  // clicking around a UI whose requests all fail.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setDeliberate(false);
      setUser(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    let canceled = false;
    api
      .me()
      .then((me) => {
        if (!canceled) setUser(me);
      })
      .catch(() => {
        // No session, or one the server no longer honors. Either way the
        // answer is the sign-in screen.
        if (!canceled) setUser(null);
      })
      .finally(() => {
        if (!canceled) setLoading(false);
      });
    return () => {
      canceled = true;
    };
  }, []);

  /**
   * Sign in, in one exchange or two.
   *
   * Returns null when the server wants a second factor. Null rather than an
   * exception, because being asked for a code is not a failure: the password
   * was right, and the page's next move is to show a field rather than an
   * error.
   */
  const signIn = useCallback(async (username, password, totpCode) => {
    const result = await api.login(username, password, totpCode);
    if (result?.two_factor_required) return null;
    // Nothing to keep: the session and the CSRF token both arrived as cookies.
    setDeliberate(false);
    setUser(result.user);
    return result.user;
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      signIn,
      signOut,
      //: True only when they pressed Sign out. Every other way of ending up
      //: signed out -- an expired session, a 401, arriving cold at a deep
      //: link -- leaves the page they wanted worth coming back to.
      leftOnPurpose: deliberate,
      isAdmin: user?.role === "admin",
      refresh: () => api.me().then(setUser),
    }),
    [user, loading, deliberate, signIn, signOut],
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
