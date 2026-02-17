import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { SidebarNav } from "./SidebarNav";

export function AppShell({ children, sidebarContent = null }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const queryValue = new URLSearchParams(location.search).get("q") || "";

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const query = String(formData.get("q") || "").trim();
    navigate(query ? `/orders?q=${encodeURIComponent(query)}` : "/orders");
  };

  return (
    <div className="min-h-screen flex overflow-hidden bg-background-light font-display text-slate-800">
      <aside className="fixed inset-y-0 left-0 z-20 w-72 bg-surface-light border-r border-slate-200 shadow-sm flex flex-col">
        <SidebarNav />
        {sidebarContent ? (
          <div className="flex-1 overflow-y-auto">{sidebarContent}</div>
        ) : (
          <div className="flex-1" />
        )}
      </aside>

      <div className="ml-72 flex-1 flex flex-col min-w-0">
        <header className="h-16 bg-surface-light border-b border-slate-200 flex items-center justify-between px-6 z-10">
          <form onSubmit={handleSearchSubmit} className="relative w-full max-w-xl">
            <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">search</span>
            <input
              key={`${location.pathname}:${location.search}`}
              name="q"
              className="w-full bg-slate-50 border-none rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary"
              placeholder="Search by ticket, KOM, message id, filename"
              defaultValue={queryValue}
            />
          </form>
          <div className="flex items-center gap-3 ml-4">
            <button
              onClick={logout}
              type="button"
              className="text-sm px-3 py-1.5 rounded-lg bg-slate-900 text-white hover:bg-slate-700"
            >
              Logout
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  );
}
