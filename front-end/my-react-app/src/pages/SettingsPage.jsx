import { AppShell } from "../components/AppShell";

export function SettingsPage() {
  return (
    <AppShell>
      <div className="max-w-5xl space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Settings</h1>
          <p className="text-sm text-slate-500">Application preferences and controls will appear here.</p>
        </div>

        <div className="bg-surface-light border border-slate-200 rounded-xl p-8 text-center shadow-sm">
          <span className="material-icons text-3xl text-slate-400 mb-2">settings</span>
          <h2 className="text-lg font-semibold text-slate-900">Coming soon</h2>
          <p className="text-sm text-slate-500 mt-1">This section is a placeholder for upcoming settings options.</p>
        </div>
      </div>
    </AppShell>
  );
}
