import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, formatPercent } from "../utils/format";

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
  const { token } = useAuth();
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

  const queueCounts = overview?.queue_counts || {};
  const replyNeeded = Number(queueCounts.reply_needed || 0);
  const reviewNeeded = Number(queueCounts.human_review_needed || 0);
  const postCase = Number(queueCounts.post_case || 0);
  const needsAttention = replyNeeded + reviewNeeded + postCase;
  const needsAttentionSubtitle = `Reply ${replyNeeded} · Review ${reviewNeeded} · Post ${postCase}`;
  const lineSeries = buildLineSeries(overview?.processed_by_hour || []);

  return (
    <AppShell>
      <div className="space-y-6">
        {error ? (
          <div className="bg-danger/10 border border-danger/20 text-danger rounded-lg p-3 text-sm">{error}</div>
        ) : null}

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4">
          <KpiCard
            title="Today Orders"
            value={overview?.today?.total ?? 0}
            subtitle="Orders received today"
            icon="inventory_2"
          />
          <KpiCard
            title="OK Rate"
            value={formatPercent(overview?.today?.ok_rate)}
            subtitle={`OK ${overview?.today?.ok ?? 0}`}
            icon="check_circle"
          />
          <KpiCard
            title="Needs Attention"
            value={needsAttention}
            subtitle={needsAttentionSubtitle}
            icon="priority_high"
          />
          <KpiCard
            title="Last 24h Orders"
            value={overview?.last_24h?.total ?? 0}
            subtitle="Processed in the last 24 hours"
            icon="schedule"
          />

          <div className="bg-surface-light rounded-xl border border-slate-200 p-4 shadow-sm">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">24h Trend</h3>
                <p className="text-xs text-slate-500">Processed by hour</p>
              </div>
              <span className="material-icons text-primary/60">show_chart</span>
            </div>
            <div className="relative h-24 w-full rounded border border-slate-100 p-2">
              <svg viewBox="0 0 100 100" className="w-full h-full" preserveAspectRatio="none">
                <polyline
                  fill="none"
                  stroke="#13daec"
                  strokeWidth="3"
                  points={lineSeries}
                />
              </svg>
            </div>
            <div className="flex justify-between text-[11px] text-slate-400 mt-2">
              <span>24h ago</span>
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
      </div>
    </AppShell>
  );
}
