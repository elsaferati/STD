import { useI18n } from "../i18n/I18nContext";
import { statusLabel } from "../utils/format";

const STYLES = {
  ok: "bg-success/10 text-success border-success/20",
  reply: "bg-red-50 text-red-700 border-red-200",
  human_in_the_loop: "bg-orange-50 text-orange-700 border-orange-200",
  post: "bg-slate-100 text-slate-600 border-slate-200",
  failed: "bg-danger/10 text-danger border-danger/20",
  partial: "bg-red-50 text-red-700 border-red-200",
  unknown: "bg-slate-100 text-slate-600 border-slate-200",
  waiting_for_reply: "bg-amber-50 text-amber-700 border-amber-200",
  client_replied: "bg-blue-50 text-blue-700 border-blue-200",
  updated_after_reply: "bg-teal-50 text-teal-700 border-teal-200",
};

export function StatusBadge({ status }) {
  const { t } = useI18n();
  const raw = (status || "ok").toLowerCase();
  const normalized = raw === "partial" ? "reply" : raw === "unknown" ? "ok" : raw;
  const color = STYLES[normalized] || STYLES.unknown;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${color}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {statusLabel(normalized, t)}
    </span>
  );
}
