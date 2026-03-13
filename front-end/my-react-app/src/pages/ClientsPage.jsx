import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchJson } from "../api/http";
import {
  ALL_CLIENT_FILTER,
  CLIENT_BRANCHES,
  UNKNOWN_CLIENT_BRANCH_ID,
} from "../constants/clientBranches";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../auth/useAuth";
import { useI18n } from "../i18n/I18nContext";
import { formatDateTime } from "../utils/format";
import { normalizeBranchId } from "../utils/clientClassifier";

const ORDER_PAGE_SIZE = 50;
const REFRESH_INTERVAL_MS = 60_000;

function isAbortError(error) {
  return error?.name === "AbortError";
}

function buildInitialClientCounts({ visibleKnownBranchIds = [], includeUnknownBranch = false, includeAll = true } = {}) {
  const counts = {};
  if (includeAll) {
    counts[ALL_CLIENT_FILTER] = 0;
  }
  visibleKnownBranchIds.forEach((branchId) => {
    counts[branchId] = 0;
  });
  if (includeUnknownBranch) {
    counts[UNKNOWN_CLIENT_BRANCH_ID] = 0;
  }
  return counts;
}

export function ClientsPage() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const isAdminLike = user?.role === "admin" || user?.role === "superadmin";
  const assignedClientBranchIds = useMemo(() => {
    const assigned = Array.isArray(user?.client_branches) ? user.client_branches : [];
    return new Set(
      assigned
        .map((branchId) => String(branchId || "").trim().toLowerCase())
        .filter(Boolean),
    );
  }, [user?.client_branches]);
  const visibleKnownBranches = useMemo(() => {
    if (isAdminLike) return CLIENT_BRANCHES;
    return CLIENT_BRANCHES.filter((branch) => assignedClientBranchIds.has(branch.id));
  }, [assignedClientBranchIds, isAdminLike]);
  const visibleKnownBranchIds = useMemo(
    () => visibleKnownBranches.map((branch) => branch.id),
    [visibleKnownBranches],
  );
  const includeUnknownBranch = isAdminLike || assignedClientBranchIds.has(UNKNOWN_CLIENT_BRANCH_ID);
  const visibleBranchCount = visibleKnownBranchIds.length + (includeUnknownBranch ? 1 : 0);
  const showAllFilter = isAdminLike || visibleBranchCount > 1;
  const defaultNonAllFilterId = useMemo(() => {
    if (visibleKnownBranchIds.length > 0) {
      return visibleKnownBranchIds[0];
    }
    if (includeUnknownBranch) {
      return UNKNOWN_CLIENT_BRANCH_ID;
    }
    return ALL_CLIENT_FILTER;
  }, [includeUnknownBranch, visibleKnownBranchIds]);
  const allowedFilterIds = useMemo(() => {
    const ids = new Set(visibleKnownBranchIds);
    if (includeUnknownBranch) {
      ids.add(UNKNOWN_CLIENT_BRANCH_ID);
    }
    if (showAllFilter) {
      ids.add(ALL_CLIENT_FILTER);
    }
    return ids;
  }, [includeUnknownBranch, showAllFilter, visibleKnownBranchIds]);

  const [orders, setOrders] = useState([]);
  const [pagination, setPagination] = useState({
    page: 1,
    page_size: ORDER_PAGE_SIZE,
    total: 0,
    total_pages: 1,
  });
  const [clientCounts, setClientCounts] = useState(() =>
    buildInitialClientCounts({ visibleKnownBranchIds, includeUnknownBranch, includeAll: showAllFilter }),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchInput, setSearchInput] = useState(searchParams.get("q") || "");

  const activeRequestRef = useRef(null);

  const qParam = searchParams.get("q") || "";
  const selectedClientParam = searchParams.get("client") || ALL_CLIENT_FILTER;
  const pageParam = Math.max(1, Number.parseInt(searchParams.get("page") || "1", 10) || 1);

  useEffect(() => {
    setSearchInput(qParam);
  }, [qParam]);

  const selectedClient = useMemo(() => {
    const normalized = String(selectedClientParam || "").trim().toLowerCase();
    if (!normalized) {
      return showAllFilter ? ALL_CLIENT_FILTER : defaultNonAllFilterId;
    }
    if (allowedFilterIds.has(normalized)) {
      return normalized;
    }
    return showAllFilter ? ALL_CLIENT_FILTER : defaultNonAllFilterId;
  }, [allowedFilterIds, defaultNonAllFilterId, selectedClientParam, showAllFilter]);

  useEffect(() => {
    const rawClient = searchParams.get("client");
    if (!showAllFilter && defaultNonAllFilterId !== ALL_CLIENT_FILTER && rawClient !== defaultNonAllFilterId) {
      const next = new URLSearchParams(searchParams);
      next.set("client", defaultNonAllFilterId);
      next.delete("page");
      setSearchParams(next);
      return;
    }
    if (!rawClient) return;
    const normalized = String(rawClient).trim().toLowerCase();
    if (allowedFilterIds.has(normalized)) {
      return;
    }
    const next = new URLSearchParams(searchParams);
    next.delete("client");
    next.delete("page");
    setSearchParams(next);
  }, [allowedFilterIds, defaultNonAllFilterId, searchParams, setSearchParams, showAllFilter]);

  useEffect(() => {
    setClientCounts(buildInitialClientCounts({ visibleKnownBranchIds, includeUnknownBranch, includeAll: showAllFilter }));
  }, [includeUnknownBranch, showAllFilter, visibleKnownBranchIds]);

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
    if (activeRequestRef.current) {
      activeRequestRef.current.abort();
    }

    const controller = new AbortController();
    activeRequestRef.current = controller;
    setLoading(true);

    try {
      const ordersQuery = new URLSearchParams();
      if (qParam.trim()) {
        ordersQuery.set("q", qParam.trim());
      }
      if (selectedClient !== ALL_CLIENT_FILTER && selectedClient) {
        ordersQuery.set("client", selectedClient);
      }
      ordersQuery.set("page", String(pageParam));
      ordersQuery.set("page_size", String(ORDER_PAGE_SIZE));

      const [ordersPayload, countsPayload] = await Promise.all([
        fetchJson(`/api/orders?${ordersQuery.toString()}`, { signal: controller.signal }),
        fetchJson("/api/clients/counts", { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;

      const rows = Array.isArray(ordersPayload?.orders) ? ordersPayload.orders : [];
      setOrders(
        rows.map((row) => ({
          ...row,
          branchId: normalizeBranchId(row?.extraction_branch),
        })),
      );

      const apiPagination = ordersPayload?.pagination || {};
      setPagination({
        page: Number(apiPagination.page || pageParam || 1),
        page_size: Number(apiPagination.page_size || ORDER_PAGE_SIZE),
        total: Number(apiPagination.total || 0),
        total_pages: Number(apiPagination.total_pages || 1),
      });

      const nextCounts = buildInitialClientCounts({ visibleKnownBranchIds, includeUnknownBranch, includeAll: showAllFilter });
      const rawCounts = countsPayload?.counts && typeof countsPayload.counts === "object" ? countsPayload.counts : {};
      Object.entries(rawCounts).forEach(([branch, value]) => {
        const normalizedBranch = normalizeBranchId(branch);
        if (!Object.prototype.hasOwnProperty.call(nextCounts, normalizedBranch)) {
          return;
        }
        nextCounts[normalizedBranch] = Number(value || 0);
      });
      if (showAllFilter) {
        nextCounts[ALL_CLIENT_FILTER] =
          Number(countsPayload?.total || 0) || Object.values(nextCounts).reduce((sum, value) => sum + Number(value || 0), 0);
      }
      setClientCounts(nextCounts);

      setError("");
    } catch (requestError) {
      if (isAbortError(requestError) || controller.signal.aborted) return;
      setError(requestError.message || t("clients.loadError"));
    } finally {
      if (activeRequestRef.current === controller) {
        activeRequestRef.current = null;
      }
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [includeUnknownBranch, pageParam, qParam, selectedClient, showAllFilter, t, visibleKnownBranchIds]);

  useEffect(() => {
    loadOrders();
    const intervalId = setInterval(loadOrders, REFRESH_INTERVAL_MS);
    return () => {
      clearInterval(intervalId);
      if (activeRequestRef.current) {
        activeRequestRef.current.abort();
      }
    };
  }, [loadOrders]);

  const branchLabels = useMemo(() => {
    const labels = {
      [UNKNOWN_CLIENT_BRANCH_ID]: t("clients.branch.unknown"),
    };
    CLIENT_BRANCHES.forEach((branch) => {
      labels[branch.id] = t(branch.labelKey, null, branch.defaultLabel);
    });
    return labels;
  }, [t]);

  const filterOptions = useMemo(() => {
    const options = [];
    if (showAllFilter) {
      options.push({
        id: ALL_CLIENT_FILTER,
        label: t("clients.filterAll"),
        count: clientCounts[ALL_CLIENT_FILTER] || 0,
      });
    }
    options.push(
      ...visibleKnownBranches.map((branch) => ({
        id: branch.id,
        label: branchLabels[branch.id],
        count: clientCounts[branch.id] || 0,
      })),
    );
    if (includeUnknownBranch) {
      options.push({
        id: UNKNOWN_CLIENT_BRANCH_ID,
        label: branchLabels[UNKNOWN_CLIENT_BRANCH_ID],
        count: clientCounts[UNKNOWN_CLIENT_BRANCH_ID] || 0,
      });
    }
    return options;
  }, [branchLabels, clientCounts, includeUnknownBranch, showAllFilter, t, visibleKnownBranches]);

  const hasPrev = pagination.page > 1;
  const hasNext = pagination.page < pagination.total_pages;
  const hasActiveFilters = qParam.trim().length > 0 || (showAllFilter && selectedClient !== ALL_CLIENT_FILTER);

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    const query = searchInput.trim();
    updateParams({ q: query || null });
  };

  return (
    <AppShell
      active="clients"
      headerLeft={(
        <form onSubmit={handleSearchSubmit} className="relative w-full max-w-xl">
          <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">search</span>
          <input
            className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary"
            placeholder={t("clients.searchPlaceholder")}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </form>
      )}
    >
      <main className="flex-1 flex flex-col min-w-0">
        <div className="w-full px-6 py-6 space-y-6">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-bold text-slate-900">{t("clients.title")}</h1>
            <p className="text-sm text-slate-500">{t("clients.showingCount", { count: pagination.total || 0 })}</p>
          </div>

          {error ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{error}</div> : null}

          <section className="bg-surface-light border border-slate-200 rounded-xl p-4 shadow-sm">
            <p className="text-xs tracking-[0.2em] text-slate-500 mb-3">{t("clients.filterLabel")}</p>
            <div className="flex flex-wrap gap-2">
              {filterOptions.map((option) => {
                const active = selectedClient === option.id;
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() =>
                      updateParams({
                        client: option.id === ALL_CLIENT_FILTER ? null : active ? null : option.id,
                      })
                    }
                    className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm border transition-colors ${
                      active
                        ? "bg-primary text-white border-primary"
                        : "bg-white text-slate-700 border-slate-200 hover:border-primary/40 hover:text-primary"
                    }`}
                  >
                    <span>{option.label}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${active ? "bg-white/20" : "bg-slate-100 text-slate-600"}`}>
                      {option.count}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <div className="relative bg-surface-light rounded-lg shadow-sm border border-slate-200 overflow-x-auto overflow-y-auto max-h-[70vh]">
            <table className="w-full table-fixed text-left text-sm whitespace-nowrap">
              <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-20">
                <tr>
                  <th className="px-4 py-3 font-semibold text-slate-500 w-[56px]">Nr.</th>
                  <th className="px-4 py-3 font-semibold text-slate-500 w-[180px]">
                    {t("common.orderId")}
                  </th>
                  <th className="px-4 py-3 font-semibold text-slate-500">{t("clients.tableClient")}</th>
                  <th className="px-4 py-3 font-semibold text-slate-500">{t("common.kommissionNumber")}</th>
                  <th className="px-4 py-3 font-semibold text-slate-500">{t("common.dateTime")}</th>
                  <th className="px-4 py-3 font-semibold text-slate-500 w-[300px]">{t("common.customer")}</th>
                  <th className="px-4 py-3 font-semibold text-slate-500">{t("common.status")}</th>
                  <th className="px-4 py-3 font-semibold text-slate-500 text-right">{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (
                  <tr>
                    <td className="px-4 py-8 text-center text-slate-500" colSpan={8}>
                      {t("clients.loading")}
                    </td>
                  </tr>
                ) : orders.length > 0 ? (
                  orders.map((order, index) => {
                    const branchId = normalizeBranchId(order?.branchId);
                    return (
                      <tr key={order.id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-4 py-3 w-[56px] text-slate-500">
                          {(pagination.page - 1) * (pagination.page_size || ORDER_PAGE_SIZE) + index + 1}
                        </td>
                        <td className="px-4 py-3 w-[180px] overflow-hidden">
                          <Link
                            to={`/orders/${order.id}`}
                            className="block max-w-full truncate font-medium text-primary hover:underline"
                            title={order.ticket_number || order.id}
                          >
                            {order.ticket_number || order.id}
                          </Link>
                        </td>
                        <td className="px-4 py-3">
                          <div className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">
                            {branchLabels[branchId] || branchLabels[UNKNOWN_CLIENT_BRANCH_ID]}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-slate-700">{order.kom_nr || "-"}</td>
                        <td className="px-4 py-3 text-slate-600">
                          {formatDateTime(order.effective_received_at || order.received_at, lang)}
                        </td>
                        <td className="px-4 py-3 w-[300px] overflow-hidden">
                          <div className="max-w-full">
                            <div className="truncate font-medium text-slate-900" title={order.kom_name || "-"}>
                              {order.kom_name || "-"}
                            </div>
                            <div className="truncate text-xs text-slate-500" title={order.store_name || order.kundennummer || "-"}>
                              {order.store_name || order.kundennummer || "-"}
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={order.status} />
                        </td>
                        <td className="px-4 py-3 text-right">
                          <Link
                            to={`/orders/${order.id}`}
                            className="inline-flex items-center gap-1 p-1.5 text-primary bg-primary/10 rounded transition-colors hover:bg-primary hover:text-white"
                            title={t("common.viewDetails")}
                          >
                            <span className="material-icons text-lg">visibility</span>
                          </Link>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td className="px-4 py-8 text-center text-slate-500" colSpan={8}>
                      {!hasActiveFilters && (clientCounts[ALL_CLIENT_FILTER] || 0) === 0
                        ? t("clients.noOrders")
                        : t("clients.noMatchingOrders")}
                    </td>
                  </tr>
                )}
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
      </main>
    </AppShell>
  );
}
