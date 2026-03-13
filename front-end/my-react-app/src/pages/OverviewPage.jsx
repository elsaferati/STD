import { useCallback, useEffect, useRef, useState } from "react";
import { fetchJson, withQuery } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { OrderClientTimelineChart } from "../components/OrderClientTimelineChart";
import { StatusBreakdownChart } from "../components/StatusBreakdownChart";

import { useI18n } from "../i18n/I18nContext";
import { formatDate, formatPercent } from "../utils/format";

const RANGE_PRESETS = [
  { id: "today", labelKey: "overview.rangeToday" },
  { id: "week", labelKey: "overview.rangeThisWeek" },
  { id: "month", labelKey: "overview.rangeThisMonth" },
  { id: "custom_month", labelKey: "overview.rangeSelectMonth" },
  { id: "3m", labelKey: "overview.rangeThreeMonths" },
  { id: "6m", labelKey: "overview.rangeSixMonths" },
  { id: "year", labelKey: "overview.rangeThisYear" },
];

const STATUS_CONFIG = [
  {
    key: "ok",
    labelKey: "status.ok",
    icon: "check_circle",
    accentClass: "border-l-4 border-l-emerald-500",
    iconClass: "text-emerald-600 bg-emerald-50",
    dotClass: "bg-emerald-500",
  },
  {
    key: "waiting_for_reply",
    labelKey: "status.waiting_for_reply",
    icon: "mail",
    accentClass: "border-l-4 border-l-amber-400",
    iconClass: "text-amber-700 bg-amber-50",
    dotClass: "bg-amber-300",
  },
  {
    key: "updated_after_reply",
    labelKey: "status.updated_after_reply",
    icon: "published_with_changes",
    accentClass: "border-l-4 border-l-teal-500",
    iconClass: "text-teal-700 bg-teal-50",
    dotClass: "bg-teal-400",
  },
  {
    key: "human_in_the_loop",
    labelKey: "status.human_in_the_loop",
    icon: "manage_search",
    accentClass: "border-l-4 border-l-violet-400",
    iconClass: "text-violet-700 bg-violet-50",
    dotClass: "bg-violet-300",
  },
  {
    key: "post",
    labelKey: "status.post",
    icon: "local_post_office",
    accentClass: "border-l-4 border-l-slate-500",
    iconClass: "text-slate-700 bg-slate-100",
    dotClass: "bg-slate-400",
  },
  {
    key: "unknown",
    labelKey: "status.unknown",
    icon: "person_add",
    accentClass: "border-l-4 border-l-sky-400",
    iconClass: "text-sky-700 bg-sky-50",
    dotClass: "bg-sky-300",
  },
  {
    key: "failed",
    labelKey: "status.failed",
    icon: "error",
    accentClass: "border-l-4 border-l-rose-500",
    iconClass: "text-rose-700 bg-rose-50",
    dotClass: "bg-rose-400",
  },
];

