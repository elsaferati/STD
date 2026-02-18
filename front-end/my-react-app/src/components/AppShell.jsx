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
  showPulse = false,
  pulseValue = 0,
  pulseMax = 1,
  sidebarContent = null,
}) {
  const { logout } = useAuth();
  const { t } = useI18n();
  const percent = Math.min((pulseValue / Math.max(pulseMax, 1)) * 100, 100);

  return (
    <div className="bg-background-light text-slate-800 font-display min-h-screen">
      <div className="fixed top-4 right-4 z-50 md:hidden">
        <LanguageSwitcher compact />
      </div>
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
                <div className="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-600 border border-slate-300">
                  <span className="material-icons text-lg">support_agent</span>
                  <span className="text-sm">{t("common.assistance")}</span>
                  <span className="ml-auto text-[10px] uppercase tracking-wide text-slate-600">{t("appShell.soon")}</span>
                </div>
              </div>
            </div>

            {showPulse ? (
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-slate-600 mb-3">{t("appShell.pulse")}</p>
                <div className="rounded-xl border border-slate-300 bg-slate-100 p-4 space-y-3">
                  <div>
                    <p className="text-xs text-slate-600">{t("appShell.queueHealth")}</p>
                    <p className="text-lg font-semibold text-slate-900">
                      {t("appShell.pending", { count: pulseValue })}
                    </p>
                  </div>
                  <div className="h-1.5 rounded-full bg-slate-300 overflow-hidden">
                    <div className="h-full bg-primary/80" style={{ width: `${percent}%` }} />
                  </div>
                  <p className="text-[11px] text-slate-600">{t("appShell.basedOnToday")}</p>
                </div>
              </div>
            ) : null}

            {sidebarContent ? (
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500 mb-3">{t("common.filters")}</p>
                {sidebarContent}
              </div>
            ) : null}
          </div>
          <div className="relative z-10 px-6 py-5 border-t border-slate-300/80">
            <button
              type="button"
              onClick={logout}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-slate-300 text-slate-800 hover:bg-slate-400 transition-colors"
            >
              <span className="material-icons text-lg">logout</span>
              <span className="text-sm font-medium">{t("common.logout")}</span>
            </button>
          </div>
        </aside>

        <div className="flex-1 flex flex-col h-screen overflow-y-auto lg:pl-6">
          {children}
        </div>
      </div>
    </div>
  );
}
