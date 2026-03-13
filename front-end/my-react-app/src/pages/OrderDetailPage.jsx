import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { fetchBlob, fetchJson } from "../api/http";
import { AppShell } from "../components/AppShell";
import { StatusBadge } from "../components/StatusBadge";
import { ValidationBadge } from "../components/ValidationBadge";
import { useI18n } from "../i18n/I18nContext";
import { useAuth } from "../auth/useAuth";
import { downloadBlob } from "../utils/download";
import { localizeOperationalMessages, visibleOperationalMessages, isUserFacingWarning } from "../utils/operationalSignals";
import {
  entryValue,
  fieldLabel,
  formatDateTime,
} from "../utils/format";

const PX_STATUS_CONFIG = {
  pending: { label: "Human in the Loop", className: "bg-yellow-50 text-yellow-700 border-yellow-200" },
  control_1_done: { label: "Control 1 Done", className: "bg-sky-50 text-sky-700 border-sky-200" },
  control_2_done: { label: "Control 2 Done", className: "bg-blue-50 text-blue-700 border-blue-200" },
  done: { label: "Done", className: "bg-emerald-50 text-emerald-700 border-emerald-200" },
};

function PxStatusBadge({ status }) {
  const cfg = PX_STATUS_CONFIG[status] || PX_STATUS_CONFIG.pending;
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold border ${cfg.className}`}>
      {cfg.label}
    </span>
  );
}

function buildHeaderDraft(order) {
  const header = order?.header || {};
  const draft = {};
  Object.entries(header).forEach(([field, entry]) => {
    draft[field] = entryValue(entry);
  });
  return draft;
}

function buildItemDraft(order) {
  return (order?.items || []).map((item, index) => {
    const parsedLineNo = Number.parseInt(String(item?.line_no ?? ""), 10);
    return {
      line_no: Number.isFinite(parsedLineNo) && parsedLineNo > 0 ? parsedLineNo : index + 1,
      artikelnummer: entryValue(item.artikelnummer),
      modellnummer: entryValue(item.modellnummer),
      menge: entryValue(item.menge),
      furncloud_id: entryValue(item.furncloud_id),
      __isNew: false,
      __sourceIndex: index,
      __draftId: `existing-${item?.line_no ?? index + 1}-${index}`,
    };
  });
}

function levelClass(level) {
  if (level === "error") {
    return "bg-red-50 border-red-200 text-red-700";
  }
  if (level === "warning") {
    return "bg-amber-50 border-amber-200 text-amber-700";
  }
  return "bg-blue-50 border-blue-200 text-blue-700";
}

function xmlFileLabel(fileName, t) {
  const normalized = String(fileName || "").toLowerCase();
  if (normalized.includes("order info")) {
    return t("orderDetail.xmlFileOrderInfo");
  }
  if (normalized.includes("article info")) {
    return t("orderDetail.xmlFileArticleInfo");
  }
  return fileName;
}

const HIDDEN_HEADER_FIELDS = new Set([
  "seller",
  "iln",
  "human_review_needed",
  "iln_anl",
  "iln_fil",
  "post_case",
  "reply_needed",
  "adressnummer",
]);

export function OrderDetailPage() {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const hasPxPermission = Boolean(user?.can_control_1 || user?.can_control_2 || user?.can_final_control);
  const returnTarget = location.state?.from;
  const openedFromClients = returnTarget?.pathname === "/clients" || location.state?.source === "clients";
  const backToListPath = returnTarget
    ? `${returnTarget.pathname || ""}${returnTarget.search || ""}${returnTarget.hash || ""}`
    : "/orders";
  const detailNavActive = openedFromClients ? "clients" : "orders";
  const backToListLabel = openedFromClients ? t("common.clients") : t("common.orderExtractions");

  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [pxError, setPxError] = useState("");
  const [searchInput, setSearchInput] = useState("");

  const [isEditing, setIsEditing] = useState(false);
  const [startingEdit, setStartingEdit] = useState(false);
  const [editBaselineItemCount, setEditBaselineItemCount] = useState(0);
  const [deletedPersistedIndexes, setDeletedPersistedIndexes] = useState([]);
  const [headerDraft, setHeaderDraft] = useState({});
  const [itemDraft, setItemDraft] = useState([]);

  const loadOrder = useCallback(async () => {
    if (!orderId) {
      return;
    }
    try {
      const payload = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`);
      setOrder(payload);
      setError("");
      if (!isEditing) {
        setHeaderDraft(buildHeaderDraft(payload));
        setItemDraft(buildItemDraft(payload));
      }
    } catch (requestError) {
      setError(requestError.message || t("orderDetail.loadError"));
    } finally {
      setLoading(false);
    }
  }, [isEditing, orderId, t]);

  useEffect(() => {
    if (isEditing) {
      return undefined;
    }

    loadOrder();
    const intervalId = setInterval(loadOrder, 15000);
    return () => clearInterval(intervalId);
  }, [isEditing, loadOrder]);

  const editableHeaderFields = useMemo(
    () => new Set(order?.editable_header_fields || []),
    [order],
  );

  const editableItemFields = useMemo(
    () => new Set(order?.editable_item_fields || []),
    [order],
  );

  const headerRows = useMemo(() => {
    const header = order?.header || {};
    const ordered = [];
    const seen = new Set();
    const isVisibleField = (field) => !HIDDEN_HEADER_FIELDS.has(String(field || "").toLowerCase());

    (order?.editable_header_fields || []).forEach((field) => {
      if (Object.prototype.hasOwnProperty.call(header, field) && isVisibleField(field)) {
        ordered.push([field, header[field]]);
        seen.add(field);
      }
    });

    Object.keys(header)
      .filter((field) => !seen.has(field) && isVisibleField(field))
      .sort()
      .forEach((field) => {
        ordered.push([field, header[field]]);
      });

    return ordered;
  }, [order]);

  const startEditing = async () => {
    if (!orderId || !order?.is_editable || startingEdit) {
      return;
    }
    setStartingEdit(true);
    setError("");
    try {
      const fresh = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`);
      setOrder(fresh);
      setHeaderDraft(buildHeaderDraft(fresh));
      setItemDraft(buildItemDraft(fresh));
      setEditBaselineItemCount((fresh.items || []).length);
      setDeletedPersistedIndexes([]);
      setIsEditing(true);
      setNotice("");
    } catch (requestError) {
      setError(requestError.message || t("orderDetail.loadError"));
    } finally {
      setStartingEdit(false);
    }
  };

  const discardChanges = () => {
    setIsEditing(false);
    setHeaderDraft(buildHeaderDraft(order));
    setItemDraft(buildItemDraft(order));
    setEditBaselineItemCount(0);
    setDeletedPersistedIndexes([]);
    setNotice(t("orderDetail.changesDiscarded"));
  };

  const addItemRow = () => {
    const draftId = `new-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setItemDraft((current) => {
      const maxLineNo = current.reduce((maxValue, item, index) => {
        const parsed = Number.parseInt(String(item?.line_no ?? ""), 10);
        const fallback = index + 1;
        return Math.max(maxValue, Number.isFinite(parsed) && parsed > 0 ? parsed : fallback);
      }, 0);
      return [
        ...current,
        {
          line_no: maxLineNo + 1,
          artikelnummer: "",
          modellnummer: "",
          menge: "",
          furncloud_id: "",
          __isNew: true,
          __draftId: draftId,
        },
      ];
    });
  };

  const removeNewItemRow = (draftId) => {
    setItemDraft((current) => current.filter((item) => item.__draftId !== draftId));
  };

  const removePersistedItemRow = (draftId) => {
    const target = itemDraft.find((item) => item.__draftId === draftId);
    if (!target) {
      return;
    }
    const lineNo = target?.line_no ?? "?";
    const confirmed = window.confirm(t("orderDetail.deleteItemConfirm", { line_no: lineNo }));
    if (!confirmed) {
      return;
    }
    const sourceIndex = Number.parseInt(String(target?.__sourceIndex ?? ""), 10);
    if (Number.isFinite(sourceIndex) && sourceIndex >= 0) {
      setDeletedPersistedIndexes((existing) => (
        existing.includes(sourceIndex) ? existing : [...existing, sourceIndex]
      ));
    }
    setItemDraft((current) => current.filter((item) => item.__draftId !== draftId));
    setNotice(t("orderDetail.itemDeletedNotice"));
  };

  const regenerateXml = async () => {
    if (!orderId) {
      return;
    }
    setBusyAction("regen");
    setNotice("");
    try {
      const result = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}/export-xml`, {
        method: "POST",
      });
      setOrder((current) => (
        current
          ? {
              ...current,
              xml_files: result?.xml_files || current.xml_files,
            }
          : current
      ));
      await loadOrder();
      setNotice(t("orderDetail.xmlRegenerated"));
    } catch (requestError) {
      setError(requestError.message || t("orderDetail.xmlRegenFailed"));
    } finally {
      setBusyAction("");
    }
  };

  const resolveValidation = async () => {
    if (!orderId || !order) {
      return;
    }
    const note = window.prompt(t("orderDetail.resolveValidationPrompt"));
    if (note === null) {
      return;
    }
    const trimmedNote = note.trim();
    if (!trimmedNote) {
      setError(t("orderDetail.resolveValidationNoteRequired"));
      return;
    }
    setBusyAction("resolve-validation");
    setError("");
    setNotice("");
    try {
      const updated = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}/validation/resolve`, {
        method: "POST",
        body: { note: trimmedNote },
      });
      setOrder(updated);
      setNotice(t("orderDetail.validationResolved"));
    } catch (requestError) {
      setError(requestError.message || t("orderDetail.validationResolveFailed"));
    } finally {
      setBusyAction("");
    }
  };

  const downloadFile = async (filename) => {
    setBusyAction(`download:${filename}`);
    setError("");
    try {
      const blob = await fetchBlob(`/api/files/${encodeURIComponent(filename)}`);
      downloadBlob(blob, filename);
    } catch (requestError) {
      setError(requestError.message || t("orderDetail.fileDownloadFailed"));
    } finally {
      setBusyAction("");
    }
  };

  const saveChanges = async () => {
    if (!orderId || !order) {
      return;
    }

    const persistedCount = (order.items || []).length;
    const deletedSet = new Set(deletedPersistedIndexes);
    const headerPatch = {};
    (order.editable_header_fields || []).forEach((field) => {
      const before = entryValue(order.header?.[field]);
      const after = String(headerDraft[field] || "");
      if (after !== before) {
        headerPatch[field] = after;
      }
    });

    const itemPatch = {};
    const persistedRows = itemDraft.filter((item) => !item?.__isNew);
    persistedRows.forEach((draftItem) => {
      const sourceIndex = Number.parseInt(String(draftItem?.__sourceIndex ?? ""), 10);
      if (!Number.isFinite(sourceIndex) || sourceIndex < 0 || sourceIndex >= persistedCount) {
        return;
      }
      if (deletedSet.has(sourceIndex)) {
        return;
      }
      const item = order.items?.[sourceIndex] || {};
      const changes = {};
      (order.editable_item_fields || []).forEach((field) => {
        const before = entryValue(item?.[field]);
        const after = String(draftItem?.[field] || "");
        if (after !== before) {
          changes[field] = after;
        }
      });
      if (Object.keys(changes).length) {
        itemPatch[sourceIndex] = changes;
      }
    });

    const newItems = itemDraft
      .filter((item) => Boolean(item?.__isNew))
      .map((item) => {
        const payload = {};
        (order.editable_item_fields || []).forEach((field) => {
          payload[field] = String(item?.[field] || "");
        });
        return payload;
      })
      .filter((item) => Object.values(item).some((value) => String(value || "").trim() !== ""));

    if (import.meta.env.DEV) {
      console.debug("[OrderDetail] save classification", {
        baseline: editBaselineItemCount,
        persistedCount,
        draftCount: itemDraft.length,
        itemPatchCount: Object.keys(itemPatch).length,
        deletedPersistedCount: deletedPersistedIndexes.length,
        newItemsCount: newItems.length,
      });
    }

    if (
      !Object.keys(headerPatch).length
      && !Object.keys(itemPatch).length
      && deletedPersistedIndexes.length === 0
      && newItems.length === 0
    ) {
      setIsEditing(false);
      setEditBaselineItemCount(0);
      setDeletedPersistedIndexes([]);
      setNotice(t("orderDetail.noChanges"));
      return;
    }

    setBusyAction("save");
    setError("");
    try {
      const updated = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`, {
        method: "PATCH",
        body: {
          header: headerPatch,
          items: itemPatch,
          ...(deletedPersistedIndexes.length ? { deleted_item_indexes: deletedPersistedIndexes } : {}),
          ...(newItems.length ? { new_items: newItems } : {}),
        },
      });
      setOrder(updated);
      setHeaderDraft(buildHeaderDraft(updated));
      setItemDraft(buildItemDraft(updated));
      setIsEditing(false);
      setEditBaselineItemCount(0);
      setDeletedPersistedIndexes([]);
      setNotice(updated.xml_regenerated ? t("orderDetail.savedAndRegenerated") : t("orderDetail.savedNoRegen"));
    } catch (requestError) {
      setError(requestError.message || t("orderDetail.saveFailed"));
    } finally {
      setBusyAction("");
    }
  };

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    const query = searchInput.trim();
    if (!query) {
      navigate("/orders");
      return;
    }
    navigate(`/orders?q=${encodeURIComponent(query)}`);
  };

  const handlePxConfirm = async (level) => {
    if (!orderId) return;
    setBusyAction(`px:${level}`);
    setPxError("");
    try {
      const result = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}/px-confirm`, {
        method: "POST",
        body: { level },
      });
      setOrder((prev) => prev ? { ...prev, px_controls: result.px_controls } : prev);
      setNotice("PX control confirmed.");
    } catch (requestError) {
      setPxError(requestError.message || "Failed to confirm PX control.");
    } finally {
      setBusyAction("");
    }
  };

  if (loading) {
    return (
      <AppShell
        active={detailNavActive}
        headerLeft={(
          <form onSubmit={handleSearchSubmit} className="relative w-full max-w-xl">
            <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">search</span>
            <input
              className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary"
              placeholder={t("orders.searchPlaceholder")}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </form>
        )}
      >
        <div className="flex-1 flex items-center justify-center">{t("common.loadingOrder")}</div>
      </AppShell>
    );
  }

  if (!order) {
    return (
      <AppShell
        active={detailNavActive}
        headerLeft={(
          <form onSubmit={handleSearchSubmit} className="relative w-full max-w-xl">
            <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">search</span>
            <input
              className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary"
              placeholder={t("orders.searchPlaceholder")}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </form>
        )}
      >
        <div className="p-6">
          <Link to={backToListPath} state={returnTarget} className="text-primary hover:underline">{backToListLabel}</Link>
          <p className="mt-4 text-danger">{error || t("orderDetail.notFound")}</p>
        </div>
      </AppShell>
    );
  }

  const displayOrderRef = [
    entryValue(order?.header?.ticket_number),
    entryValue(order?.header?.kom_nr),
    order.order_id,
  ]
    .map((value) => String(value || "").trim())
    .find((value) => value.length > 0) || order.order_id;
  const editButtonDisabled = !order.is_editable || isEditing || startingEdit;
  const editDisabledReason = !order.is_editable
    ? String(order.editability_reason || t("orderDetail.editUnavailableFallback"))
    : "";
  const editDisabledHelpId = editButtonDisabled && editDisabledReason ? "edit-fields-helptext" : undefined;
  const validationStatus = String(order.validation_status || "not_run").toLowerCase();
  const validationIssues = Array.isArray(order.validation_issues) ? order.validation_issues : [];
  const canResolveValidation = validationStatus === "flagged" || validationStatus === "stale";
  const visibleErrors = localizeOperationalMessages(visibleOperationalMessages(order?.errors), t);
  const isSuperAdmin = user?.role === "superadmin";
  const rawWarnings = visibleOperationalMessages(order?.warnings);
  const filteredWarnings = isSuperAdmin
    ? rawWarnings
    : rawWarnings.filter(isUserFacingWarning);
  const visibleWarnings = localizeOperationalMessages(filteredWarnings, t);

  return (
    <AppShell
      active={detailNavActive}
      headerLeft={(
        <form onSubmit={handleSearchSubmit} className="relative w-full max-w-xl">
          <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">search</span>
          <input
            className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary"
            placeholder={t("orders.searchPlaceholder")}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </form>
      )}
    >
      <main className="flex-1 flex flex-col min-w-0">
        <div className={`px-4 py-4 space-y-3 ${isEditing ? "pb-40 md:pb-36" : ""}`}>
          <header className="bg-surface-light border-b border-slate-200 rounded-xl">
            <div className="px-4 py-3 flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <nav className="flex items-center text-xs text-slate-500 gap-2">
              <Link className="hover:text-primary transition-colors" to="/">{t("common.dashboard")}</Link>
              <span className="material-icons text-base">chevron_right</span>
              <Link className="hover:text-primary transition-colors" to={backToListPath} state={returnTarget}>{backToListLabel}</Link>
              <span className="material-icons text-base">chevron_right</span>
              <span className="text-primary font-medium">#{displayOrderRef}</span>
            </nav>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-bold tracking-tight text-slate-900">{t("orderDetail.orderNumber", { id: displayOrderRef })}</h1>
              <StatusBadge status={order.status} />
              <ValidationBadge status={order.validation_status} />
              <span className="text-xs text-slate-500">{t("orderDetail.received", { date: formatDateTime(order.received_at, lang) })}</span>
            </div>
          </div>

            <div className="hidden md:block" />
            </div>
          </header>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className="lg:col-span-8 flex flex-col gap-4">
            {error ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg p-3">{error}</div> : null}
            {notice ? <div className="text-sm text-success bg-success/10 border border-success/20 rounded-lg p-3">{notice}</div> : null}

            <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="bg-slate-50 border-b border-slate-200">
                <table className="w-full text-sm text-left table-fixed">
                  <colgroup>
                    <col className="w-14" />
                    <col className="w-56" />
                    <col className="w-[52%]" />
                  </colgroup>
                  <thead className="text-xs text-slate-500 uppercase">
                    <tr>
                      <th className="px-4 py-2 font-medium tracking-wider sticky left-0 z-10 bg-slate-50 border-r border-slate-200">{t("orderDetail.tableNumber")}</th>
                      <th className="px-4 py-2 font-medium tracking-wider bg-slate-50">{t("common.field")}</th>
                      <th className="px-4 py-2 font-medium tracking-wider bg-slate-50">{t("common.value")}</th>
                    </tr>
                  </thead>
                </table>
              </div>
              <div className="relative">
                <table className="w-full text-sm text-left table-fixed">
                  <colgroup>
                    <col className="w-14" />
                    <col className="w-56" />
                    <col className="w-[52%]" />
                  </colgroup>
                  <tbody className="divide-y divide-slate-200">
                    {headerRows.map(([field, entry], index) => {
                      const editable = editableHeaderFields.has(field) && isEditing;
                      return (
                        <tr key={field}>
                          <td className="px-4 py-2.5 text-slate-500 sticky left-0 z-10 border-r border-slate-200 bg-white">
                            {index + 1}
                          </td>
                          <td className="px-4 py-2.5 font-medium text-slate-900">{fieldLabel(field, t)}</td>
                          <td className="px-4 py-2.5">
                            {editable ? (
                              <input
                                value={headerDraft[field] || ""}
                                onChange={(event) => setHeaderDraft((current) => ({ ...current, [field]: event.target.value }))}
                                className="w-full border border-slate-200 rounded px-2 py-1 text-sm"
                              />
                            ) : (
                              <span className="text-slate-700">{entryValue(entry) || "-"}</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="px-4 py-2.5 border-b border-slate-200 flex items-center justify-between bg-slate-50/60">
                <h2 className="font-bold text-base text-slate-800">{t("orderDetail.lineItems")}</h2>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-500">
                    {(isEditing ? itemDraft.length : (order.items || []).length)} {t("common.items")}
                  </span>
                  {isEditing ? (
                    <button
                      type="button"
                      onClick={addItemRow}
                      className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold text-primary bg-primary/10 border border-primary/20 rounded-md hover:bg-primary/15 transition-colors"
                    >
                      <span className="material-icons text-sm">add</span>
                      {t("orderDetail.addItem")}
                    </button>
                  ) : null}
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="text-xs text-slate-500 uppercase bg-slate-50 border-b border-slate-200 sticky top-0 z-20">
                    <tr>
                      <th className="px-4 py-2 sticky top-0 left-0 z-20 bg-slate-50">#</th>
                      <th className="px-4 py-2 sticky top-0 bg-slate-50">{t("fields.artikelnummer")}</th>
                      <th className="px-4 py-2 sticky top-0 bg-slate-50">{t("fields.modellnummer")}</th>
                      <th className="px-4 py-2 sticky top-0 bg-slate-50">{t("fields.menge")}</th>
                      <th className="px-4 py-2 sticky top-0 bg-slate-50">{t("fields.furncloud_id")}</th>
                      {isEditing ? <th className="px-4 py-2 sticky top-0 bg-slate-50 text-right">{t("common.actions")}</th> : null}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {(isEditing ? itemDraft : (order.items || [])).map((item, index) => (
                      <tr key={item?.__draftId || `${order.order_id}-${index}`}>
                        <td className="px-4 py-2.5 text-slate-500 sticky left-0 z-10 bg-white border-r border-slate-200">
                          {isEditing ? index + 1 : (item?.line_no ?? index + 1)}
                        </td>
                        {["artikelnummer", "modellnummer", "menge", "furncloud_id"].map((field) => (
                          <td key={field} className="px-4 py-2.5">
                            {isEditing && editableItemFields.has(field) ? (
                              <input
                                value={itemDraft[index]?.[field] || ""}
                                onChange={(event) => {
                                  const next = [...itemDraft];
                                  next[index] = {
                                    ...(next[index] || {}),
                                    [field]: event.target.value,
                                  };
                                  setItemDraft(next);
                                }}
                                className="w-full border border-slate-200 rounded px-2 py-1 text-sm"
                              />
                            ) : (
                              <span>{isEditing ? (item?.[field] || "-") : (entryValue(item[field]) || "-")}</span>
                            )}
                          </td>
                        ))}
                        {isEditing ? (
                          <td className="px-4 py-2.5 text-right">
                            {item?.__isNew ? (
                              <button
                                type="button"
                                onClick={() => removeNewItemRow(item.__draftId)}
                                aria-label={t("orderDetail.deleteItemAriaLabel", { line_no: index + 1 })}
                                className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-danger hover:bg-danger/10 rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/60"
                              >
                                <span className="material-icons text-sm">delete</span>
                                {t("orderDetail.deleteItem")}
                              </button>
                            ) : (
                              <button
                                type="button"
                                onClick={() => removePersistedItemRow(item.__draftId)}
                                aria-label={t("orderDetail.deleteItemAriaLabel", { line_no: index + 1 })}
                                className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-danger hover:bg-danger/10 rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/60"
                              >
                                <span className="material-icons text-sm">delete</span>
                                {t("orderDetail.deleteItem")}
                              </button>
                            )}
                          </td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <aside className="lg:col-span-4 flex flex-col gap-4">
            <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm p-3">
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">{t("common.actions")}</h2>
              <div className="grid grid-cols-1 gap-2">
                <button
                  type="button"
                  onClick={regenerateXml}
                  disabled={busyAction === "regen"}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 rounded-md hover:bg-slate-50 hover:text-primary transition-colors disabled:opacity-60"
                >
                  <span className="material-icons text-base">refresh</span>
                  {busyAction === "regen" ? t("orderDetail.regenerating") : t("common.regenerateXml")}
                </button>
                <button
                  type="button"
                  onClick={startEditing}
                  disabled={editButtonDisabled}
                  aria-disabled={editButtonDisabled}
                  aria-describedby={editDisabledHelpId}
                  title={editButtonDisabled && editDisabledReason ? editDisabledReason : ""}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-semibold text-slate-900 bg-primary rounded-md shadow-sm shadow-primary/20 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1"
                >
                  <span className="material-icons text-base">edit</span>
                  {startingEdit ? t("common.loadingOrder") : t("common.editFields")}
                </button>
                {editButtonDisabled && editDisabledReason ? (
                  <p id={editDisabledHelpId} className="text-xs text-slate-600 px-1">
                    {t("orderDetail.editUnavailable", { reason: editDisabledReason })}
                  </p>
                ) : null}
                {order.reply_mailto ? (
                  <a
                    href={order.reply_mailto}
                    target="_blank"
                    rel="noreferrer"
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-semibold text-white bg-slate-900 rounded-md hover:bg-slate-700"
                  >
                    <span className="material-icons text-base">send</span>
                    {t("common.sendReply")}
                  </a>
                ) : null}
              </div>
            </div>
            <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm p-3 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">{t("common.validation")}</h2>
                  <p className="mt-1 text-sm text-slate-600">{order.validation_summary || t("orderDetail.validationNoSummary")}</p>
                </div>
                <ValidationBadge status={validationStatus} />
              </div>
              <div className="grid grid-cols-1 gap-2 text-xs text-slate-500">
                <div>{t("orderDetail.validationCheckedAt", { date: order.validation_checked_at ? formatDateTime(order.validation_checked_at, lang) : "-" })}</div>
                {order.validation_stale_reason ? (
                  <div>{t("orderDetail.validationStaleReason", { reason: order.validation_stale_reason })}</div>
                ) : null}
              </div>
              <div className="space-y-2">
                {validationIssues.length ? validationIssues.map((issue, index) => (
                  <div key={`validation-issue-${index}`} className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
                    <p className="font-semibold">{issue.field_path || t("orderDetail.validationGeneralIssue")}</p>
                    <p className="mt-1">{issue.reason || issue.source_evidence || "-"}</p>
                    <p className="mt-1 text-xs text-rose-700">
                      {t("orderDetail.validationExpected")} {issue.expected_value || "-"} | {t("orderDetail.validationXml")} {issue.xml_value || "-"}
                    </p>
                  </div>
                )) : (
                  <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600">
                    {t("orderDetail.validationIssuesEmpty")}
                  </div>
                )}
              </div>
              {canResolveValidation ? (
                <button
                  type="button"
                  onClick={resolveValidation}
                  disabled={busyAction === "resolve-validation"}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 text-xs font-semibold text-white bg-slate-900 rounded-md hover:bg-slate-700 disabled:opacity-60"
                >
                  <span className="material-icons text-base">verified</span>
                  {busyAction === "resolve-validation" ? t("common.saving") : t("orderDetail.resolveValidation")}
                </button>
              ) : null}
            </div>
            <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden sticky top-6">
              <div className="p-4 border-b border-slate-200 flex items-center justify-between">
                <h2 className="font-bold text-base text-slate-800 flex items-center gap-2">
                  <span className="material-icons text-primary">analytics</span>
                  {t("orderDetail.operationalSignals")}
                </h2>
                <span className="bg-slate-100 text-slate-600 text-xs font-bold px-2 py-1 rounded-full">
                  {t("orderDetail.issues", { count: visibleErrors.length + visibleWarnings.length })}
                </span>
              </div>

              <div className="p-3.5 bg-slate-50 border-b border-slate-200">
                <div className="flex items-center justify-between gap-3 mb-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">{t("common.generatedXml")}</h3>
                  <span className="text-[11px] font-medium text-slate-400">
                    {(order.xml_files || []).length} file{(order.xml_files || []).length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="grid gap-2">
                  {(order.xml_files || []).map((file) => (
                    <button
                      key={file.filename}
                      type="button"
                      onClick={() => downloadFile(file.filename)}
                      disabled={busyAction === `download:${file.filename}`}
                      className="w-full flex items-center justify-between rounded-lg border border-primary/20 bg-white px-3 py-2.5 text-sm font-medium text-slate-800 shadow-sm shadow-primary/5 transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:opacity-60"
                    >
                      <span className="flex items-center gap-2">
                        <span className="material-icons text-[18px] text-primary">description</span>
                        {xmlFileLabel(file.name, t)}
                      </span>
                      <span className="material-icons text-primary text-lg">download</span>
                    </button>
                  ))}
                  {!(order.xml_files || []).length ? (
                    <p className="text-xs text-slate-500">{t("orderDetail.noXmlFiles")}</p>
                  ) : null}
                </div>
              </div>

              <div className="p-4 space-y-3 max-h-[420px] overflow-y-auto">
                {visibleErrors.map((message, index) => (
                  <div key={`error-${index}`} className={`rounded-lg border p-3 ${levelClass("error")}`}>
                    <p className="font-semibold text-xs uppercase tracking-wide mb-1">{t("common.error")}</p>
                    <p className="text-sm">{message}</p>
                  </div>
                ))}

                {visibleWarnings.map((message, index) => (
                  <div key={`warning-${index}`} className={`rounded-lg border p-3 ${levelClass("warning")}`}>
                    <p className="font-semibold text-xs uppercase tracking-wide mb-1">{t("common.warning")}</p>
                    <p className="text-sm">{message}</p>
                  </div>
                ))}

                {!visibleErrors.length && !visibleWarnings.length ? (
                  <div className={`rounded-lg border p-3 ${levelClass("info")}`}>
                    <p className="font-semibold text-xs uppercase tracking-wide mb-1">{t("common.info")}</p>
                    <p className="text-sm">{t("orderDetail.noIssues")}</p>
                  </div>
                ) : null}
              </div>
            </div>
          </aside>
        </div>

        {hasPxPermission && order.px_controls ? (() => {
          const px = order.px_controls;
          const status = px.px_status || "pending";
          const userId = user?.id ? String(user.id) : "";
          const confirmedByMe = [px.control_1_user_id, px.control_2_user_id, px.final_control_user_id]
            .filter(Boolean)
            .map(String)
            .includes(userId);

          const canConfirmControl1 = user?.can_control_1 && status === "pending";
          const canConfirmControl2 = user?.can_control_2 && status === "control_1_done";
          const canConfirmFinal = user?.can_final_control && status === "control_2_done";
          const nextLevel = canConfirmControl1 ? "control_1" : canConfirmControl2 ? "control_2" : canConfirmFinal ? "final_control" : null;
          const nextLevelBlocked = confirmedByMe && nextLevel;

          let waitingReason = null;
          if (!nextLevel && status !== "done") {
            if (status === "pending" && !user?.can_control_1) waitingReason = "Waiting for Control 1";
            else if (status === "control_1_done" && !user?.can_control_2) waitingReason = "Waiting for Control 2";
            else if (status === "control_2_done" && !user?.can_final_control) waitingReason = "Waiting for Final Control";
          }

          return (
            <div className="px-6 pb-6">
              <div className="bg-surface-light border border-slate-200 rounded-xl p-5 shadow-sm space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-base font-semibold text-slate-900">PX Controls</h3>
                  <PxStatusBadge status={status} />
                </div>

                <div className="flex items-center gap-3 text-sm">
                  {["control_1", "control_2", "final_control"].map((lvl, idx) => {
                    const doneMap = { control_1: ["control_1_done", "control_2_done", "done"], control_2: ["control_2_done", "done"], final_control: ["done"] };
                    const isDone = doneMap[lvl].includes(status);
                    const atField = `${lvl}_at`;
                    return (
                      <div key={lvl} className={`flex-1 rounded-lg border p-3 ${isDone ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-white"}`}>
                        <p className={`text-xs font-semibold uppercase tracking-wide mb-1 ${isDone ? "text-emerald-700" : "text-slate-500"}`}>
                          {["Control 1", "Control 2", "Final Control"][idx]}
                        </p>
                        {isDone ? (
                          <p className="text-xs text-emerald-700">{px[atField] ? new Date(px[atField]).toLocaleString() : "Done"}</p>
                        ) : (
                          <p className="text-xs text-slate-400">Pending</p>
                        )}
                      </div>
                    );
                  })}
                </div>

                {pxError && <p className="text-sm text-red-600">{pxError}</p>}

                {status !== "done" && (
                  <div>
                    {nextLevel && !confirmedByMe && (
                      <button
                        type="button"
                        disabled={busyAction === `px:${nextLevel}`}
                        onClick={() => handlePxConfirm(nextLevel)}
                        className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-semibold disabled:opacity-60"
                      >
                        {busyAction === `px:${nextLevel}` ? "Confirming…" : `Confirm ${nextLevel === "control_1" ? "Control 1" : nextLevel === "control_2" ? "Control 2" : "Final Control"}`}
                      </button>
                    )}
                    {nextLevelBlocked && (
                      <p className="text-sm text-amber-600">You have already confirmed a step for this order.</p>
                    )}
                    {waitingReason && (
                      <p className="text-sm text-slate-500">{waitingReason}</p>
                    )}
                  </div>
                )}
                {status === "done" && px.xml_sent_at && (
                  <p className="text-sm text-emerald-600">XML sent on {new Date(px.xml_sent_at).toLocaleString()}</p>
                )}
              </div>
            </div>
          );
        })() : null}
        </div>

      {isEditing ? (
        <div className="fixed bottom-0 left-0 right-0 lg:left-72 bg-white border-t border-primary/50 shadow-[0_-4px_20px_rgba(0,0,0,0.08)] py-4 px-4 md:px-6 z-40">
          <div className="max-w-[1920px] mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="material-icons text-primary animate-pulse">edit_note</span>
              <p className="text-sm font-medium text-slate-700">{t("orderDetail.reviewMode")}</p>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={discardChanges}
                className="px-5 py-2.5 text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
              >
                {t("common.discard")}
              </button>
              <button
                type="button"
                onClick={saveChanges}
                disabled={busyAction === "save"}
                className="px-6 py-2.5 text-sm font-bold text-slate-900 bg-primary rounded-lg shadow-lg shadow-primary/20 transition-all flex items-center gap-2 disabled:opacity-60"
              >
                <span className="material-icons text-lg">check</span>
                {busyAction === "save" ? t("common.saving") : t("common.saveVerify")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      </main>
    </AppShell>
  );
}
