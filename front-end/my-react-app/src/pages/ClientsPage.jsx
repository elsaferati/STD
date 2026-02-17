import { AppShell } from "../components/AppShell";

export function ClientsPage() {
  return (
    <AppShell>
      <div className="max-w-5xl space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Clients</h1>
          <p className="text-sm text-slate-500">Client management will be available here.</p>
        </div>

        <div className="bg-surface-light border border-slate-200 rounded-xl p-8 text-center shadow-sm">
          <span className="material-icons text-3xl text-slate-400 mb-2">groups</span>
          <h2 className="text-lg font-semibold text-slate-900">Coming soon</h2>
          <p className="text-sm text-slate-500 mt-1">This section is a placeholder for upcoming client features.</p>
        </div>
      </div>
    </AppShell>
  );
}
