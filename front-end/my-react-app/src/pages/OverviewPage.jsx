
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, formatPercent } from "../utils/format";

function MetricCard({ title, value, subtitle, icon, accentClass }) {
  return (
    <div className={`bg-surface-light p-4 rounded-xl border shadow-sm ${accentClass}`}>
      <div className="flex justify-between items-start mb-2">
        <span className="text-slate-500 text-sm font-medium">{title}</span>
        <span className="material-icons text-primary bg-primary/10 p-1 rounded text-lg">{icon}</span>
      </div>
      <div>
        <div className="text-2xl font-bold">{value}</div>
        <div className="text-xs text-slate-500 mt-1">{subtitle}</div>
      </div>
    </div>
  );
}

function QueueCard({ title, value, subtitle }) {
  return (
    <div className="bg-slate-50 p-4 rounded-xl border border-primary/20 flex flex-col items-center justify-center text-center relative overflow-hidden group">
      <div className="absolute inset-0 bg-primary/5 opacity-0 group-hover:opacity-100 transition-opacity" />
      <span className="text-xs font-semibold uppercase tracking-wider text-primary mb-1">{title}</span>
      <div className="text-3xl font-bold text-slate-800">{value}</div>
      <span className="text-[10px] text-slate-400 mt-1">{subtitle}</span>
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
      setError(requestError.message || "Failed to load overview data.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadOverview();
    const intervalId = setInterval(loadOverview, 15000);
    return () => clearInterval(intervalId);
  }, [loadOverview]);

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    const query = searchInput.trim();
    navigate(`/orders${query ? `?q=${encodeURIComponent(query)}` : ""}`);
  };

  const statusByDay = overview?.status_by_day || [];
  const maxDayTotal = Math.max(...statusByDay.map((bucket) => Number(bucket.total || 0)), 1);
  const lineSeries = buildLineSeries(overview?.processed_by_hour || []);

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
                  <h1 className="text-lg font-bold tracking-tight">Operations Control</h1>
                  <p className="text-xs text-slate-500">Order Extraction Dashboard</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <form onSubmit={handleSearchSubmit} className="relative hidden md:block w-64">
                  <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400">
                    <span className="material-icons text-lg">search</span>
                  </span>
                  <input
                    className="w-full pl-10 pr-4 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                    placeholder="Search ticket #..."
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                  />
                </form>
                <Link to="/orders" className="text-sm px-3 py-1.5 rounded-lg border border-slate-200 hover:border-primary hover:text-primary transition-colors">
                  Orders
                </Link>
                <button
                  type="button"
                  onClick={logout}
                  className="text-sm px-3 py-1.5 rounded-lg bg-slate-900 text-white hover:bg-slate-700 transition-colors lg:hidden"
                >
                  Logout
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
                  title="Total Orders (Today)"
                  value={overview?.today?.total ?? 0}
                  subtitle={`Last 24h: ${overview?.last_24h?.total ?? 0}`}
                  icon="inventory_2"
                  accentClass=""
                />
                <MetricCard
                  title="OK Rate"
                  value={formatPercent(overview?.today?.ok_rate)}
                  subtitle={`OK: ${overview?.today?.ok ?? 0}`}
                  icon="check_circle"
                  accentClass="border-l-4 border-l-success"
                />
                <MetricCard
                  title="Partial Rate"
                  value={formatPercent(overview?.today?.partial_rate)}
                  subtitle={`Partial: ${overview?.today?.partial ?? 0}`}
                  icon="warning"
                  accentClass="border-l-4 border-l-warning"
                />
                <MetricCard
                  title="Failed Rate"
                  value={formatPercent(overview?.today?.failed_rate)}
                  subtitle={`Failed: ${overview?.today?.failed ?? 0}`}
                  icon="error"
                  accentClass="border-l-4 border-l-danger"
                />
              </div>

              <div className="col-span-1 md:col-span-2 lg:col-span-4 xl:col-span-3 grid grid-cols-3 gap-4">
                <QueueCard title="Reply Needed" value={overview?.queue_counts?.reply_needed ?? 0} subtitle="Needs customer response" />
                <QueueCard title="Review" value={overview?.queue_counts?.human_review_needed ?? 0} subtitle="Manual verification" />
                <QueueCard title="Post Case" value={overview?.queue_counts?.post_case ?? 0} subtitle="High priority" />
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
              <div className="lg:col-span-2 bg-surface-light rounded-xl border border-slate-200 p-4 shadow-sm flex flex-col h-[260px]">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="font-bold text-lg">Extraction Performance</h3>
                    <p className="text-sm text-slate-500">Last 7 Days by Status</p>
                  </div>
                  <div className="flex gap-2 text-xs font-medium">
                    <div className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-success" />OK</div>
                    <div className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-warning" />Partial</div>
                    <div className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-danger" />Failed</div>
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
                    <h3 className="font-bold text-lg">Queue Velocity</h3>
                    <p className="text-sm text-slate-500">Processed outputs (24h)</p>
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
                  <span>24h Ago</span>
                  <span>Now</span>
                </div>
              </div>
            </div>

            <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
              <div className="p-6 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <h3 className="font-bold text-lg">Latest Orders</h3>
                  <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs font-medium">Live Feed</span>
                </div>
                <button
                  type="button"
                  onClick={loadOverview}
                  className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-white bg-primary rounded-lg hover:bg-primary-dark transition-colors"
                >
                  <span className="material-icons text-sm">refresh</span>
                  Refresh
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-slate-500 font-medium border-b border-slate-200">
                    <tr>
                      <th className="px-6 py-4 whitespace-nowrap">Received At</th>
                      <th className="px-6 py-4 whitespace-nowrap">Status</th>
                      <th className="px-6 py-4 whitespace-nowrap">Ticket / KOM</th>
                      <th className="px-6 py-4 whitespace-nowrap">Client / Store</th>
                      <th className="px-6 py-4 whitespace-nowrap">Items</th>
                      <th className="px-6 py-4 whitespace-nowrap">Flags</th>
                      <th className="px-6 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {(overview?.latest_orders || []).map((order) => (
                      <tr key={order.id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-6 py-4 whitespace-nowrap text-slate-600">{formatDateTime(order.effective_received_at)}</td>
                        <td className="px-6 py-4 whitespace-nowrap"><StatusBadge status={order.status} /></td>
                        <td className="px-6 py-4 whitespace-nowrap font-medium text-primary">
                          {order.ticket_number || order.kom_nr || order.id}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="font-medium text-slate-800">{order.kom_name || "-"}</div>
                          <div className="text-xs text-slate-500">{order.store_name || "-"}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-slate-600">{order.item_count}</td>
                        <td className="px-6 py-4 whitespace-nowrap text-xs text-slate-500">
                          {order.reply_needed || order.human_review_needed || order.post_case
                            ? [
                                order.reply_needed ? "Reply" : "",
                                order.human_review_needed ? "Review" : "",
                                order.post_case ? "Post" : "",
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
                            Open
                          </Link>
                        </td>
                      </tr>
                    ))}
                    {!loading && (overview?.latest_orders || []).length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-6 py-8 text-center text-slate-500">No orders found.</td>
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
