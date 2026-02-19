
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { fetchBlob, fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/StatusBadge";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { downloadBlob } from "../utils/download";
import { formatDateTime, statusLabel } from "../utils/format";
import { useI18n } from "../i18n/I18nContext";

const STATUS_OPTIONS = ["ok", "partial", "failed", "unknown"];
const EXPORT_INITIALS_STORAGE_KEY = "orders_export_initials";

function buildExportFilename(title, initials) {
  const safeTitle = (title || "Orders").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "Orders";
  const now = new Date();
  const day = String(now.getDate()).padStart(2, "0");
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const year = String(now.getFullYear()).slice(-2);
  const dateStamp = `${day}_${month}_${year}`;
  const parts = [safeTitle, dateStamp];
  if (initials) parts.push(initials);
  return `${parts.join("_")}.xlsx`;
}

function flagLabel(order, t) {
  const labels = [];
  if (order.reply_needed) labels.push(t("flags.reply"));
  if (order.human_review_needed) labels.push(t("flags.review"));
  if (order.post_case) labels.push(t("flags.post"));
  return labels.length ? labels.join(" | ") : "-";
}

export function OrdersPage() {
  const { token, logout } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { t, lang } = useI18n();

  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionBusy, setActionBusy] = useState("");
  const [searchInput, setSearchInput] = useState(searchParams.get("q") || "");
  const [isDraggingTable, setIsDraggingTable] = useState(false);

  const tableScrollRef = useRef(null);
  const dragStartXRef = useRef(0);
  const dragStartScrollRef = useRef(0);
  const dragPointerIdRef = useRef(null);

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
      setError(requestError.message || t("orders.loadError"));
    } finally {
      setLoading(false);
    }
  }, [queryString, t, token]);

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

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    const query = searchInput.trim();
    updateParams({ q: query || null });
  };

  const handleExportExcel = async () => {
    const exportTitle = t("orders.exportTitle");
    const storedInitials = localStorage.getItem(EXPORT_INITIALS_STORAGE_KEY) || "";
    const initialsInput = window.prompt(t("orders.initialsPrompt"), storedInitials);
    if (initialsInput === null) {
      return;
    }
    const initials = initialsInput.trim();
    if (initials) {
      localStorage.setItem(EXPORT_INITIALS_STORAGE_KEY, initials);
    }
    setActionBusy("excel");
    setActionError("");
    try {
      const exportParams = new URLSearchParams(searchParams);
      if (initials) exportParams.set("initials", initials);
      if (exportTitle) exportParams.set("title", exportTitle);
      const exportQuery = exportParams.toString();
      const blob = await fetchBlob(`/api/orders.xlsx${exportQuery ? `?${exportQuery}` : ""}`, { token });
      downloadBlob(blob, buildExportFilename(exportTitle, initials));
    } catch (requestError) {
      setActionError(requestError.message || t("orders.excelExportFailed"));
    } finally {
      setActionBusy("");
    }
  };

  const handleExportXml = async (orderId) => {
    setActionBusy(`export:${orderId}`);
    setActionError("");
    try {
      const result = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}/export-xml`, { method: "POST", token });
      const xmlFiles = Array.isArray(result?.xml_files) ? result.xml_files : [];
      if (!xmlFiles.length) {
        throw new Error(t("orders.noXmlAvailable"));
      }
      if (xmlFiles.length > 1) {
        setActionError(t("orders.multipleXmlNotice", { count: xmlFiles.length }));
        await loadOrders();
        return;
      }
      const xmlFile = xmlFiles[0];
      if (!xmlFile?.filename) {
        throw new Error(t("orders.noXmlAvailable"));
      }
      const blob = await fetchBlob(`/api/files/${encodeURIComponent(xmlFile.filename)}`, { token });
      downloadBlob(blob, xmlFile.filename);
      await loadOrders();
    } catch (requestError) {
      setActionError(requestError.message || t("orders.xmlExportFailed"));
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
        throw new Error(t("orders.noXmlAvailable"));
      }
      const blob = await fetchBlob(`/api/files/${encodeURIComponent(xmlFile.filename)}`, { token });
      downloadBlob(blob, xmlFile.filename);
    } catch (requestError) {
      setActionError(requestError.message || t("orders.xmlDownloadFailed"));
    } finally {
      setActionBusy("");
    }
  };

  const handleDeleteOrder = async (order) => {
    const label = order.ticket_number || order.kom_nr || order.id;
    const confirmed = window.confirm(t("orders.deleteConfirm", { id: label }));
    if (!confirmed) return;
    setActionBusy(`delete:${order.id}`);
    setActionError("");
    try {
      await fetchJson(`/api/orders/${encodeURIComponent(order.id)}`, { method: "DELETE", token });
      await loadOrders();
    } catch (requestError) {
      setActionError(requestError.message || t("orders.deleteFailed"));
    } finally {
      setActionBusy("");
    }
  };

  const orders = payload?.orders || [];
  const counts = payload?.counts || { all: 0, today: 0, needs_reply: 0, manual_review: 0 };
  const pagination = payload?.pagination || { page: 1, total_pages: 1, total: 0 };

  const hasPrev = pagination.page > 1;
  const hasNext = pagination.page < pagination.total_pages;

  const handleTablePointerDown = (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (!tableScrollRef.current) return;
    if (event.target.closest("button, a, input, select, textarea, [role='button']")) {
      return;
    }
    dragPointerIdRef.current = event.pointerId;
    dragStartXRef.current = event.clientX;
    dragStartScrollRef.current = tableScrollRef.current.scrollLeft;
    setIsDraggingTable(true);
    tableScrollRef.current.setPointerCapture(event.pointerId);
  };

  const handleTablePointerMove = (event) => {
    if (!isDraggingTable || !tableScrollRef.current) return;
    const deltaX = event.clientX - dragStartXRef.current;
    tableScrollRef.current.scrollLeft = dragStartScrollRef.current - deltaX;
  };

  const handleTablePointerUp = (event) => {
    if (!isDraggingTable || !tableScrollRef.current) return;
    if (dragPointerIdRef.current !== null) {
      tableScrollRef.current.releasePointerCapture(dragPointerIdRef.current);
    }
    dragPointerIdRef.current = null;
    setIsDraggingTable(false);
  };

  const renderFilters = (className = "", idPrefix = "filters", isDark = false) => (
    <aside
      className={[
        "rounded-xl border p-5 space-y-8",
        isDark
          ? "bg-slate-900/60 border-slate-800/70 shadow-[0_10px_30px_rgba(15,23,42,0.45)]"
          : "bg-surface-light border-slate-200 shadow-sm",
        className,
      ].join(" ")}
    >
      <div>
        <h3
          className={`text-xs font-bold uppercase tracking-wider mb-4 flex items-center ${
            isDark ? "text-slate-400" : "text-slate-400"
          }`}
        >
          <span className={`material-icons text-sm mr-1 ${isDark ? "text-primary/80" : ""}`}>date_range</span>
          {t("orders.extractionDate")}
        </h3>
        <div className="space-y-3">
          <div>
            <label
              className={`text-xs mb-1 block ${isDark ? "text-slate-400" : "text-slate-500"}`}
              htmlFor={`${idPrefix}-fromDate`}
            >
              {t("common.from")}
            </label>
            <input
              id={`${idPrefix}-fromDate`}
              type="date"
              className={`w-full rounded text-sm border ${
                isDark
                  ? "bg-slate-950/70 border-slate-800 text-slate-100 placeholder:text-slate-600 focus:ring-primary/60"
                  : "bg-slate-50 border-slate-200"
              }`}
              value={fromDate}
              onChange={(event) => updateParams({ from: event.target.value || null })}
            />
          </div>
          <div>
            <label
              className={`text-xs mb-1 block ${isDark ? "text-slate-400" : "text-slate-500"}`}
              htmlFor={`${idPrefix}-toDate`}
            >
              {t("common.to")}
            </label>
            <input
              id={`${idPrefix}-toDate`}
              type="date"
              className={`w-full rounded text-sm border ${
                isDark
                  ? "bg-slate-950/70 border-slate-800 text-slate-100 placeholder:text-slate-600 focus:ring-primary/60"
                  : "bg-slate-50 border-slate-200"
              }`}
              value={toDate}
              onChange={(event) => updateParams({ to: event.target.value || null })}
            />
          </div>
        </div>
      </div>

      <div>
        <h3
          className={`text-xs font-bold uppercase tracking-wider mb-4 flex items-center ${
            isDark ? "text-slate-400" : "text-slate-400"
          }`}
        >
          <span className={`material-icons text-sm mr-1 ${isDark ? "text-primary/80" : ""}`}>rule</span>
          {t("orders.extractionStatus")}
        </h3>
        <div className="space-y-2">
          {STATUS_OPTIONS.map((status) => (
            <label key={status} className="flex items-center group cursor-pointer">
              <input
                type="checkbox"
                checked={selectedStatuses.has(status)}
                onChange={() => toggleStatus(status)}
                className={`h-4 w-4 text-primary rounded focus:ring-primary ${
                  isDark ? "border-slate-700 bg-slate-950/70" : "border-slate-300"
                }`}
              />
              <span
                className={`ml-3 text-sm transition-colors ${
                  isDark ? "text-slate-200 group-hover:text-white" : "text-slate-600 group-hover:text-primary"
                }`}
              >
                {statusLabel(status, t)}
              </span>
              <span
                className={`ml-auto text-xs px-1.5 py-0.5 rounded ${
                  isDark ? "bg-slate-800/70 text-slate-300 border border-slate-700/60" : "bg-slate-100 text-slate-600"
                }`}
              >
                {payload?.counts?.status?.[status] ?? 0}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <h3
          className={`text-xs font-bold uppercase tracking-wider mb-4 flex items-center ${
            isDark ? "text-slate-400" : "text-slate-400"
          }`}
        >
          <span className={`material-icons text-sm mr-1 ${isDark ? "text-primary/80" : ""}`}>flag</span>
          {t("orders.workflowFlags")}
        </h3>
        <div className="space-y-4">
          <label className="flex items-center justify-between">
            <span className={`text-sm ${isDark ? "text-slate-200" : "text-slate-700"}`}>{t("common.replyNeeded")}</span>
            <input
              type="checkbox"
              checked={replyNeededParam === "true"}
              onChange={(event) => updateParams({ reply_needed: event.target.checked ? "true" : null })}
              className={`h-4 w-4 text-primary rounded focus:ring-primary ${
                isDark ? "border-slate-700 bg-slate-950/70" : "border-slate-300"
              }`}
            />
          </label>
          <label className="flex items-center justify-between">
            <span className={`text-sm ${isDark ? "text-slate-200" : "text-slate-700"}`}>{t("common.humanReview")}</span>
            <input
              type="checkbox"
              checked={humanReviewParam === "true"}
              onChange={(event) => updateParams({ human_review_needed: event.target.checked ? "true" : null })}
              className={`h-4 w-4 text-primary rounded focus:ring-primary ${
                isDark ? "border-slate-700 bg-slate-950/70" : "border-slate-300"
              }`}
            />
          </label>
          <label className="flex items-center justify-between">
            <span className={`text-sm ${isDark ? "text-slate-200" : "text-slate-700"}`}>{t("common.postCase")}</span>
            <input
              type="checkbox"
              checked={postCaseParam === "true"}
              onChange={(event) => updateParams({ post_case: event.target.checked ? "true" : null })}
              className={`h-4 w-4 text-primary rounded focus:ring-primary ${
                isDark ? "border-slate-700 bg-slate-950/70" : "border-slate-300"
              }`}
            />
          </label>
        </div>
      </div>
    </aside>
  );

  return (
    <AppShell active="orders" sidebarContent={renderFilters("", "sidebar", false)}>
      <main className="flex-1 flex flex-col min-w-0">
        <div className="sticky top-0 z-30">
          <header className="h-16 bg-surface-light border-b border-slate-200 flex items-center justify-between px-6">
            <form onSubmit={handleSearchSubmit} className="relative w-full max-w-xl">
              <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">search</span>
              <input
                className="w-full bg-slate-50 border-none rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary"
                placeholder={t("orders.searchPlaceholder")}
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </form>
            <div className="flex items-center gap-3 ml-4">
              <LanguageSwitcher compact className="hidden md:flex" />
              <button onClick={logout} type="button" className="text-sm px-3 py-1.5 rounded-lg bg-slate-900 text-white hover:bg-slate-700">
                {t("common.logout")}
              </button>
            </div>
          </header>

          <div className="bg-surface-light px-6 pt-6 pb-0 border-b border-slate-200 shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 gap-2">
              <div>
                <h1 className="text-2xl font-bold text-slate-900 mb-1">{t("orders.workspaceTitle")}</h1>
                <p className="text-sm text-slate-500">{t("orders.workspaceSubtitle")}</p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleExportExcel}
                  disabled={actionBusy === "excel"}
                  className="bg-white border border-slate-200 text-slate-700 px-4 py-2 rounded text-sm font-medium hover:bg-slate-50 transition-colors flex items-center gap-2 disabled:opacity-60"
                >
                  <span className="material-icons text-base">file_download</span>
                  {actionBusy === "excel" ? t("orders.exporting") : t("common.exportExcel")}
                </button>
                <button type="button" disabled className="bg-primary/40 text-white px-4 py-2 rounded text-sm font-medium cursor-not-allowed">
                  {t("orders.manualOrder")}
                </button>
              </div>
            </div>

            <div className="flex items-center gap-6 overflow-x-auto">
              <button
                type="button"
                onClick={() => applyTab("all")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "all" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("orders.allOrders")} <span className="bg-slate-100 text-slate-600 py-0.5 px-2 rounded-full text-xs ml-1">{counts.all || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("today")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "today" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("orders.todaysQueue")} <span className="bg-primary/10 text-primary-dark py-0.5 px-2 rounded-full text-xs ml-1">{counts.today || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("needs_reply")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "needs_reply" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("orders.needsReply")} <span className="bg-amber-100 text-amber-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts.needs_reply || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("manual_review")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "manual_review" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("orders.manualReview")} <span className="bg-red-100 text-red-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts.manual_review || 0}</span>
              </button>
            </div>
          </div>
        </div>

        <div className="px-6 py-6 space-y-6">
        {error ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{error}</div> : null}
        {actionError ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{actionError}</div> : null}

          <div className="lg:hidden mb-6">
            {renderFilters("", "mobile", false)}
          </div>

          <div>
            <div
              ref={tableScrollRef}
              onPointerDown={handleTablePointerDown}
              onPointerMove={handleTablePointerMove}
              onPointerUp={handleTablePointerUp}
              onPointerLeave={handleTablePointerUp}
              onPointerCancel={handleTablePointerUp}
              className={`relative bg-surface-light rounded-lg shadow-sm border border-slate-200 overflow-x-auto overflow-y-auto max-h-[70vh] ${isDraggingTable ? "cursor-grabbing select-none" : "cursor-grab"}`}
            >
              <table className="w-full text-left text-sm whitespace-nowrap">
                <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-20">
                  <tr>
                    <th className="px-4 py-3 font-semibold text-slate-500 sticky top-0 left-0 z-10 bg-slate-50 border-r border-slate-200">Nr</th>
                    <th className="px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50 w-40 max-w-40">{t("common.orderId")}</th>
                    <th className="px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50">{t("common.dateTime")}</th>
                    <th className="px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50">{t("common.customer")}</th>
                    <th className="px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50">{t("common.amount")}</th>
                    <th className="px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50">{t("common.status")}</th>
                    <th className="px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50">{t("common.flags")}</th>
                    <th className="px-4 py-3 font-semibold text-slate-500 text-right sticky top-0 z-10 bg-slate-50">{t("common.actions")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {orders.map((order, index) => (
                    <tr key={order.id} className="hover:bg-slate-50 transition-colors group">
                      <td className="px-4 py-3 text-slate-500 border-r border-slate-100 sticky left-0 z-10 bg-surface-light">
                        {(pagination.page - 1) * (pagination.page_size || orders.length || 0) + index + 1}
                      </td>
                      <td className="px-4 py-3 w-40 max-w-40">
                        <button
                          type="button"
                          onClick={() => navigate(`/orders/${order.id}`)}
                          className="font-medium text-primary hover:underline block w-full text-left truncate"
                        >
                          {order.ticket_number || order.kom_nr || order.id}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{formatDateTime(order.effective_received_at, lang)}</td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-900">{order.kom_name || "-"}</div>
                        <div className="text-xs text-slate-500">{order.store_name || order.kundennummer || "-"}</div>
                      </td>
                      <td className="px-4 py-3 font-medium text-slate-900">{order.delivery_week || order.liefertermin || "-"}</td>
                      <td className="px-4 py-3"><StatusBadge status={order.status} /></td>
                      <td className="px-4 py-3 text-xs text-slate-600">{flagLabel(order, t)}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => handleDownloadXml(order.id)}
                            disabled={actionBusy === `download:${order.id}`}
                            className="p-1.5 text-slate-500 hover:text-primary hover:bg-primary/10 rounded transition-colors disabled:opacity-60"
                            title={t("common.downloadXml")}
                          >
                            <span className="material-icons text-lg">download</span>
                          </button>
                          <Link
                            to={`/orders/${order.id}`}
                            className="p-1.5 text-primary bg-primary/10 rounded transition-colors hover:bg-primary hover:text-white"
                            title={t("common.viewDetails")}
                          >
                            <span className="material-icons text-lg">visibility</span>
                          </Link>
                          <button
                            type="button"
                            onClick={() => handleDeleteOrder(order)}
                            disabled={actionBusy === `delete:${order.id}`}
                            className="p-1.5 text-slate-500 hover:text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-60"
                            title={t("common.delete")}
                          >
                            <span className="material-icons text-lg">delete</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!loading && orders.length === 0 ? (
                    <tr>
                      <td className="px-4 py-8 text-center text-slate-500" colSpan={8}>{t("orders.noMatchingOrders")}</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between px-2">
              <div className="text-sm text-slate-500">
                {t("orders.showing", {
                  from: orders.length ? (pagination.page - 1) * (pagination.page_size || orders.length) + 1 : 0,
                  to: (pagination.page - 1) * (pagination.page_size || 0) + orders.length,
                  total: pagination.total || 0,
                })}
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
        </div>
      </main>
    </AppShell>
  );
}
