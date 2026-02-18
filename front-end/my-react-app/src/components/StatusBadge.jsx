import { useI18n } from "../i18n/I18nContext";
import { statusLabel } from "../utils/format";

const STYLES = {
  ok: "bg-success/10 text-success border-success/20",
  partial: "bg-warning/10 text-warning border-warning/20",
  failed: "bg-danger/10 text-danger border-danger/20",
  unknown: "bg-slate-100 text-slate-600 border-slate-200",
};

export function StatusBadge({ status }) {
  const { t } = useI18n();
  const normalized = (status || "unknown").toLowerCase();
  const color = STYLES[normalized] || STYLES.unknown;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${color}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {statusLabel(normalized, t)}
    </span>
  );
}
