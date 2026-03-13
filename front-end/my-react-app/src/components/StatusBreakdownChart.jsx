import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatPercent } from "../utils/format";
import { calculateStatusPercentages, STATUS_KEYS } from "../utils/statusBreakdown";

const STATUS_SERIES = [
  { key: "ok", labelKey: "status.ok", fallbackLabel: "OK", color: "#10b981" },
  {
    key: "waitingForReply",
    labelKey: "status.waiting_for_reply",
    fallbackLabel: "Waiting for Reply",
    color: "#fbbf24",
  },
  {
    key: "updatedAfterReply",
    labelKey: "status.updated_after_reply",
    fallbackLabel: "Updated After Reply",
    color: "#14b8a6",
  },
  {
    key: "humanInTheLoop",
    labelKey: "status.human_in_the_loop",
    fallbackLabel: "Human in the Loop",
    color: "#a78bfa",
  },
  { key: "post", labelKey: "status.post", fallbackLabel: "Post", color: "#475569" },
  {
    key: "unknownClient",
    labelKey: "status.unknown",
    fallbackLabel: "Unknown Client",
    color: "#7dd3fc",
  },
  { key: "failed", labelKey: "status.failed", fallbackLabel: "Failed", color: "#f43f5e" },
];

function formatAxisDate(value, locale) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value || "");
  }
  return date.toLocaleDateString(locale || undefined, { month: "short", day: "numeric" });
}

function getTopStatusKey(day) {
  for (let index = STATUS_KEYS.length - 1; index >= 0; index -= 1) {
    const key = STATUS_KEYS[index];
    if (Number(day?.[key] || 0) > 0) {
      return key;
    }
  }
  return STATUS_KEYS[STATUS_KEYS.length - 1];
}

function CustomTooltip({ active, payload, label, locale, t, viewMode }) {
  if (!active || !payload?.length) {
    return null;
  }

  const day = payload[0]?.payload?.source;
  const percentages = calculateStatusPercentages(day);
  const rows = STATUS_SERIES.filter((series) => Number(day?.[series.key] || 0) > 0);

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-lg">
      <div className="text-xs font-semibold text-slate-900">{formatAxisDate(label, locale)}</div>
      {rows.map((series) => (
        <div key={series.key} className="mt-1 flex items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2 text-slate-600">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: series.color }} />
            <span>{t(series.labelKey, null, series.fallbackLabel)}</span>
          </div>
          <span className="font-semibold text-slate-900">
            {viewMode === "percentage"
              ? formatPercent(percentages[series.key])
              : Number(day?.[series.key] || 0)}
          </span>
        </div>
      ))}
    </div>
  );
}

export function StatusBreakdownChart({ data, locale, t, onSelectDay, selectedDay }) {
  const [viewMode, setViewMode] = useState("volume");

  const chartData = useMemo(
    () =>
      (data || []).map((day) => ({
        ...day,
        source: day,
      })),
    [data],
  );

  const handleChartClick = (state) => {
    const day = state?.activePayload?.[0]?.payload?.source;
    if (day) {
      onSelectDay?.(day);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <div className="inline-flex rounded-xl border border-slate-200 bg-slate-50 p-1">
          <button
            type="button"
            onClick={() => setViewMode("volume")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              viewMode === "volume" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            {t("overview.volumeView")}
          </button>
          <button
            type="button"
            onClick={() => setViewMode("percentage")}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              viewMode === "percentage" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            {t("overview.percentageView")}
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              barSize={40}
              stackOffset={viewMode === "percentage" ? "expand" : "none"}
              margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
              onClick={handleChartClick}
            >
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={(value) => formatAxisDate(value, locale)}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "#64748b", fontSize: 12 }}
              />
              <YAxis
                tickFormatter={(value) => (viewMode === "percentage" ? formatPercent(Number(value) * 100) : value)}
                tickLine={false}
                axisLine={false}
                width={48}
                tick={{ fill: "#64748b", fontSize: 12 }}
                domain={viewMode === "percentage" ? [0, 1] : [0, "auto"]}
                allowDecimals={viewMode === "percentage"}
              />
              <Tooltip
                cursor={{ fill: "#e2e8f0", fillOpacity: 0.35 }}
                content={<CustomTooltip locale={locale} t={t} viewMode={viewMode} />}
              />
              {STATUS_SERIES.map((series) => (
                <Bar
                  key={series.key}
                  dataKey={series.key}
                  stackId="status"
                  fill={series.color}
                  name={t(series.labelKey, null, series.fallbackLabel)}
                >
                  {chartData.map((day) => (
                    <Cell
                      key={`${day.date}-${series.key}`}
                      radius={getTopStatusKey(day) === series.key ? [4, 4, 0, 0] : [0, 0, 0, 0]}
                      stroke={selectedDay?.date === day.date ? "#0f172a" : "none"}
                      strokeWidth={selectedDay?.date === day.date ? 1 : 0}
                      cursor="pointer"
                    />
                  ))}
                </Bar>
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
