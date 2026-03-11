import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchJson, withQuery } from "../api/http";
import { AppShell } from "../components/AppShell";
import { OrderClientTimelineChart } from "../components/OrderClientTimelineChart";

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
  const navigate = useNavigate();
  const { t, locale } = useI18n();
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [selectedDayIndex, setSelectedDayIndex] = useState(null);
  const [selectedClientDayIndex, setSelectedClientDayIndex] = useState(null);
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

  useEffect(() => {
    setSelectedDayIndex(null);
    setSelectedClientDayIndex(null);
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
  const dayTotals = statusByDay.map((bucket) => getBucketTotals(bucket));
  const maxDayTotal = Math.max(...dayTotals.map((bucket) => bucket.total), 0);
  const hasActivity = dayTotals.some((bucket) => bucket.total > 0);
  const latestActiveIndex = (() => {
    for (let index = dayTotals.length - 1; index >= 0; index -= 1) {
      if (dayTotals[index]?.total > 0) {
        return index;
      }
    }
    return null;
  })();
  const safeSelectedIndex =
    selectedDayIndex !== null && selectedDayIndex < statusByDay.length
      ? selectedDayIndex
      : null;
  const effectiveSelectedIndex = safeSelectedIndex ?? latestActiveIndex;
  const selectedBucket =
    effectiveSelectedIndex !== null ? statusByDay[effectiveSelectedIndex] : null;
  const selectedTotals =
    effectiveSelectedIndex !== null ? dayTotals[effectiveSelectedIndex] : null;
  const bucketGranularity = overview?.range?.bucket_granularity || "day";
  const clientHourData = overview?.orders_by_client_hour || { clients: [], days: [] };
  const clientHourDays = clientHourData.days || [];
  const latestClientDayIndex = (() => {
    for (let index = clientHourDays.length - 1; index >= 0; index -= 1) {
      if ((clientHourDays[index]?.total || 0) > 0) {
        return index;
      }
    }
    return clientHourDays.length ? 0 : null;
  })();
  const safeClientDayIndex =
    selectedClientDayIndex !== null && selectedClientDayIndex < clientHourDays.length
      ? selectedClientDayIndex
      : null;
  const effectiveClientDayIndex = safeClientDayIndex ?? latestClientDayIndex;
  const selectedClientDay =
    effectiveClientDayIndex !== null ? clientHourDays[effectiveClientDayIndex] : null;
  const isMonthDayView = bucketGranularity === "day" && (rangePreset === "month" || rangePreset === "custom_month");
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
  const fitAllDaysInView = bucketGranularity === "day" && statusByDay.length >= 20;
  const chartMinWidth = Math.max(statusByDay.length * 84, 420);
  const showAllBucketLabels = bucketGranularity === "month" || fitAllDaysInView || isMonthDayView;
  const labelStride = fitAllDaysInView
    ? 1
    : Math.max(1, Math.ceil(statusByDay.length / 10));
  const timelineView =
    rangePreset === "week"
      ? "weekly"
      : rangePreset === "month" || rangePreset === "custom_month"
        ? "monthly"
        : "daily";
  const monthOptions = buildMonthOptions(locale);
  const yearOptions = buildYearOptions();

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    const query = searchInput.trim();
    if (!query) {
      navigate("/orders");
      return;
    }
    navigate(`/orders?q=${encodeURIComponent(query)}`);
  };

  return (
    <AppShell
      active="overview"
      headerLeft={(
        <form onSubmit={handleSearchSubmit} className="relative hidden md:block w-full max-w-md">
          <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400">
            <span className="material-icons text-lg">search</span>
          </span>
          <input
            className="w-full pl-10 pr-4 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            placeholder={t("overview.searchPlaceholder")}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </form>
      )}
    >
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
                {bucketGranularity === "month" ? t("overview.monthlyStatusBreakdown", null, "Monthly Status Breakdown") : t("overview.dailyStatusBreakdown")}
              </h2>
              <p className="text-[13px] text-slate-500 mt-1">{chartRangeLabel || rangeLabel || t("overview.chartSubtitle")}</p>
            </div>
            <div className="flex flex-wrap gap-3 text-[12px] font-medium">
              {STATUS_CONFIG.map((status) => (
                <div key={status.key} className="flex items-center gap-2">
                  <span className={`w-3 h-3 rounded-full ${status.dotClass}`} />
                  <span className="text-slate-600">{t(status.labelKey)}</span>
                </div>
              ))}
            </div>
          </div>

          {hasActivity ? (
            <div className={fitAllDaysInView ? "overflow-hidden" : "overflow-x-auto pb-1"}>
              <div className="space-y-4" style={fitAllDaysInView ? undefined : { minWidth: `${chartMinWidth}px` }}>
                <div className={`h-[250px] flex items-end ${fitAllDaysInView ? "justify-between gap-2 px-1" : "justify-center gap-4 px-4"}`}>
                  {statusByDay.map((bucket, index) => {
                    const totals = dayTotals[index];
                    const scale = maxDayTotal > 0 ? maxDayTotal : 1;
                    const tooltip = [
                      `${t("common.total")}: ${totals.total}`,
                      `${t("status.ok")}: ${totals.ok}`,
                      `${t("status.waiting_for_reply")}: ${totals.waitingForReply}`,
                      `${t("status.human_in_the_loop")}: ${totals.humanInTheLoop}`,
                      `${t("status.post")}: ${totals.post}`,
                      `${t("status.unknown")}: ${totals.unknown}`,
                      `${t("status.failed")}: ${totals.failed}`,
                      `${t("status.updated_after_reply")}: ${totals.updatedAfterReply}`,
                    ].join("\n");
                    const showLabel =
                      showAllBucketLabels ||
                      index === 0 ||
                      index === statusByDay.length - 1 ||
                      index % labelStride === 0;

                    return (
                      <button
                        key={bucket.date}
                        type="button"
                        title={tooltip}
                        onClick={() => setSelectedDayIndex((current) => (current === index ? null : index))}
                        className={`${fitAllDaysInView ? "flex-1 min-w-0 max-w-[28px]" : "w-[72px] shrink-0"} h-full flex flex-col items-center gap-2 focus:outline-none`}
                      >
                        <div
                          className={`w-full rounded-2xl overflow-hidden border transition-all ${
                            effectiveSelectedIndex === index
                              ? "border-primary shadow-sm"
                              : "border-slate-200"
                          }`}
                        >
                          <div className="h-[190px] flex flex-col justify-end bg-slate-50">
                            {STATUS_CONFIG.slice().reverse().map((status) => {
                              const amount = toNumber(bucket?.[status.key]);
                              const height = `${(amount / scale) * 100}%`;
                              return (
                                <div
                                  key={status.key}
                                  className={`w-full ${status.dotClass}`}
                                  style={{ height }}
                                />
                              );
                            })}
                          </div>
                        </div>
                        <div className="text-center">
                          {!fitAllDaysInView ? (
                            <div className="text-[11px] font-semibold text-slate-700">{totals.total}</div>
                          ) : null}
                          <span className={`text-[11px] ${showLabel ? "text-slate-500" : "text-transparent"}`}>
                            {bucket.label}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {selectedTotals ? (
                  <div className="bg-slate-50 border border-slate-200 rounded-2xl p-3 flex flex-wrap items-center gap-3 text-[13px]">
                    <div className="flex items-center gap-2 text-slate-700 font-semibold">
                      <span>{t("common.selectedDay")}:</span>
                      <span>{selectedLabel}</span>
                    </div>
                    <div className="flex items-center gap-2 text-slate-700 font-semibold">
                      <span>{t("common.total")}:</span>
                      <span>{selectedTotals.total}</span>
                    </div>
                    {STATUS_CONFIG.map((status) => {
                      const totalsKey =
                        status.key === "waiting_for_reply"
                          ? "waitingForReply"
                          : status.key === "human_in_the_loop"
                            ? "humanInTheLoop"
                            : status.key === "updated_after_reply"
                              ? "updatedAfterReply"
                              : status.key;
                      return (
                        <div key={status.key} className="flex items-center gap-2 text-slate-600">
                          <span className={`w-2.5 h-2.5 rounded-full ${status.dotClass}`} />
                          <span>{t(status.labelKey)} {selectedTotals[totalsKey]}</span>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="min-h-[220px] flex items-center justify-center text-sm text-slate-400 border border-dashed border-slate-200 rounded-2xl">
              {t("overview.noActivity")}
            </div>
          )}
        </section>

        {bucketGranularity === "day" ? (
          <section className="bg-surface-light rounded-2xl border border-slate-200 shadow-sm p-4 space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-lg font-bold text-slate-900">{t("overview.orderClientTimeline", null, "Order Client Timeline")}</h2>
                <p className="text-[13px] text-slate-500 mt-1">{t("overview.orderClientTimelineSubtitle", null, "Pick a day to inspect hourly order totals and the client split.")}</p>
              </div>
              {selectedClientDay ? (
                <div className="text-[12px] font-medium text-slate-600">
                  {selectedClientDay.label} · {t("overview.hourlyOrders", { count: selectedClientDay.total ?? 0 }, `${selectedClientDay.total ?? 0} orders`)}
                </div>
              ) : null}
            </div>

            {clientHourDays.length ? (
              <>
                <OrderClientTimelineChart
                  timeline={clientHourData}
                  view={timelineView}
                  locale={locale}
                />
                <div className="hidden flex-wrap gap-2">
                  {clientHourDays.map((day, index) => {
                    const isActive = effectiveClientDayIndex === index;
                    return (
                      <button
                        key={day.date}
                        type="button"
                        onClick={() => setSelectedClientDayIndex(index)}
                        className={`rounded-xl border px-3 py-2 text-left transition-colors ${
                          isActive
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                        }`}
                      >
                        <div className="text-[12px] font-semibold">{day.label}</div>
                        <div className="text-[11px] opacity-80">{day.total} {t("common.total")}</div>
                      </button>
                    );
                  })}
                </div>
              </>
            ) : (
              <div className="min-h-[120px] flex items-center justify-center text-sm text-slate-400 border border-dashed border-slate-200 rounded-2xl">
                {t("overview.noHourlyClientActivity", null, "No hourly client activity for the selected day.")}
              </div>
            )}
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
