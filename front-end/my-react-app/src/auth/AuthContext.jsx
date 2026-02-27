import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchJson } from "../api/http";
import { AuthContext } from "./context";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const loadUser = async () => {
      try {
        const payload = await fetchJson("/api/auth/me");
        if (active) {
          setUser(payload?.user || null);
        }
      } catch {
        if (active) {
          setUser(null);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };
    loadUser();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (username, password) => {
    const payload = await fetchJson("/api/auth/login", {
      method: "POST",
      body: { username, password },
    });
    setUser(payload?.user || null);
    return payload?.user || null;
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetchJson("/api/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({
      user,
      isAuthenticated: Boolean(user),
      loading,
      login,
      logout,
    }),
    [user, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
