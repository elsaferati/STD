import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/StatusBadge";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { useI18n } from "../i18n/I18nContext";
import { formatDateTime, formatPercent } from "../utils/format";

function MetricCard({ title, value, subtitle, icon, accentClass = "" }) {
  return (
    <div className={`bg-surface-light p-4 rounded-xl border border-slate-200 shadow-sm ${accentClass}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm text-slate-500 font-medium">{title}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{value}</p>
          <p className="text-xs text-slate-500 mt-1">{subtitle}</p>
        </div>
        <span className="material-icons text-primary bg-primary/10 p-1.5 rounded-lg text-lg">{icon}</span>
      </div>
    </div>
  );
}

function QueueCard({ title, value, subtitle }) {
  return (
    <div className="bg-surface-light p-4 rounded-xl border border-slate-200 shadow-sm">
      <p className="text-sm text-slate-500 font-medium">{title}</p>
      <p className="text-2xl font-bold text-slate-900 mt-2">{value}</p>
      <p className="text-xs text-slate-500 mt-1">{subtitle}</p>
    </div>
  );
}

function KpiCard({ title, value, subtitle, icon }) {
  return (
    <div className="bg-surface-light p-4 rounded-xl border border-slate-200 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm text-slate-500 font-medium">{title}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{value}</p>
          <p className="text-xs text-slate-500 mt-1">{subtitle}</p>
        </div>
        <span className="material-icons text-primary bg-primary/10 p-1.5 rounded-lg text-lg">{icon}</span>
      </div>
    </div>
  );
}

function buildLineSeries(points) {
  if (!points.length) {
    return "";
  }

  const maxValue = Math.max(...points.map((point) => Number(point.processed || 0)), 1);
  return points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 100;
      const y = 100 - (Number(point.processed || 0) / maxValue) * 100;
      return `${x},${y}`;
    })
    .join(" ");
}

export function OverviewPage() {
  const { token, logout } = useAuth();
  const navigate = useNavigate();
  const { t, lang } = useI18n();
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchInput, setSearchInput] = useState("");

  const loadOverview = useCallback(async () => {
    try {
      const payload = await fetchJson("/api/overview", { token });
      setOverview(payload);
      setError("");
    } catch (requestError) {
      setError(requestError.message || t("overview.loadError"));
    } finally {
      setLoading(false);
    }
  }, [token, t]);

  useEffect(() => {
    loadOverview();
    const intervalId = setInterval(loadOverview, 15000);
    return () => clearInterval(intervalId);
  }, [loadOverview]);

  const lineSeries = buildLineSeries(overview?.processed_by_hour || []);
  const statusByDay = overview?.status_by_day || [];
  const maxDayTotal = Math.max(...statusByDay.map((bucket) => Number(bucket.total || 0)), 1);

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
      showPulse
      pulseValue={overview?.queue_counts?.reply_needed ?? 0}
      pulseMax={overview?.today?.total ?? 1}
    >
          <header className="bg-surface-light/90 backdrop-blur border-b border-slate-200 sticky top-0 z-30">
            <div className="max-w-[1600px] mx-auto px-6 h-16 flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 bg-primary/20 rounded-lg flex items-center justify-center text-primary font-bold text-xl">
                  S
                </div>
                <div>
                  <h1 className="text-lg font-bold tracking-tight">{t("overview.title")}</h1>
                  <p className="text-xs text-slate-500">{t("overview.subtitle")}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <form onSubmit={handleSearchSubmit} className="relative hidden md:block w-64">
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
                <LanguageSwitcher compact className="hidden md:flex" />
                <Link to="/orders" className="text-sm px-3 py-1.5 rounded-lg border border-slate-200 hover:border-primary hover:text-primary transition-colors">
                  {t("common.orders")}
                </Link>
                <button
                  type="button"
                  onClick={logout}
                  className="text-sm px-3 py-1.5 rounded-lg bg-slate-900 text-white hover:bg-slate-700 transition-colors lg:hidden"
                >
                  {t("common.logout")}
                </button>
              </div>
            </div>
          </header>

          <main className="flex-1 max-w-[1600px] mx-auto w-full p-6 space-y-6">
            {error ? (
              <div className="bg-danger/10 border border-danger/20 text-danger rounded-lg p-3 text-sm">{error}</div>
            ) : null}

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 gap-4">
              <div className="col-span-1 md:col-span-2 lg:col-span-4 grid grid-cols-2 lg:grid-cols-4 gap-4">
                <MetricCard
                  title={t("overview.totalOrdersToday")}
                  value={overview?.today?.total ?? 0}
                  subtitle={t("overview.last24h", { count: overview?.last_24h?.total ?? 0 })}
                  icon="inventory_2"
                  accentClass="border-l-4 border-l-primary"
                />
                <MetricCard
                  title={t("overview.okRate")}
                  value={formatPercent(overview?.today?.ok_rate)}
                  subtitle={t("overview.okCount", { count: overview?.today?.ok ?? 0 })}
                  icon="check_circle"
                  accentClass="border-l-4 border-l-success"
                />
                <MetricCard
                  title={t("overview.partialRate")}
                  value={formatPercent(overview?.today?.partial_rate)}
                  subtitle={t("overview.partialCount", { count: overview?.today?.partial ?? 0 })}
                  icon="warning"
                  accentClass="border-l-4 border-l-warning"
                />
                <MetricCard
                  title={t("overview.failedRate")}
                  value={formatPercent(overview?.today?.failed_rate)}
                  subtitle={t("overview.failedCount", { count: overview?.today?.failed ?? 0 })}
                  icon="error"
                  accentClass="border-l-4 border-l-danger"
                />
              </div>

              <div className="col-span-1 md:col-span-2 lg:col-span-4 xl:col-span-3 grid grid-cols-3 gap-4">
                <QueueCard
                  title={t("overview.queueReplyNeeded")}
                  value={overview?.queue_counts?.reply_needed ?? 0}
                  subtitle={t("overview.queueReplySubtitle")}
                />
                <QueueCard
                  title={t("overview.queueReview")}
                  value={overview?.queue_counts?.human_review_needed ?? 0}
                  subtitle={t("overview.queueReviewSubtitle")}
                />
                <QueueCard
                  title={t("overview.queuePostCase")}
                  value={overview?.queue_counts?.post_case ?? 0}
                  subtitle={t("overview.queuePostCaseSubtitle")}
                />
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
              <div className="lg:col-span-2 bg-surface-light rounded-xl border border-slate-200 p-4 shadow-sm flex flex-col h-[260px]">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="font-bold text-lg">{t("overview.extractionPerformance")}</h3>
                    <p className="text-sm text-slate-500">{t("overview.last7Days")}</p>
                  </div>
                  <div className="flex gap-2 text-xs font-medium">
                    <div className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-success" />{t("status.ok")}</div>
                    <div className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-warning" />{t("status.partial")}</div>
                    <div className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-danger" />{t("status.failed")}</div>
                  </div>
                </div>
                <div className="w-full flex-1 min-h-[120px] flex items-end justify-between gap-2 px-2">
                  {statusByDay.map((bucket) => {
                    const okHeight = `${(Number(bucket.ok || 0) / maxDayTotal) * 100}%`;
                    const partialHeight = `${(Number(bucket.partial || 0) / maxDayTotal) * 100}%`;
                    const failedHeight = `${(Number(bucket.failed || 0) / maxDayTotal) * 100}%`;
                    return (
                      <div key={bucket.date} className="flex-1 flex flex-col items-center gap-2">
                        <div className="w-full max-w-[40px] flex flex-col h-full justify-end rounded-t-lg overflow-hidden">
                          <div className="bg-danger w-full" style={{ height: failedHeight }} />
                          <div className="bg-warning w-full" style={{ height: partialHeight }} />
                          <div className="bg-success w-full" style={{ height: okHeight }} />
                        </div>
                        <span className="text-xs text-slate-400">{bucket.label}</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="bg-surface-light rounded-xl border border-slate-200 p-4 shadow-sm flex flex-col h-[260px]">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="font-bold text-lg">{t("overview.queueVelocity")}</h3>
                    <p className="text-sm text-slate-500">{t("overview.processed24h")}</p>
                  </div>
                  <span className="material-icons text-primary/50">ssid_chart</span>
                </div>
                <div className="relative flex-1 w-full min-h-[120px] rounded-lg border border-slate-100 p-2">
                  <svg viewBox="0 0 100 100" className="w-full h-full" preserveAspectRatio="none">
                    <polyline
                      fill="none"
                      stroke="#13daec"
                      strokeWidth="2"
                      points={lineSeries}
                    />
                  </svg>
                </div>
                <div className="flex justify-between text-xs text-slate-400 mt-2">
                  <span>{t("overview.hoursAgo")}</span>
                  <span>{t("overview.now")}</span>
                </div>
              </div>
            </div>

            <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
              <div className="p-6 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <h3 className="font-bold text-lg">{t("overview.latestOrders")}</h3>
                  <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs font-medium">{t("overview.liveFeed")}</span>
                </div>
                <button
                  type="button"
                  onClick={loadOverview}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-white bg-primary rounded-lg hover:bg-primary-dark transition-colors"
                >
                  <span className="material-icons text-sm">refresh</span>
                  {t("overview.refresh")}
                </button>
              </div>

              <div className="overflow-auto max-h-[80vh]">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-slate-500 font-medium border-b border-slate-200">
                    <tr>
                      <th className="px-6 py-4 whitespace-nowrap sticky top-0 z-10 bg-slate-50">Nr</th>
                      <th className="px-6 py-4 whitespace-nowrap sticky top-0 z-10 bg-slate-50">{t("common.receivedAt")}</th>
                      <th className="px-6 py-4 whitespace-nowrap sticky top-0 z-10 bg-slate-50">{t("common.status")}</th>
                      <th className="px-6 py-4 whitespace-nowrap sticky top-0 z-10 bg-slate-50 w-40 max-w-[160px]">{t("common.ticketKom")}</th>
                      <th className="px-6 py-4 whitespace-nowrap sticky top-0 z-10 bg-slate-50">{t("common.clientStore")}</th>
                      <th className="px-6 py-4 whitespace-nowrap sticky top-0 z-10 bg-slate-50">{t("common.items")}</th>
                      <th className="px-6 py-4 whitespace-nowrap sticky top-0 z-10 bg-slate-50">{t("common.flags")}</th>
                      <th className="px-6 py-4 text-right sticky top-0 z-10 bg-slate-50">{t("common.actions")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {(overview?.latest_orders || []).map((order, index) => (
                      <tr key={order.id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-6 py-4 whitespace-nowrap text-slate-500">{index + 1}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-slate-600">
                          {formatDateTime(order.effective_received_at, lang)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap"><StatusBadge status={order.status} /></td>
                        <td className="px-6 py-4 font-medium text-primary w-40 max-w-[160px]">
                          <span className="block truncate">
                            {order.ticket_number || order.kom_nr || order.id}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="font-medium text-slate-800">{order.kom_name || "-"}</div>
                          <div className="text-xs text-slate-500">{order.store_name || "-"}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-slate-600">{order.item_count}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-xs text-slate-500">
                          {order.reply_needed || order.human_review_needed || order.post_case
                            ? [
                                order.reply_needed ? t("flags.reply") : "",
                                order.human_review_needed ? t("flags.review") : "",
                                order.post_case ? t("flags.post") : "",
                              ]
                                .filter(Boolean)
                                .join(" | ")
                            : "-"}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Link
                            to={`/orders/${order.id}`}
                            className="text-primary hover:text-primary-dark transition-colors bg-primary/10 px-2 py-1 rounded text-xs font-bold uppercase"
                          >
                            {t("common.open")}
                          </Link>
                        </td>
                      </tr>
                    ))}
                    {!loading && (overview?.latest_orders || []).length === 0 ? (
                      <tr>
                        <td colSpan={8} className="px-6 py-8 text-center text-slate-500">{t("overview.noOrders")}</td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>
          </main>
    </AppShell>
  );
}
