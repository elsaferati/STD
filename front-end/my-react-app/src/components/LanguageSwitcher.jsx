import { useI18n } from "../i18n/I18nContext";

export function LanguageSwitcher({ compact = false, className = "" }) {
  const { lang, setLang, t, available } = useI18n();

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {compact ? null : (
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {t("common.language")}
        </span>
      )}
      <select
        value={lang}
        onChange={(event) => setLang(event.target.value)}
        className="text-sm rounded-md border border-slate-200 bg-white pl-3 pr-8 py-1.5 leading-5 min-w-[96px] focus:outline-none focus:ring-2 focus:ring-primary/60"
        aria-label={t("common.language")}
      >
        {available.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