function MetricCard({ title, value, detail, icon, accentClass = "", iconClass = "text-primary bg-primary/10" }) {
  return (
    <div className={`bg-surface-light p-3 rounded-xl border border-slate-200 shadow-sm ${accentClass}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-slate-500 font-medium break-words">{title}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1.5">{value}</p>
          <p className="text-[13px] text-slate-500 mt-1.5">{detail}</p>
        </div>
        <span className={`material-icons shrink-0 p-2 rounded-xl text-lg ${iconClass}`}>{icon}</span>
      </div>
    </div>
  );
}

function getCurrentMonthToken() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  return `${year}-${month}`;
}

function buildMonthOptions(locale, count = 18) {
  const options = [];
  const cursor = new Date();
  cursor.setDate(1);
  for (let index = 0; index < count; index += 1) {
    const year = cursor.getFullYear();
    const month = String(cursor.getMonth() + 1).padStart(2, "0");
    const value = `${year}-${month}`;
    const label = cursor.toLocaleDateString(locale || undefined, { month: "long", year: "numeric" });
    options.push({ value, label });
    cursor.setMonth(cursor.getMonth() - 1);
  }
  return options;
}

function buildYearOptions(count = 6) {
  const currentYear = new Date().getFullYear();
  return Array.from({ length: count }, (_, index) => {
    const year = currentYear - index;
    return { value: String(year), label: String(year) };
  });
}

function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function getBucketTotals(bucket) {
  const ok = toNumber(bucket?.ok);
  const waitingForReply = toNumber(bucket?.waiting_for_reply ?? bucket?.reply);
  const humanInTheLoop = toNumber(bucket?.human_in_the_loop);
  const post = toNumber(bucket?.post);
  const unknown = toNumber(bucket?.unknown);
  const failed = toNumber(bucket?.failed);
  const updatedAfterReply = toNumber(bucket?.updated_after_reply);
  const total =
    toNumber(bucket?.total) ||
    (ok + waitingForReply + humanInTheLoop + post + unknown + failed + updatedAfterReply);
  return {
    ok,
    waitingForReply,
    humanInTheLoop,
    post,
    unknown,
    failed,
    updatedAfterReply,
    total,
  };
}

function formatRangeLabel(range, locale) {
  if (!range?.start || !range?.end) {
    return "";
  }
  const startDate = new Date(range.start);
  const endDate = new Date(range.end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return "";
  }
  const inclusiveEnd = new Date(endDate.getTime() - 1);
  if (startDate.toDateString() === inclusiveEnd.toDateString()) {
    return formatDate(startDate.toISOString(), locale);
  }
  return `${formatDate(startDate.toISOString(), locale)} - ${formatDate(inclusiveEnd.toISOString(), locale)}`;
}

function formatBucketLabel(bucket, locale, granularity) {
  if (!bucket?.date) {
    return "";
  }
  const date = new Date(bucket.date);
  if (Number.isNaN(date.getTime())) {
    return String(bucket.label || bucket.date);
  }
  if (granularity === "month") {
    return date.toLocaleDateString(locale || undefined, { month: "short", year: "numeric" });
  }
  return formatDate(bucket.date, locale);
}

function normalizeOverviewSummary(payload) {
  const periodSummary = payload?.summary;
  if (periodSummary && typeof periodSummary === "object" && periodSummary.statuses) {
    return periodSummary;
  }

  const legacy = payload?.today || {};
  const total = toNumber(legacy?.total);
  return {
    total,
    statuses: {
      ok: { count: toNumber(legacy?.ok), rate: toNumber(legacy?.ok_rate) },
      waiting_for_reply: { count: toNumber(legacy?.reply), rate: toNumber(legacy?.reply_rate) },
      human_in_the_loop: { count: toNumber(legacy?.human_in_the_loop), rate: toNumber(legacy?.human_in_the_loop_rate) },
      post: { count: toNumber(legacy?.post), rate: toNumber(legacy?.post_rate) },
      unknown: { count: toNumber(payload?.queue_counts?.unknown), rate: 0 },
      failed: { count: toNumber(legacy?.failed), rate: toNumber(legacy?.failed_rate) },
      updated_after_reply: { count: 0, rate: 0 },
    },
  };
}

export function OverviewPage() {
  const { t, locale } = useI18n();
  const { user } = useAuth();
  const isSuperadmin = Boolean(user?.is_super_admin);
  const [overview, setOverview] = useState(null);
  const [xmlActivity, setXmlActivity] = useState(null);
  const [error, setError] = useState("");
  const [selectedDay, setSelectedDay] = useState(null);
  const [rangePreset, setRangePreset] = useState("today");
  const [selectedMonth, setSelectedMonth] = useState(getCurrentMonthToken());
  const [isMonthMenuOpen, setIsMonthMenuOpen] = useState(false);
  const [selectedYear, setSelectedYear] = useState(String(new Date().getFullYear()));
  const [isYearMenuOpen, setIsYearMenuOpen] = useState(false);
  const monthMenuRef = useRef(null);
  const yearMenuRef = useRef(null);

  const loadOverview = useCallback(async () => {
    try {
      const payload = await fetchJson(
        withQuery("/api/overview", {
          range: rangePreset,
          month: rangePreset === "custom_month" ? selectedMonth : null,
          year: rangePreset === "year" ? selectedYear : null,
        }),
      );
      setOverview(payload);
      setError("");
    } catch (requestError) {
      setError(requestError.message || t("overview.loadError"));
    }
  }, [rangePreset, selectedMonth, selectedYear, t]);

  useEffect(() => {
    loadOverview();
    const intervalId = setInterval(loadOverview, 15000);
    return () => clearInterval(intervalId);
  }, [loadOverview]);

  const loadXmlActivity = useCallback(async () => {
    if (!isSuperadmin) return;
    try {
      const payload = await fetchJson(
        withQuery("/api/superadmin/xml-activity", {
          range: rangePreset,
          month: rangePreset === "custom_month" ? selectedMonth : null,
          year: rangePreset === "year" ? selectedYear : null,
        }),
      );
      setXmlActivity(payload);
    } catch { /* silent — section simply won't render */ }
  }, [isSuperadmin, rangePreset, selectedMonth, selectedYear]);

  useEffect(() => {
    loadXmlActivity();
    const id = setInterval(loadXmlActivity, 15000);
    return () => clearInterval(id);
  }, [loadXmlActivity]);

  useEffect(() => {
    setSelectedDay(null);
  }, [overview?.range?.preset, overview?.range?.month, overview?.range?.start, overview?.range?.end]);

  useEffect(() => {
    if (!isMonthMenuOpen) {
      return undefined;
    }
    const handlePointerDown = (event) => {
      if (!monthMenuRef.current?.contains(event.target)) {
        setIsMonthMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [isMonthMenuOpen]);

  useEffect(() => {
    if (!isYearMenuOpen) {
      return undefined;
    }
    const handlePointerDown = (event) => {
      if (!yearMenuRef.current?.contains(event.target)) {
        setIsYearMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [isYearMenuOpen]);

  const summary = normalizeOverviewSummary(overview);
  const statusByDay = overview?.status_by_day || [];
  const statusChartData = statusByDay.map((bucket) => {
    const totals = getBucketTotals(bucket);
    return {
      date: bucket.date,
      ok: totals.ok,
      waitingForReply: totals.waitingForReply,
      updatedAfterReply: totals.updatedAfterReply,
      humanInTheLoop: totals.humanInTheLoop,
      post: totals.post,
      unknownClient: totals.unknown,
      failed: totals.failed,
      total: totals.total,
      sourceBucket: bucket,
    };
  });
  const hasActivity = statusChartData.some((bucket) => bucket.total > 0);
  const latestActiveDay = (() => {
    for (let index = statusChartData.length - 1; index >= 0; index -= 1) {
      if (statusChartData[index]?.total > 0) {
        return statusChartData[index];
      }
    }
    return null;
  })();
  const safeSelectedDay =
    selectedDay && statusChartData.some((bucket) => bucket.date === selectedDay.date)
      ? selectedDay
      : null;
  const effectiveSelectedDay = safeSelectedDay ?? latestActiveDay;
  const selectedBucket = effectiveSelectedDay?.sourceBucket || null;
  const selectedTotals = effectiveSelectedDay || null;
  const bucketGranularity = overview?.range?.bucket_granularity || "day";
  const clientHourData = overview?.orders_by_client_hour || { clients: [], days: [] };
  const clientHourDays = clientHourData.days || [];
  const selectedClientDay = null;
  const selectedLabel = selectedBucket
    ? formatBucketLabel(selectedBucket, locale, bucketGranularity)
    : "";
  const rangeLabel = formatRangeLabel(overview?.range, locale);
  const chartRangeLabel = formatRangeLabel(
    overview?.range
      ? {
          start: overview.range.chart_start,
          end: overview.range.chart_end,
        }
      : null,
    locale,
  );
  const timelineView =
    rangePreset === "week"
      ? "weekly"
      : rangePreset === "month" || rangePreset === "custom_month"
        ? "monthly"
        : rangePreset === "3m"
          ? "quarter"
          : rangePreset === "6m"
            ? "half_year"
            : rangePreset === "year"
              ? "year"
              : "daily";
  const isLongRangeTimeline = ["quarter", "half_year", "year"].includes(timelineView);
  const monthOptions = buildMonthOptions(locale);
  const yearOptions = buildYearOptions();

  return (
    <AppShell active="overview">
      <main className="flex-1 max-w-[1600px] mx-auto w-full p-6 space-y-6">
        <section className="bg-surface-light rounded-2xl border border-slate-200 shadow-sm p-4">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-primary/15 rounded-xl flex items-center justify-center text-primary font-bold text-xl">
                S
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-slate-900">{t("overview.title")}</h1>
                <p className="text-[13px] text-slate-500 mt-1">{t("overview.subtitle")}</p>
                {rangeLabel ? (
                  <p className="text-[13px] text-slate-700 mt-1.5">{t("overview.periodLabel", { range: rangeLabel })}</p>
                ) : null}
              </div>
            </div>

            <div className="xl:max-w-[760px] w-full xl:w-auto">
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                  <span>{t("overview.filterTitle")}</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {RANGE_PRESETS.map((preset) => {
                    const isActive = rangePreset === preset.id;
                    if (preset.id === "custom_month") {
                      return (
                        <div key={preset.id} ref={monthMenuRef} className="relative">
                          <button
                            type="button"
                            onClick={() => {
                              setRangePreset("custom_month");
                              setIsMonthMenuOpen((current) => (rangePreset === "custom_month" ? !current : true));
                            }}
                            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[12px] font-semibold border transition-colors ${
                              isActive
                                ? "bg-primary text-white border-primary shadow-sm"
                                : "bg-white text-slate-700 border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                            }`}
                          >
                            <span>{t(preset.labelKey)}</span>
                            <span className="material-icons text-sm">expand_more</span>
                          </button>
                          {isActive && isMonthMenuOpen ? (
                            <div className="absolute top-full left-0 mt-1 w-[180px] max-h-64 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg z-20 p-1">
                              {monthOptions.map((option) => {
                                const selected = option.value === selectedMonth;
                                return (
                                  <button
                                    key={option.value}
                                    type="button"
                                    onClick={() => {
                                      setSelectedMonth(option.value);
                                      setIsMonthMenuOpen(false);
                                    }}
                                    className={`w-full text-left px-3 py-2 rounded-lg text-[12px] ${
                                      selected
                                        ? "bg-primary/10 text-primary font-semibold"
                                        : "text-slate-700 hover:bg-slate-50"
                                    }`}
                                  >
                                    {option.label}
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}
                        </div>
                      );
                    }
                    if (preset.id === "year") {
                      return (
                        <div key={preset.id} ref={yearMenuRef} className="relative">
                          <button
                            type="button"
                            onClick={() => {
                              setRangePreset("year");
                              setIsYearMenuOpen((current) => (rangePreset === "year" ? !current : true));
                            }}
                            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[12px] font-semibold border transition-colors ${
                              isActive
                                ? "bg-primary text-white border-primary shadow-sm"
                                : "bg-white text-slate-700 border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                            }`}
                          >
                            <span>{t(preset.labelKey)}</span>
                            <span className="material-icons text-sm">expand_more</span>
                          </button>
                          {isActive && isYearMenuOpen ? (
                            <div className="absolute top-full left-0 mt-1 w-[120px] max-h-64 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg z-20 p-1">
                              {yearOptions.map((option) => {
                                const selected = option.value === selectedYear;
                                return (
                                  <button
                                    key={option.value}
                                    type="button"
                                    onClick={() => {
                                      setSelectedYear(option.value);
                                      setIsYearMenuOpen(false);
                                    }}
                                    className={`w-full text-left px-3 py-2 rounded-lg text-[12px] ${
                                      selected
                                        ? "bg-primary/10 text-primary font-semibold"
                                        : "text-slate-700 hover:bg-slate-50"
                                    }`}
                                  >
                                    {option.label}
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}
                        </div>
                      );
                    }
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => setRangePreset(preset.id)}
                        className={`px-2.5 py-1.5 rounded-lg text-[12px] font-semibold border transition-colors ${
                          isActive
                            ? "bg-primary text-white border-primary shadow-sm"
                            : "bg-white text-slate-700 border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                        }`}
                      >
                        {t(preset.labelKey)}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </section>

        {error ? (
          <div className="bg-danger/10 border border-danger/20 text-danger rounded-lg p-3 text-sm">{error}</div>
        ) : null}

        <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
          <MetricCard
            title={t("overview.totalOrders")}
            value={summary.total ?? 0}
            detail={rangeLabel || t("overview.totalOrdersSubtitle")}
            icon="inventory_2"
            accentClass="border-l-4 border-l-primary"
            iconClass="text-primary bg-primary/10"
          />
          {STATUS_CONFIG.map((status) => {
            const entry = summary?.statuses?.[status.key] || { count: 0, rate: 0 };
            return (
              <MetricCard
                key={status.key}
                title={t(status.labelKey)}
                value={formatPercent(entry.rate)}
                detail={t("overview.statusCount", { count: entry.count ?? 0 })}
                icon={status.icon}
                accentClass={status.accentClass}
                iconClass={status.iconClass}
              />
            );
          })}
        </section>

        <section className="bg-surface-light rounded-2xl border border-slate-200 shadow-sm p-4 space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-lg font-bold text-slate-900">
                {bucketGranularity === "month" ? t("overview.monthlyStatusBreakdown") : t("overview.dailyStatusBreakdown")}
              </h2>
              <p className="text-[13px] text-slate-500 mt-1">{chartRangeLabel || rangeLabel || t("overview.chartSubtitle")}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {STATUS_CONFIG.map((status) => (
                <span
                  key={status.key}
                  className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700"
                >
                  <span className={`h-2.5 w-2.5 rounded-full ${status.dotClass}`} />
                  <span>{t(status.labelKey)}</span>
                </span>
              ))}
            </div>
          </div>

          {hasActivity ? (
            <div className="space-y-4">
              <StatusBreakdownChart
                data={statusChartData}
                locale={locale}
                t={t}
                selectedDay={effectiveSelectedDay}
                onSelectDay={(day) => setSelectedDay((current) => (current?.date === day.date ? null : day))}
              />
            </div>
          ) : (
            <div className="min-h-[220px] flex items-center justify-center text-sm text-slate-400 border border-dashed border-slate-200 rounded-2xl">
              {t("overview.noActivity")}
            </div>
          )}
        </section>

        {clientHourDays.length ? (
          <section className="bg-surface-light rounded-2xl border border-slate-200 shadow-sm p-4 space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-lg font-bold text-slate-900">{t("overview.orderClientTimeline")}</h2>
                <p className="text-[13px] text-slate-500 mt-1">
                  {isLongRangeTimeline
                    ? t("overview.orderClientTimelineLongRangeSubtitle")
                    : t("overview.orderClientTimelineSubtitle")}
                </p>
              </div>
              {selectedClientDay && !isLongRangeTimeline ? (
                <div className="text-[12px] font-medium text-slate-600">
                  {selectedClientDay.label} · {t("overview.hourlyOrders", { count: selectedClientDay.total ?? 0 }, `${selectedClientDay.total ?? 0} orders`)}
                </div>
              ) : null}
            </div>

            <OrderClientTimelineChart
              timeline={clientHourData}
              view={timelineView}
              locale={locale}
              t={t}
            />
          </section>
        ) : null}

        {isSuperadmin && xmlActivity ? (
          <section className="bg-surface-light rounded-2xl border border-slate-200 shadow-sm p-4 space-y-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="material-icons text-violet-600">shield</span>
                <h2 className="text-lg font-bold text-slate-900">XML Activity</h2>
                <span className="text-[11px] uppercase tracking-widest text-violet-600 bg-violet-50 border border-violet-200 px-2 py-0.5 rounded-full">Superadmin</span>
              </div>
              <p className="text-[13px] text-slate-500 mt-1">{rangeLabel}</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <MetricCard
                title="XMLs Generated"
                value={xmlActivity.summary.generated_files}
                detail={`from ${xmlActivity.summary.generated_orders} orders (OrderInfo + ArticleInfo)`}
                icon="description"
                accentClass="border-l-4 border-l-violet-500"
                iconClass="text-violet-600 bg-violet-50"
              />
              <MetricCard
                title="XMLs Regenerated"
                value={xmlActivity.summary.regenerated_files}
                detail={`from ${xmlActivity.summary.regenerated_events} regeneration events`}
                icon="refresh"
                accentClass="border-l-4 border-l-amber-500"
                iconClass="text-amber-600 bg-amber-50"
              />
            </div>

            {xmlActivity.by_day.some((d) => d.generated_orders > 0 || d.regenerated_events > 0) ? (
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-slate-500 text-[12px] uppercase tracking-wide">
                    <tr>
                      <th className="px-4 py-2 text-left">Date</th>
                      <th className="px-4 py-2 text-right">Generated (files)</th>
                      <th className="px-4 py-2 text-right">→ OrderInfo XML</th>
                      <th className="px-4 py-2 text-right">→ ArticleInfo XML</th>
                      <th className="px-4 py-2 text-right">Regenerated (files)</th>
                      <th className="px-4 py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {xmlActivity.by_day
                      .filter((d) => d.generated_orders > 0 || d.regenerated_events > 0)
                      .map((d) => (
                        <tr key={d.date} className="border-t border-slate-100 hover:bg-slate-50">
                          <td className="px-4 py-2 font-medium text-slate-700">{d.label}</td>
                          <td className="px-4 py-2 text-right">{d.generated_files}</td>
                          <td className="px-4 py-2 text-right text-slate-500">{d.generated_orders}</td>
                          <td className="px-4 py-2 text-right text-slate-500">{d.generated_orders}</td>
                          <td className="px-4 py-2 text-right">{d.regenerated_files}</td>
                          <td className="px-4 py-2 text-right font-semibold">{d.generated_files + d.regenerated_files}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="min-h-[80px] flex items-center justify-center text-sm text-slate-400 border border-dashed border-slate-200 rounded-2xl">
                No XML activity in this period
              </div>
            )}
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
