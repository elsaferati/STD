import { useI18n } from "../i18n/I18nContext";
import { validationStatusLabel } from "../utils/format";

const STYLES = {
  not_run: "bg-slate-100 text-slate-600 border-slate-200",
  passed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  flagged: "bg-rose-50 text-rose-700 border-rose-200",
  stale: "bg-amber-50 text-amber-700 border-amber-200",
  skipped: "bg-slate-100 text-slate-600 border-slate-200",
  error: "bg-red-50 text-red-700 border-red-200",
  resolved: "bg-cyan-50 text-cyan-700 border-cyan-200",
};

export function ValidationBadge({ status }) {
  const { t } = useI18n();
  const normalized = String(status || "not_run").toLowerCase();
  const color = STYLES[normalized] || STYLES.not_run;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${color}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {validationStatusLabel(normalized, t)}
    </span>
  );
}
