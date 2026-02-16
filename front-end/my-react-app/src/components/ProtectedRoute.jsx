import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";

export function ProtectedRoute() {
  const { token, logout } = useAuth();
  const location = useLocation();
  const [verifiedToken, setVerifiedToken] = useState("");

  useEffect(() => {
    if (!token) {
      return undefined;
    }

    let active = true;
    const controller = new AbortController();

    fetchJson("/api/auth/check", { token, signal: controller.signal })
      .then(() => {
        if (active) {
          setVerifiedToken(token);
        }
      })
      .catch(() => {
        if (active) {
          logout();
          setVerifiedToken("");
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [token, logout]);

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (verifiedToken !== token) {
    return (
      <div className="min-h-screen bg-background-light flex items-center justify-center text-slate-600 font-display">
        Checking session...
      </div>
    );
  }

  return <Outlet />;
}
