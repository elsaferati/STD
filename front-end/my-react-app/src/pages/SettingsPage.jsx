import { AppShell } from "../components/AppShell";
import { useI18n } from "../i18n/I18nContext";

export function SettingsPage() {
  const { t } = useI18n();
  return (
    <AppShell>
      <div className="max-w-5xl space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{t("settings.title")}</h1>
          <p className="text-sm text-slate-500">{t("settings.subtitle")}</p>
        </div>

        <div className="bg-surface-light border border-slate-200 rounded-xl p-8 text-center shadow-sm">
          <span className="material-icons text-3xl text-slate-400 mb-2">settings</span>
          <h2 className="text-lg font-semibold text-slate-900">{t("settings.comingSoon")}</h2>
          <p className="text-sm text-slate-500 mt-1">{t("settings.placeholder")}</p>
        </div>
      </div>
    </AppShell>
  );
}
