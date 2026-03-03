import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchJson } from "../api/http";
import {
  ALL_CLIENT_FILTER,
  CLIENT_BRANCHES,
  KNOWN_CLIENT_BRANCH_IDS,
  UNKNOWN_CLIENT_BRANCH_ID,
} from "../constants/clientBranches";
import { AppShell } from "../components/AppShell";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { StatusBadge } from "../components/StatusBadge";
import { useI18n } from "../i18n/I18nContext";
import { formatDateTime } from "../utils/format";
import { extractBranchFromWarnings, normalizeBranchId } from "../utils/clientClassifier";

const ORDER_PAGE_SIZE = 500;
const DETAIL_REQUEST_CONCURRENCY = 8;
const REFRESH_INTERVAL_MS = 60_000;

function isAbortError(error) {
  return error?.name === "AbortError";
}

async function fetchAllOrderSummaries(signal) {
  const firstPage = await fetchJson(`/api/orders?page=1&page_size=${ORDER_PAGE_SIZE}`, { signal });
  const firstOrders = Array.isArray(firstPage?.orders) ? firstPage.orders : [];
  const totalPages = Math.max(1, Number(firstPage?.pagination?.total_pages || 1));

  const allOrders = [...firstOrders];
  if (totalPages > 1) {
    const requests = [];
    for (let page = 2; page <= totalPages; page += 1) {
      requests.push(fetchJson(`/api/orders?page=${page}&page_size=${ORDER_PAGE_SIZE}`, { signal }));
    }
    const pages = await Promise.all(requests);
    pages.forEach((payload) => {
      if (Array.isArray(payload?.orders)) {
        allOrders.push(...payload.orders);
      }
    });
  }

  const seen = new Set();
  const deduped = [];
  for (const order of allOrders) {
    const id = String(order?.id || "").trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    deduped.push(order);
  }

  return deduped;
}

