import { NavLink } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";

function navItemClass(isActive) {
  return [
    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
    isActive
      ? "bg-primary/10 text-primary"
      : "text-slate-600 hover:text-slate-900 hover:bg-slate-100",
  ].join(" ");
}

export function SidebarNav() {
  const { t } = useI18n();
  const navItems = [
    { to: "/", label: t("common.dashboard"), icon: "dashboard", end: true },
    { to: "/orders", label: t("common.orders"), icon: "receipt_long" },
    { to: "/clients", label: t("common.clients"), icon: "groups" },
    { to: "/settings", label: t("common.settings"), icon: "settings" },
  ];
  return (
    <div className="border-b border-slate-100">
      <div className="h-16 flex items-center px-6 border-b border-slate-100">
        <div className="w-8 h-8 rounded bg-gradient-to-br from-primary to-cyan-600 flex items-center justify-center mr-3 shadow-lg shadow-primary/20">
          <span className="text-white font-bold text-lg">X</span>
        </div>
        <span className="font-bold text-xl tracking-tight text-slate-900">
          XXLUTZ <span className="text-primary font-normal">Agent</span>
        </span>
      </div>

      <nav className="p-4 space-y-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => navItemClass(isActive)}
          >
            <span className="material-icons text-lg">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
