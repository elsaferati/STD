import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { useI18n } from "../i18n/I18nContext";
import { LanguageSwitcher } from "./LanguageSwitcher";

function NavLink({ to, active, icon, label }) {
  const activeClasses = "bg-white text-slate-900 border border-slate-200 shadow-sm";
  const idleClasses = "text-slate-600 hover:text-slate-900 hover:bg-white/70";
  return (
    <Link
      to={to}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${active ? activeClasses : idleClasses}`}
    >
      <span className={`material-icons text-lg ${active ? "text-primary" : ""}`}>{icon}</span>
      <span className="text-sm font-semibold">{label}</span>
    </Link>
  );
}

export function AppShell({
  active,
  children,
  sidebarContent = null,
  headerLeft = null,
}) {
  const { user, logout } = useAuth();
  const { t } = useI18n();
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);

  const isAdminLike = user?.role === "admin" || user?.role === "superadmin";
  const username = user?.username ?? user?.email ?? "";
  const showUser = Boolean(username);

  useEffect(() => {
    if (!isUserMenuOpen) {
      return undefined;
    }

    const handlePointerDown = (event) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target)) {
        setIsUserMenuOpen(false);
      }
    };

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setIsUserMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isUserMenuOpen]);

  const handleLogout = async () => {
    setIsUserMenuOpen(false);
    await logout();
  };

  return (
    <div className="bg-background-light text-slate-800 font-display min-h-screen">
      <div className="flex min-h-screen overflow-hidden">
        <aside className="hidden lg:flex w-64 flex-col bg-[#EEF1F4] text-slate-800 relative overflow-hidden sticky top-0 h-screen shadow-[6px_0_6px_rgba(15,23,42,0.08)] border-r border-slate-200/80">
          <div className="absolute inset-0 bg-gradient-to-b from-[#F6F7F9] via-[#EEF1F4] to-[#E2E6EA] opacity-100" />
          <div className="relative z-10 px-6 py-6 border-b border-slate-300/80">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-xl bg-primary/15 border border-primary/30 flex items-center justify-center text-primary font-bold text-xl shadow-glow">
                S
              </div>
              <div>
                <p className="text-sm uppercase tracking-[0.2em] text-slate-600">{t("appShell.operations")}</p>
                <h2 className="text-lg font-semibold text-slate-900">{t("appShell.controlCenter")}</h2>
              </div>
            </div>
          </div>
          <div className="relative z-10 flex-1 px-4 py-6 space-y-6 overflow-y-auto">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-600 mb-3">{t("common.navigation")}</p>
              <div className="space-y-2">
                <NavLink to="/" active={active === "overview"} icon="space_dashboard" label={t("common.overview")} />
                <NavLink to="/orders" active={active === "orders"} icon="receipt_long" label={t("common.orders")} />
                <NavLink to="/clients" active={active === "clients"} icon="groups" label={t("common.clients")} />
                <NavLink to="/data-export" active={active === "dataExport"} icon="file_download" label={t("common.dataExport")} />
                <NavLink to="/excel-orders" active={active === "excelOrders"} icon="table_view" label={t("common.excelOrders")} />
                {isAdminLike ? (
                  <NavLink to="/settings" active={active === "settings"} icon="settings" label={t("common.settings")} />
                ) : null}
                {isAdminLike ? (
                  <NavLink to="/users" active={active === "users"} icon="manage_accounts" label={t("common.users")} />
                ) : null}
              </div>
            </div>

            {sidebarContent ? (
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500 mb-3">{t("common.filters")}</p>
                {sidebarContent}
              </div>
            ) : null}
          </div>
        </aside>

        <div className="flex-1 flex flex-col h-screen overflow-y-auto lg:px-6">
          <header className="sticky top-0 z-30 bg-surface-light border-b border-slate-200">
            <div className="h-16 px-6 flex items-center justify-between gap-4">
              <div className="min-w-0 flex-1">
                {headerLeft}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <LanguageSwitcher compact />
                {showUser ? (
                  <div ref={userMenuRef} className="relative">
                    <button
                      type="button"
                      onClick={() => setIsUserMenuOpen((open) => !open)}
                      aria-haspopup="menu"
                      aria-expanded={isUserMenuOpen}
                      className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-50"
                    >
                      <span className="material-icons text-lg text-slate-500">account_circle</span>
                      <span className="text-sm font-medium">{username}</span>
                      <span className={`material-icons text-base text-slate-400 transition-transform ${isUserMenuOpen ? "rotate-180" : ""}`}>
                        expand_more
                      </span>
                    </button>
                    {isUserMenuOpen ? (
                      <div className="absolute right-0 top-[calc(100%+0.5rem)] w-44 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg">
                        <button
                          type="button"
                          onClick={handleLogout}
                          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100"
                        >
                          <span className="material-icons text-base">logout</span>
                          <span>{t("common.logout")}</span>
                        </button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </header>
          {children}
        </div>
      </div>
    </div>
  );
}