async function classifyOrdersByBranch(orderSummaries, signal) {
  const classified = new Array(orderSummaries.length);
  let nextIndex = 0;

  const worker = async () => {
    while (true) {
      if (signal.aborted) return;

      const index = nextIndex;
      nextIndex += 1;
      if (index >= orderSummaries.length) return;

      const summary = orderSummaries[index];
      const orderId = String(summary?.id || "");
      let branchId = UNKNOWN_CLIENT_BRANCH_ID;

      if (orderId) {
        try {
          const detail = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`, { signal });
          branchId = extractBranchFromWarnings(detail?.warnings);
        } catch (error) {
          if (isAbortError(error) || signal.aborted) return;
          branchId = UNKNOWN_CLIENT_BRANCH_ID;
        }
      }

      classified[index] = {
        ...summary,
        branchId: normalizeBranchId(branchId),
      };
    }
  };

  const workerCount = Math.min(DETAIL_REQUEST_CONCURRENCY, orderSummaries.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  return classified.filter(Boolean);
}

export function ClientsPage() {
  const { t, lang } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();

  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchInput, setSearchInput] = useState(searchParams.get("q") || "");

  const activeRequestRef = useRef(null);

  const qParam = searchParams.get("q") || "";
  const selectedClientParam = searchParams.get("client") || ALL_CLIENT_FILTER;

  useEffect(() => {
    setSearchInput(qParam);
  }, [qParam]);

  const selectedClient = useMemo(() => {
    const normalized = String(selectedClientParam || "").trim().toLowerCase();
    if (!normalized || normalized === ALL_CLIENT_FILTER) return ALL_CLIENT_FILTER;
    if (normalized === UNKNOWN_CLIENT_BRANCH_ID) return UNKNOWN_CLIENT_BRANCH_ID;
    return KNOWN_CLIENT_BRANCH_IDS.has(normalized) ? normalized : ALL_CLIENT_FILTER;
  }, [selectedClientParam]);

  const updateParams = useCallback(
    (updates) => {
      const next = new URLSearchParams(searchParams);
      Object.entries(updates).forEach(([key, value]) => {
        if (value === null || value === undefined || value === "") {
          next.delete(key);
        } else {
          next.set(key, String(value));
        }
      });
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
      const summaries = await fetchAllOrderSummaries(controller.signal);
      const classified = await classifyOrdersByBranch(summaries, controller.signal);
      if (controller.signal.aborted) return;

      setOrders(classified);
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
  }, [t]);

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

  const clientCounts = useMemo(() => {
    const counts = {
      [ALL_CLIENT_FILTER]: orders.length,
      [UNKNOWN_CLIENT_BRANCH_ID]: 0,
    };
    CLIENT_BRANCHES.forEach((branch) => {
      counts[branch.id] = 0;
    });

    orders.forEach((order) => {
      const branchId = normalizeBranchId(order?.branchId);
      counts[branchId] = (counts[branchId] || 0) + 1;
    });

    return counts;
  }, [orders]);

  const searchQuery = qParam.trim().toLowerCase();

  const filteredOrders = useMemo(() => {
    return orders.filter((order) => {
      const branchId = normalizeBranchId(order?.branchId);
      if (selectedClient !== ALL_CLIENT_FILTER && branchId !== selectedClient) {
        return false;
      }

      if (!searchQuery) return true;
      const searchable = [
        order?.ticket_number,
        order?.id,
        order?.kom_nr,
        order?.kom_name,
        order?.store_name,
        order?.kundennummer,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return searchable.includes(searchQuery);
    });
  }, [orders, searchQuery, selectedClient]);

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
    return [
      {
        id: ALL_CLIENT_FILTER,
        label: t("clients.filterAll"),
        count: clientCounts[ALL_CLIENT_FILTER] || 0,
      },
      ...CLIENT_BRANCHES.map((branch) => ({
        id: branch.id,
        label: branchLabels[branch.id],
        count: clientCounts[branch.id] || 0,
      })),
      {
        id: UNKNOWN_CLIENT_BRANCH_ID,
        label: branchLabels[UNKNOWN_CLIENT_BRANCH_ID],
        count: clientCounts[UNKNOWN_CLIENT_BRANCH_ID] || 0,
      },
    ];
  }, [branchLabels, clientCounts, t]);

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    const query = searchInput.trim();
    updateParams({ q: query || null });
  };

  return (
    <AppShell active="clients">
      <main className="flex-1 flex flex-col min-w-0">
        <div className="sticky top-0 z-30">
          <header className="h-16 bg-surface-light border-b border-slate-200 flex items-center justify-between px-6">
            <form onSubmit={handleSearchSubmit} className="relative w-full max-w-xl">
              <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">search</span>
              <input
                className="w-full bg-slate-50 border-none rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary"
                placeholder={t("clients.searchPlaceholder")}
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </form>
            <div className="flex items-center gap-3 ml-4">
              <LanguageSwitcher compact className="hidden md:flex" />
            </div>
          </header>
        </div>

        <div className="w-full px-6 py-6 space-y-6">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-bold text-slate-900">{t("clients.title")}</h1>
            <p className="text-sm text-slate-500">{t("clients.pageSubtitle", null, t("clients.subtitle"))}</p>
            <p className="text-sm text-slate-500">{t("clients.showingCount", { count: filteredOrders.length })}</p>
          </div>

          {error ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{error}</div> : null}

          <section className="bg-surface-light border border-slate-200 rounded-xl p-4 shadow-sm">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500 mb-3">{t("clients.filterLabel")}</p>
            <div className="flex flex-wrap gap-2">
              {filterOptions.map((option) => {
                const active = selectedClient === option.id;
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => updateParams({ client: option.id === ALL_CLIENT_FILTER ? null : option.id })}
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
                  <th className="px-4 py-3 font-semibold text-slate-500 w-[56px]">Nr</th>
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
                ) : filteredOrders.length > 0 ? (
                  filteredOrders.map((order, index) => {
                    const branchId = normalizeBranchId(order?.branchId);
                    return (
                      <tr key={order.id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-4 py-3 w-[56px] text-slate-500">{index + 1}</td>
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
                      {orders.length === 0 ? t("clients.noOrders") : t("clients.noMatchingOrders")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
