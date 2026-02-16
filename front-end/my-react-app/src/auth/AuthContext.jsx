import { useCallback, useMemo, useState } from "react";
import { AuthContext } from "./context";

const TOKEN_STORAGE_KEY = "xxlutz_dashboard_token";

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) || "");

  const login = useCallback((nextToken) => {
    const normalized = (nextToken || "").trim();
    localStorage.setItem(TOKEN_STORAGE_KEY, normalized);
    setToken(normalized);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken("");
  }, []);

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: Boolean(token),
      login,
      logout,
    }),
    [token, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
