
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { fetchBlob, fetchJson } from "../api/http";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/StatusBadge";
import { ValidationBadge } from "../components/ValidationBadge";
import { CLIENT_BRANCHES, UNKNOWN_CLIENT_BRANCH_ID } from "../constants/clientBranches";
import { downloadBlob } from "../utils/download";
import { formatDateTime } from "../utils/format";
import { useI18n } from "../i18n/I18nContext";

const EXPORT_INITIALS_STORAGE_KEY = "orders_export_initials";
const ORDER_LIST_RESTORE_KEY = "orders_list_restore";

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

export function OrdersPage() {
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
  const orderRowRefs = useRef(new Map());
  const hasRestoredScrollRef = useRef(false);
  const dragStartXRef = useRef(0);
  const dragStartScrollRef = useRef(0);
  const dragPointerIdRef = useRef(null);

  const queryString = useMemo(() => searchParams.toString(), [searchParams]);
  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const fromDate = searchParams.get("from") || "";
  const toDate = searchParams.get("to") || "";
  const queueParam = searchParams.get("queue") || "";
  const statusParam = searchParams.get("status");
  const validationStatusParam = searchParams.get("validation_status") || "";
  const clientParam = searchParams.get("client") || "";
  const deliveryWeekParam = searchParams.get("delivery_week") || "";

  const activeTab = useMemo(() => {
    if (validationStatusParam === "flagged,stale" || validationStatusParam === "stale,flagged") {
      return "gemini_review";
    }
    if (statusParam === "ok") {
      return "ok";
    }
    if (statusParam === "human_in_the_loop") {
      return "manual_review";
    }
    if (statusParam === "waiting_for_reply") {
      return "waiting_for_reply";
    }
    if (statusParam === "unknown") {
      return "unknown";
    }
    if (statusParam === "updated_after_reply") {
      return "updated_after_reply";
    }
    if (statusParam === "post") {
      return "post";
    }
    if (statusParam === "failed") {
      return "failed";
    }
    if (queueParam === "today") {
      return "today";
    }
    return "all";
  }, [queueParam, statusParam, validationStatusParam]);

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
      const result = await fetchJson(`/api/orders${queryString ? `?${queryString}` : ""}`);
      setPayload(result);
      setError("");
    } catch (requestError) {
      setError(requestError.message || t("orders.loadError"));
    } finally {
      setLoading(false);
    }
  }, [queryString, t]);

  useEffect(() => {
    loadOrders();
    const intervalId = setInterval(loadOrders, 15000);
    return () => clearInterval(intervalId);
  }, [loadOrders]);

  const rememberOrderPosition = useCallback((orderId) => {
    if (!orderId) return;
    sessionStorage.setItem(
      ORDER_LIST_RESTORE_KEY,
      JSON.stringify({
        orderId,
        queryString,
      }),
    );
  }, [queryString]);

  const applyTab = (tab) => {
    if (tab === "today") {
      updateParams({
        queue: "today",
        status: null,
        reply_needed: null,
        human_review_needed: null,
        post_case: null,
        validation_status: null,
      });
      return;
    }
    if (tab === "needs_reply") {
      updateParams({ status: "reply", human_review_needed: null, reply_needed: null, post_case: null, validation_status: null });
      return;
    }
    if (tab === "ok") {
      updateParams({ status: "ok", human_review_needed: null, reply_needed: null, post_case: null, validation_status: null });
      return;
    }
    if (tab === "manual_review") {
      updateParams({ status: "human_in_the_loop", reply_needed: null, human_review_needed: null, post_case: null, validation_status: null });
      return;
    }
    if (tab === "gemini_review") {
      updateParams({ status: null, reply_needed: null, human_review_needed: null, post_case: null, validation_status: "flagged,stale" });
      return;
    }
    if (tab === "waiting_for_reply") {
      updateParams({ status: "waiting_for_reply", reply_needed: null, human_review_needed: null, post_case: null, validation_status: null });
      return;
    }
    if (tab === "unknown") {
      updateParams({ status: "unknown", reply_needed: null, human_review_needed: null, post_case: null, validation_status: null });
      return;
    }
    if (tab === "updated_after_reply") {
      updateParams({ status: "updated_after_reply", reply_needed: null, human_review_needed: null, post_case: null, validation_status: null });
      return;
    }
    if (tab === "post") {
      updateParams({ status: "post", reply_needed: null, human_review_needed: null, post_case: null, validation_status: null });
      return;
    }
    if (tab === "failed") {
      updateParams({ status: "failed", reply_needed: null, human_review_needed: null, post_case: null, validation_status: null });
      return;
    }
    updateParams({ queue: null, from: null, to: null, reply_needed: null, human_review_needed: null, post_case: null, status: null, validation_status: null });
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
      const blob = await fetchBlob(`/api/orders.xlsx${exportQuery ? `?${exportQuery}` : ""}`);
      downloadBlob(blob, buildExportFilename(exportTitle, initials));
    } catch (requestError) {
      setActionError(requestError.message || t("orders.excelExportFailed"));
    } finally {
      setActionBusy("");
    }
  };

  const handleExportXmlZip = async () => {
    setActionBusy("xmlzip");
    setActionError("");
    try {
      const exportParams = new URLSearchParams(searchParams);
      const exportQuery = exportParams.toString();
      const blob = await fetchBlob(`/api/orders/export-xml.zip${exportQuery ? `?${exportQuery}` : ""}`);
      const now = new Date();
      const date = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}-${String(now.getDate()).padStart(2,"0")}`;
      downloadBlob(blob, `orders_xml_${date}.zip`);
    } catch (requestError) {
      setActionError(requestError.message || t("orders.xmlZipExportFailed"));
    } finally {
      setActionBusy("");
    }
  };

  const handleDownloadXml = async (orderId) => {
    setActionBusy(`download:${orderId}`);
    setActionError("");
    try {
      const detail = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`);
      const xmlFile = detail?.xml_files?.[0];
      if (!xmlFile) {
        throw new Error(t("orders.noXmlAvailable"));
      }
      const blob = await fetchBlob(`/api/files/${encodeURIComponent(xmlFile.filename)}`);
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
      await fetchJson(`/api/orders/${encodeURIComponent(order.id)}`, { method: "DELETE" });
      await loadOrders();
    } catch (requestError) {
      setActionError(requestError.message || t("orders.deleteFailed"));
    } finally {
      setActionBusy("");
    }
  };

  const orders = payload?.orders || [];
  const counts = payload?.counts || { all: 0, today: 0, waiting_for_reply: 0, manual_review: 0, gemini_review: 0, unknown: 0, updated_after_reply: 0 };
  const pagination = payload?.pagination || { page: 1, total_pages: 1, total: 0 };
  const clientOptions = useMemo(() => {
    const options = [...CLIENT_BRANCHES];
    const hasUnknown = orders.some(
      (order) =>
        order.extraction_branch &&
        !CLIENT_BRANCHES.some((branch) => branch.id === order.extraction_branch),
    );
    if (hasUnknown) {
      options.push({
        id: UNKNOWN_CLIENT_BRANCH_ID,
        labelKey: "clients.branch.unknown",
        defaultLabel: "Unknown",
      });
    }
    return options;
  }, [orders]);
  const deliveryWeekOptions = useMemo(() => {
    const unique = new Set();
    orders.forEach((order) => {
      const value = String(order.delivery_week || order.liefertermin || "").trim();
      if (value) unique.add(value);
    });
    if (deliveryWeekParam) {
      unique.add(deliveryWeekParam);
    }
    return Array.from(unique).sort((a, b) => a.localeCompare(b));
  }, [deliveryWeekParam, orders]);
  const visibleOrders = useMemo(() => {
    if (queueParam !== "today" || fromDate || toDate) {
      return orders;
    }
    return orders.filter((order) => {
      const rawDate = order.effective_received_at || order.received_at || "";
      if (!rawDate) {
        return false;
      }
      const parsedDate = new Date(rawDate);
      if (Number.isNaN(parsedDate.getTime())) {
        return false;
      }
      return parsedDate.toISOString().slice(0, 10) === todayIso;
    });
  }, [fromDate, orders, queueParam, toDate, todayIso]);
  const hasActiveFilters = useMemo(
    () => Boolean(searchParams.get("q") || queueParam || statusParam || validationStatusParam || clientParam || fromDate || toDate || deliveryWeekParam),
    [clientParam, deliveryWeekParam, fromDate, queueParam, searchParams, statusParam, toDate, validationStatusParam],
  );

  useEffect(() => {
    if (loading || hasRestoredScrollRef.current) {
      return;
    }

    const savedState = sessionStorage.getItem(ORDER_LIST_RESTORE_KEY);
    if (!savedState) {
      hasRestoredScrollRef.current = true;
      return;
    }

    try {
      const parsedState = JSON.parse(savedState);
      if (parsedState?.queryString !== queryString) {
        sessionStorage.removeItem(ORDER_LIST_RESTORE_KEY);
        hasRestoredScrollRef.current = true;
        return;
      }
      const targetRow = orderRowRefs.current.get(parsedState?.orderId);
      if (!targetRow) {
        return;
      }
      hasRestoredScrollRef.current = true;
      requestAnimationFrame(() => {
        targetRow.scrollIntoView({ block: "center", behavior: "auto" });
      });
      sessionStorage.removeItem(ORDER_LIST_RESTORE_KEY);
    } catch {
      sessionStorage.removeItem(ORDER_LIST_RESTORE_KEY);
      hasRestoredScrollRef.current = true;
    }
  }, [loading, queryString, visibleOrders]);

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

  const handleTablePointerUp = () => {
    if (!isDraggingTable || !tableScrollRef.current) return;
    if (dragPointerIdRef.current !== null) {
      tableScrollRef.current.releasePointerCapture(dragPointerIdRef.current);
    }
    dragPointerIdRef.current = null;
    setIsDraggingTable(false);
  };

  const displayedFromDate = queueParam === "today" && !fromDate ? todayIso : fromDate;
  const displayedToDate = queueParam === "today" && !toDate ? todayIso : toDate;

  return (
    <AppShell active="orders">
      <main className="flex-1 flex flex-col min-w-0">
        <div className="px-6 py-6 space-y-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-slate-900">{t("orders.workspaceTitle")}</h1>
              <p className="text-sm text-slate-500 mt-1">{t("orders.workspaceSubtitle")}</p>
            </div>
          </div>

          <div className="border-b border-slate-200">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <button
                type="button"
                onClick={() => applyTab("today")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "today" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {lang === "de" ? "Heute" : "Today"} <span className="bg-primary/10 text-primary-dark py-0.5 px-2 rounded-full text-xs ml-1">{counts.today || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("all")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "all" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {lang === "de" ? "Alle" : "All"} <span className="bg-slate-100 text-slate-600 py-0.5 px-2 rounded-full text-xs ml-1">{counts.all || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("ok")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "ok" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("status.ok")} <span className="bg-emerald-100 text-emerald-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts?.status?.ok || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("waiting_for_reply")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "waiting_for_reply" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("status.waiting_for_reply")} <span className="bg-amber-100 text-amber-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts.waiting_for_reply || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("updated_after_reply")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "updated_after_reply" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("status.updated_after_reply")} <span className="bg-teal-100 text-teal-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts.updated_after_reply || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("manual_review")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "manual_review" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("orders.manualReview")} <span className="bg-red-100 text-red-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts.manual_review || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("post")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "post" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("status.post")} <span className="bg-indigo-100 text-indigo-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts?.status?.post || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("gemini_review")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "gemini_review" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("orders.geminiReview")} <span className="bg-fuchsia-100 text-fuchsia-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts.gemini_review || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("unknown")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "unknown" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {lang === "de" ? "Unbekannt" : "Unknown"} <span className="bg-slate-200 text-slate-600 py-0.5 px-2 rounded-full text-xs ml-1">{counts.unknown || 0}</span>
              </button>
              <button
                type="button"
                onClick={() => applyTab("failed")}
                className={`pb-3 border-b-2 text-sm whitespace-nowrap transition-all ${activeTab === "failed" ? "border-primary text-primary font-bold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
              >
                {t("status.failed")} <span className="bg-slate-200 text-slate-700 py-0.5 px-2 rounded-full text-xs ml-1">{counts?.status?.failed || 0}</span>
              </button>
            </div>
          </div>

          <div className="rounded-lg border border-slate-200 bg-surface-light p-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <form onSubmit={handleSearchSubmit} className="flex flex-wrap items-center gap-2">
                <div className="relative min-w-[240px] flex-1 sm:flex-none sm:w-72">
                  <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-[18px]">search</span>
                  <input
                    className="w-full bg-slate-50 border border-slate-200 rounded-md pl-9 pr-3 py-2 text-sm focus:ring-2 focus:ring-primary"
                    placeholder={t("orders.searchPlaceholder")}
                    value={searchInput}
                    onChange={(event) => setSearchInput(event.target.value)}
                  />
                </div>
                <select
                  className="h-9 rounded-md border border-slate-200 bg-white pl-2.5 pr-9 text-sm text-slate-700 focus:ring-2 focus:ring-primary"
                  value={clientParam}
                  onChange={(event) => updateParams({ client: event.target.value || null })}
                >
                  <option value="">{t("clients.filterLabel")}</option>
                  {clientOptions.map((branch) => (
                    <option key={branch.id} value={branch.id}>
                      {t(branch.labelKey, null, branch.defaultLabel)}
                    </option>
                  ))}
                </select>
                <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-white px-2.5 h-9">
                  <span className="text-xs uppercase tracking-wide text-slate-500">{t("orders.extractionDate")}</span>
                  <input
                    type="date"
                    className="bg-transparent text-sm text-slate-700 focus:outline-none"
                    value={displayedFromDate}
                    onChange={(event) => updateParams({ queue: null, from: event.target.value || null })}
                    aria-label={t("common.from")}
                  />
                  <span className="text-slate-300">-</span>
                  <input
                    type="date"
                    className="bg-transparent text-sm text-slate-700 focus:outline-none"
                    value={displayedToDate}
                    onChange={(event) => updateParams({ queue: null, to: event.target.value || null })}
                    aria-label={t("common.to")}
                  />
                </div>
                {deliveryWeekOptions.length ? (
                  <select
                    className="h-9 rounded-md border border-slate-200 bg-white px-2.5 text-sm text-slate-700 focus:ring-2 focus:ring-primary"
                    value={deliveryWeekParam}
                    onChange={(event) => updateParams({ delivery_week: event.target.value || null })}
                  >
                    <option value="">{t("orders.deliveryWeek")}</option>
                    {deliveryWeekOptions.map((week) => (
                      <option key={week} value={week}>
                        {week}
                      </option>
                    ))}
                  </select>
                ) : null}
                {hasActiveFilters ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSearchInput("");
                      updateParams({
                        q: null,
                        queue: null,
                        status: null,
                        validation_status: null,
                        client: null,
                        from: null,
                        to: null,
                        delivery_week: null,
                      });
                    }}
                    className="h-9 px-3 rounded-md border border-slate-200 bg-white text-slate-600 text-sm hover:bg-slate-50"
                  >
                    {t("orders.clearFilters")}
                  </button>
                ) : null}
              </form>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleExportExcel}
                  disabled={actionBusy === "excel"}
                  className="bg-white border border-slate-200 text-slate-700 px-3.5 py-2 rounded-md text-sm font-medium hover:bg-slate-50 transition-colors flex items-center gap-2 disabled:opacity-60"
                >
                  <span className="material-icons text-base">file_download</span>
                  {actionBusy === "excel" ? t("orders.exporting") : t("common.exportExcel")}
                </button>
                <button
                  type="button"
                  onClick={handleExportXmlZip}
                  disabled={actionBusy === "xmlzip"}
                  className="bg-white border border-slate-200 text-slate-700 px-3.5 py-2 rounded-md text-sm font-medium hover:bg-slate-50 transition-colors flex items-center gap-2 disabled:opacity-60"
                >
                  <span className="material-icons text-base">folder_zip</span>
                  {actionBusy === "xmlzip" ? t("orders.exporting") : t("orders.exportXmlZip")}
                </button>
                <button type="button" disabled className="bg-primary/40 text-white px-3.5 py-2 rounded-md text-sm font-medium cursor-not-allowed">
                  {t("orders.manualOrder")}
                </button>
              </div>
            </div>
          </div>

          {error ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{error}</div> : null}
          {actionError ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{actionError}</div> : null}

          <div>
            <div
              ref={tableScrollRef}
              onPointerDown={handleTablePointerDown}
              onPointerMove={handleTablePointerMove}
              onPointerUp={handleTablePointerUp}
              onPointerLeave={handleTablePointerUp}
              onPointerCancel={handleTablePointerUp}
              className={`relative bg-surface-light rounded-lg shadow-sm border border-slate-200 overflow-x-auto ${isDraggingTable ? "cursor-grabbing select-none" : "cursor-grab"}`}
            >
              <table className="min-w-full table-fixed text-left text-sm whitespace-nowrap">
                <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-20">
                  <tr>
                    <th className="w-16 px-4 py-3 font-semibold text-slate-500 sticky top-0 left-0 z-10 bg-slate-50 border-r border-slate-200">Nr</th>
                    <th className="w-72 px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50">{t("common.ticketKom")}</th>
                    <th className="w-72 px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50">{t("common.dateTime")}</th>
                    <th className="w-72 px-4 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50">{t("common.customer")}</th>
                    <th className="px-3 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50 w-36">{t("common.status")}</th>
                    <th className="px-3 py-3 font-semibold text-slate-500 sticky top-0 z-10 bg-slate-50 w-32">{t("common.validation")}</th>
                    <th className="px-3 py-3 font-semibold text-slate-500 text-right sticky top-0 z-10 bg-slate-50 w-28">{t("common.actions")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {visibleOrders.map((order, index) => (
                    <tr
                      key={order.id}
                      ref={(node) => {
                        if (node) {
                          orderRowRefs.current.set(order.id, node);
                        } else {
                          orderRowRefs.current.delete(order.id);
                        }
                      }}
                      className="hover:bg-slate-50 transition-colors group"
                    >
                      <td className="px-4 py-3 text-slate-500 border-r border-slate-100 sticky left-0 z-10 bg-surface-light">
                        {(pagination.page - 1) * (pagination.page_size || visibleOrders.length || 0) + index + 1}
                      </td>
                      <td className="w-72 px-4 py-3">
                        <button
                          type="button"
                          onClick={() => {
                            rememberOrderPosition(order.id);
                            navigate(`/orders/${order.id}`);
                          }}
                          className="font-medium text-primary hover:underline block w-full text-left truncate"
                        >
                          {order.ticket_number || order.id}
                        </button>
                        <div className="text-xs text-slate-500 truncate mt-1">{order.kom_nr || "-"}</div>
                      </td>
                      <td className="w-72 px-4 py-3 text-slate-600 truncate">{formatDateTime(order.effective_received_at, lang)}</td>
                      <td className="w-72 px-4 py-3">
                        <div className="font-medium text-slate-900 truncate">{order.kom_name || "-"}</div>
                        <div className="text-xs text-slate-500 truncate">{order.store_name || order.kundennummer || "-"}</div>
                      </td>
                      <td className="px-3 py-2.5"><StatusBadge status={order.status} compact /></td>
                      <td className="px-3 py-2.5"><ValidationBadge status={order.validation_status} compact /></td>
                      <td className="px-3 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-0.5">
                          <button
                            type="button"
                            onClick={() => handleDownloadXml(order.id)}
                            disabled={actionBusy === `download:${order.id}`}
                            className="p-1 text-slate-500 hover:text-primary hover:bg-primary/10 rounded transition-colors disabled:opacity-60"
                            title={t("common.downloadXml")}
                          >
                            <span className="material-icons text-[18px]">download</span>
                          </button>
                          <Link
                            to={`/orders/${order.id}`}
                            onClick={() => rememberOrderPosition(order.id)}
                            className="p-1 text-primary bg-primary/10 rounded transition-colors hover:bg-primary hover:text-white"
                            title={t("common.viewDetails")}
                          >
                            <span className="material-icons text-[18px]">visibility</span>
                          </Link>
                          <button
                            type="button"
                            onClick={() => handleDeleteOrder(order)}
                            disabled={actionBusy === `delete:${order.id}`}
                            className="p-1 text-slate-500 hover:text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-60"
                            title={t("common.delete")}
                          >
                            <span className="material-icons text-[18px]">delete</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!loading && visibleOrders.length === 0 ? (
                    <tr>
                      <td className="px-4 py-10 text-center text-slate-500" colSpan={7}>
                        <div className="space-y-1">
                          <p className="text-sm font-medium text-slate-700">{t("orders.noMatchingOrders")}</p>
                          <p className="text-xs text-slate-500">{t("orders.workspaceSubtitle")}</p>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex items-center justify-between px-2">
              <div className="text-sm text-slate-500">
                {t("orders.showing", {
                  from: visibleOrders.length ? (pagination.page - 1) * (pagination.page_size || visibleOrders.length) + 1 : 0,
                  to: (pagination.page - 1) * (pagination.page_size || 0) + visibleOrders.length,
                  total: queueParam === "today" && !fromDate && !toDate ? (counts.today || visibleOrders.length) : (pagination.total || 0),
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
