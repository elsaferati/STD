import { AppShell } from "../components/AppShell";
import { useI18n } from "../i18n/I18nContext";

export function ClientsPage() {
  const { t } = useI18n();
  return (
    <AppShell active="clients">
      <div className="max-w-5xl space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{t("clients.title")}</h1>
          <p className="text-sm text-slate-500">{t("clients.subtitle")}</p>
        </div>

        <div className="bg-surface-light border border-slate-200 rounded-xl p-8 text-center shadow-sm">
          <span className="material-icons text-3xl text-slate-400 mb-2">groups</span>
          <h2 className="text-lg font-semibold text-slate-900">{t("clients.comingSoon")}</h2>
          <p className="text-sm text-slate-500 mt-1">{t("clients.placeholder")}</p>
        </div>
      </div>
    </AppShell>
  );
}
