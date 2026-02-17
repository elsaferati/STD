import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { fetchBlob, fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/StatusBadge";
import { downloadBlob } from "../utils/download";
import { formatDateTime, statusLabel } from "../utils/format";

const STATUS_OPTIONS = ["ok", "partial", "failed", "unknown"];

function flagLabel(order) {
  const labels = [];
  if (order.reply_needed) labels.push("Reply");
  if (order.human_review_needed) labels.push("Review");
  if (order.post_case) labels.push("Post");
  return labels.length ? labels.join(" | ") : "-";
}

export function OrdersPage() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionBusy, setActionBusy] = useState("");

  const queryString = useMemo(() => searchParams.toString(), [searchParams]);
  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const fromDate = searchParams.get("from") || "";
  const toDate = searchParams.get("to") || "";
  const selectedStatuses = useMemo(
    () => new Set((searchParams.get("status") || "").split(",").filter(Boolean)),
    [searchParams],
  );

  const replyNeededParam = searchParams.get("reply_needed");
  const humanReviewParam = searchParams.get("human_review_needed");
  const postCaseParam = searchParams.get("post_case");

  const activeTab = useMemo(() => {
    if (replyNeededParam === "true") {
      return "needs_reply";
    }
    if (humanReviewParam === "true") {
      return "manual_review";
    }
    if (fromDate === todayIso && toDate === todayIso) {
      return "today";
    }
    return "all";
  }, [fromDate, humanReviewParam, replyNeededParam, toDate, todayIso]);

  const updateParams = useCallback(
    (updates, options = {}) => {
      const { resetPage = true } = options;
      const next = new URLSearchParams(searchParams);

      Object.entries(updates).forEach(([key, value]) => {
        if (value === null || value === undefined || value === "") {
          next.delete(key);
        } else {
          next.set(key, String(value));
        }
      });

      if (resetPage && !Object.prototype.hasOwnProperty.call(updates, "page")) {
        next.delete("page");
      }

      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  const loadOrders = useCallback(async () => {
    try {
      const result = await fetchJson(`/api/orders${queryString ? `?${queryString}` : ""}`, { token });
      setPayload(result);
      setError("");
    } catch (requestError) {
      setError(requestError.message || "Failed to load orders.");
    } finally {
      setLoading(false);
    }
  }, [queryString, token]);

  useEffect(() => {
    loadOrders();
    const intervalId = setInterval(loadOrders, 15000);
    return () => clearInterval(intervalId);
  }, [loadOrders]);

  const applyTab = (tab) => {
    if (tab === "today") {
      updateParams({ from: todayIso, to: todayIso, reply_needed: null, human_review_needed: null });
      return;
    }
    if (tab === "needs_reply") {
      updateParams({ reply_needed: "true", human_review_needed: null });
      return;
    }
    if (tab === "manual_review") {
      updateParams({ human_review_needed: "true", reply_needed: null });
      return;
    }
    updateParams({ from: null, to: null, reply_needed: null, human_review_needed: null, post_case: null, status: null });
  };

  const toggleStatus = (status) => {
    const next = new Set(selectedStatuses);
    if (next.has(status)) {
      next.delete(status);
    } else {
      next.add(status);
    }
    updateParams({ status: next.size ? Array.from(next).join(",") : null });
  };

  const handleExportCsv = async () => {
    setActionBusy("csv");
    setActionError("");
    try {
      const blob = await fetchBlob(`/api/orders.csv${queryString ? `?${queryString}` : ""}`, { token });
      downloadBlob(blob, "orders.csv");
    } catch (requestError) {
      setActionError(requestError.message || "CSV export failed.");
    } finally {
      setActionBusy("");
    }
  };

  const handleExportXml = async (orderId) => {
    setActionBusy(`export:${orderId}`);
    setActionError("");
    try {
      await fetchJson(`/api/orders/${encodeURIComponent(orderId)}/export-xml`, { method: "POST", token });
      await loadOrders();
    } catch (requestError) {
      setActionError(requestError.message || "XML export failed.");
    } finally {
      setActionBusy("");
    }
  };

  const handleDownloadXml = async (orderId) => {
    setActionBusy(`download:${orderId}`);
    setActionError("");
    try {
      const detail = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`, { token });
      const xmlFile = detail?.xml_files?.[0];
      if (!xmlFile) {
        throw new Error("No XML file available for this order.");
      }
      const blob = await fetchBlob(`/api/files/${encodeURIComponent(xmlFile.filename)}`, { token });
      downloadBlob(blob, xmlFile.filename);
    } catch (requestError) {
      setActionError(requestError.message || "XML download failed.");
    } finally {
      setActionBusy("");
    }
  };

  const orders = payload?.orders || [];
  const counts = payload?.counts || { all: 0, today: 0, needs_reply: 0, manual_review: 0 };
  const pagination = payload?.pagination || { page: 1, total_pages: 1, total: 0 };

  const hasPrev = pagination.page > 1;
  const hasNext = pagination.page < pagination.total_pages;

  const sidebarContent = (
    <div className="p-6 space-y-8">
      <div>
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4 flex items-center">
          <span className="material-icons text-sm mr-1">date_range</span>
          Extraction Date
        </h3>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-500 mb-1 block" htmlFor="fromDate">From</label>
            <input
              id="fromDate"
              type="date"
              className="w-full bg-slate-50 border-slate-200 rounded text-sm"
              value={fromDate}
              onChange={(event) => updateParams({ from: event.target.value || null })}
            />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block" htmlFor="toDate">To</label>
            <input
              id="toDate"
              type="date"
              className="w-full bg-slate-50 border-slate-200 rounded text-sm"
              value={toDate}
              onChange={(event) => updateParams({ to: event.target.value || null })}
            />
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4 flex items-center">
          <span className="material-icons text-sm mr-1">rule</span>
          Extraction Status
        </h3>
        <div className="space-y-2">
          {STATUS_OPTIONS.map((status) => (
            <label key={status} className="flex items-center group cursor-pointer">
              <input
                type="checkbox"
                checked={selectedStatuses.has(status)}
                onChange={() => toggleStatus(status)}
                className="h-4 w-4 text-primary rounded border-slate-300 focus:ring-primary"
              />
              <span className="ml-3 text-sm text-slate-600 group-hover:text-primary transition-colors">
                {statusLabel(status)}
              </span>
              <span className="ml-auto text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded">
                {payload?.counts?.status?.[status] ?? 0}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4 flex items-center">
          <span className="material-icons text-sm mr-1">flag</span>
          Workflow Flags
        </h3>
        <div className="space-y-4">
          <label className="flex items-center justify-between">
            <span className="text-sm text-slate-700">Reply Needed</span>
            <input
              type="checkbox"
              checked={replyNeededParam === "true"}
              onChange={(event) => updateParams({ reply_needed: event.target.checked ? "true" : null })}
              className="h-4 w-4 text-primary rounded border-slate-300 focus:ring-primary"
            />
          </label>
          <label className="flex items-center justify-between">
            <span className="text-sm text-slate-700">Human Review</span>
            <input
              type="checkbox"
              checked={humanReviewParam === "true"}
              onChange={(event) => updateParams({ human_review_needed: event.target.checked ? "true" : null })}
              className="h-4 w-4 text-primary rounded border-slate-300 focus:ring-primary"
            />
          </label>
          <label className="flex items-center justify-between">
            <span className="text-sm text-slate-700">Post Case</span>
            <input
              type="checkbox"
              checked={postCaseParam === "true"}
              onChange={(event) => updateParams({ post_case: event.target.checked ? "true" : null })}
              className="h-4 w-4 text-primary rounded border-slate-300 focus:ring-primary"
            />
          </label>
        </div>
      </div>
    </div>
  );

  return (
    <AppShell sidebarContent={sidebarContent}>
      <div className="space-y-4">
        <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-6 pt-6 pb-4 border-b border-slate-200">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h1 className="text-2xl font-bold text-slate-900 mb-1">Orders Workspace</h1>
                <p className="text-sm text-slate-500">Manage and validate extracted order data.</p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleExportCsv}
                  disabled={actionBusy === "csv"}
                  className="bg-white border border-slate-200 text-slate-700 px-4 py-2 rounded text-sm font-medium hover:bg-slate-50 transition-colors flex items-center gap-2 disabled:opacity-60"
                >
                  <span className="material-icons text-base">file_download</span>
                  {actionBusy === "csv" ? "Exporting..." : "Export CSV"}
                </button>
                <button type="button" disabled className="bg-primary/40 text-white px-4 py-2 rounded text-sm font-medium cursor-not-allowed">
                  Manual Order
                </button>
              </div>
            </div>
          </div>

          <div className="px-6 py-3 flex items-center gap-6 overflow-x-auto">
            <button
              type="button"
              onClick={() => applyTab("all")}
              className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "all" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
            >
              All Orders <span className="bg-slate-100 text-slate-600 py-0.5 px-2 rounded-full text-xs ml-1">{counts.all || 0}</span>
            </button>
            <button
              type="button"
              onClick={() => applyTab("today")}
              className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "today" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
            >
              Today's Queue <span className="bg-primary/10 text-primary-dark py-0.5 px-2 rounded-full text-xs ml-1">{counts.today || 0}</span>
            </button>
            <button
              type="button"
              onClick={() => applyTab("needs_reply")}
              className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "needs_reply" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
            >
              Needs Reply <span className="bg-amber-100 text-amber-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts.needs_reply || 0}</span>
            </button>
            <button
              type="button"
              onClick={() => applyTab("manual_review")}
              className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "manual_review" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
            >
              Manual Review <span className="bg-red-100 text-red-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts.manual_review || 0}</span>
            </button>
          </div>
        </div>

        {error ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{error}</div> : null}
        {actionError ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{actionError}</div> : null}

        <div className="bg-surface-light rounded-lg shadow-sm border border-slate-200 overflow-hidden">
          <table className="w-full text-left text-sm whitespace-nowrap">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-4 py-3 font-semibold text-slate-500">Order ID</th>
                <th className="px-4 py-3 font-semibold text-slate-500">Date & Time</th>
                <th className="px-4 py-3 font-semibold text-slate-500">Customer</th>
                <th className="px-4 py-3 font-semibold text-slate-500">Amount</th>
                <th className="px-4 py-3 font-semibold text-slate-500">Status</th>
                <th className="px-4 py-3 font-semibold text-slate-500">Flags</th>
                <th className="px-4 py-3 font-semibold text-slate-500 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {orders.map((order) => (
                <tr key={order.id} className="hover:bg-slate-50 transition-colors group">
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => navigate(`/orders/${order.id}`)}
                      className="font-medium text-primary hover:underline"
                    >
                      {order.ticket_number || order.kom_nr || order.id}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{formatDateTime(order.effective_received_at)}</td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{order.kom_name || "-"}</div>
                    <div className="text-xs text-slate-500">{order.store_name || order.kundennummer || "-"}</div>
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-900">{order.delivery_week || order.liefertermin || "-"}</td>
                  <td className="px-4 py-3"><StatusBadge status={order.status} /></td>
                  <td className="px-4 py-3 text-xs text-slate-600">{flagLabel(order)}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => handleExportXml(order.id)}
                        disabled={actionBusy === `export:${order.id}`}
                        className="p-1.5 text-slate-500 hover:text-primary hover:bg-primary/10 rounded transition-colors disabled:opacity-60"
                        title="Export XML"
                      >
                        <span className="material-icons text-lg">code</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDownloadXml(order.id)}
                        disabled={actionBusy === `download:${order.id}`}
                        className="p-1.5 text-slate-500 hover:text-primary hover:bg-primary/10 rounded transition-colors disabled:opacity-60"
                        title="Download XML"
                      >
                        <span className="material-icons text-lg">download</span>
                      </button>
                      <Link
                        to={`/orders/${order.id}`}
                        className="p-1.5 text-primary bg-primary/10 rounded transition-colors hover:bg-primary hover:text-white"
                        title="View Details"
                      >
                        <span className="material-icons text-lg">visibility</span>
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && orders.length === 0 ? (
                <tr>
                  <td className="px-4 py-8 text-center text-slate-500" colSpan={7}>No matching orders.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between px-2">
          <div className="text-sm text-slate-500">
            Showing <span className="font-medium text-slate-900">{orders.length ? (pagination.page - 1) * (pagination.page_size || orders.length) + 1 : 0}</span>
            {" "}to{" "}
            <span className="font-medium text-slate-900">{(pagination.page - 1) * (pagination.page_size || 0) + orders.length}</span>
            {" "}of <span className="font-medium text-slate-900">{pagination.total || 0}</span> results
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!hasPrev}
              onClick={() => updateParams({ page: pagination.page - 1 }, { resetPage: false })}
              className="p-2 border border-slate-200 rounded bg-surface-light text-slate-500 disabled:opacity-40"
            >
              <span className="material-icons text-sm">chevron_left</span>
            </button>
            <span className="px-3 py-1 bg-primary text-white rounded text-sm font-medium">{pagination.page}</span>
            <span className="text-sm text-slate-500">/ {pagination.total_pages || 1}</span>
            <button
              type="button"
              disabled={!hasNext}
              onClick={() => updateParams({ page: pagination.page + 1 }, { resetPage: false })}
              className="p-2 border border-slate-200 rounded bg-surface-light text-slate-500 disabled:opacity-40"
            >
              <span className="material-icons text-sm">chevron_right</span>
            </button>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
