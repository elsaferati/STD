
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchBlob, fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { downloadBlob } from "../utils/download";
import {
  entryConfidence,
  entrySource,
  entryValue,
  fieldLabel,
  formatConfidence,
  formatDateTime,
} from "../utils/format";

function buildHeaderDraft(order) {
  const header = order?.header || {};
  const draft = {};
  Object.entries(header).forEach(([field, entry]) => {
    draft[field] = entryValue(entry);
  });
  return draft;
}

function buildItemDraft(order) {
  return (order?.items || []).map((item) => ({
    artikelnummer: entryValue(item.artikelnummer),
    modellnummer: entryValue(item.modellnummer),
    menge: entryValue(item.menge),
    furncloud_id: entryValue(item.furncloud_id),
  }));
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

export function OrderDetailPage() {
  const { token } = useAuth();
  const { orderId } = useParams();

  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyAction, setBusyAction] = useState("");

  const [isEditing, setIsEditing] = useState(false);
  const [highlightLowConfidence, setHighlightLowConfidence] = useState(false);
  const [headerDraft, setHeaderDraft] = useState({});
  const [itemDraft, setItemDraft] = useState([]);

  const loadOrder = useCallback(async () => {
    if (!orderId) {
      return;
    }
    try {
      const payload = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`, { token });
      setOrder(payload);
      setError("");
      if (!isEditing) {
        setHeaderDraft(buildHeaderDraft(payload));
        setItemDraft(buildItemDraft(payload));
      }
    } catch (requestError) {
      setError(requestError.message || "Failed to load order details.");
    } finally {
      setLoading(false);
    }
  }, [isEditing, orderId, token]);

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

    (order?.editable_header_fields || []).forEach((field) => {
      if (Object.prototype.hasOwnProperty.call(header, field)) {
        ordered.push([field, header[field]]);
        seen.add(field);
      }
    });

    Object.keys(header)
      .filter((field) => !seen.has(field))
      .sort()
      .forEach((field) => {
        ordered.push([field, header[field]]);
      });

    return ordered;
  }, [order]);

  const startEditing = () => {
    if (!order?.is_editable) {
      return;
    }
    setIsEditing(true);
    setHeaderDraft(buildHeaderDraft(order));
    setItemDraft(buildItemDraft(order));
    setNotice("");
  };

  const discardChanges = () => {
    setIsEditing(false);
    setHeaderDraft(buildHeaderDraft(order));
    setItemDraft(buildItemDraft(order));
    setNotice("Changes discarded.");
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
        token,
      });
      setOrder((current) => (
        current
          ? {
              ...current,
              xml_files: result?.xml_files || current.xml_files,
            }
          : current
      ));
      setNotice("XML regenerated.");
    } catch (requestError) {
      setError(requestError.message || "XML regeneration failed.");
    } finally {
      setBusyAction("");
    }
  };

  const downloadFile = async (filename) => {
    setBusyAction(`download:${filename}`);
    setError("");
    try {
      const blob = await fetchBlob(`/api/files/${encodeURIComponent(filename)}`, { token });
      downloadBlob(blob, filename);
    } catch (requestError) {
      setError(requestError.message || "File download failed.");
    } finally {
      setBusyAction("");
    }
  };

  const saveChanges = async () => {
    if (!orderId || !order) {
      return;
    }

    const headerPatch = {};
    (order.editable_header_fields || []).forEach((field) => {
      const before = entryValue(order.header?.[field]);
      const after = String(headerDraft[field] || "");
      if (after !== before) {
        headerPatch[field] = after;
      }
    });

    const itemPatch = {};
    (order.items || []).forEach((item, index) => {
      const changes = {};
      (order.editable_item_fields || []).forEach((field) => {
        const before = entryValue(item?.[field]);
        const after = String(itemDraft[index]?.[field] || "");
        if (after !== before) {
          changes[field] = after;
        }
      });
      if (Object.keys(changes).length) {
        itemPatch[index] = changes;
      }
    });

    if (!Object.keys(headerPatch).length && !Object.keys(itemPatch).length) {
      setIsEditing(false);
      setNotice("No changes to save.");
      return;
    }

    setBusyAction("save");
    setError("");
    try {
      const updated = await fetchJson(`/api/orders/${encodeURIComponent(orderId)}`, {
        method: "PATCH",
        token,
        body: {
          header: headerPatch,
          items: itemPatch,
        },
      });
      setOrder(updated);
      setHeaderDraft(buildHeaderDraft(updated));
      setItemDraft(buildItemDraft(updated));
      setIsEditing(false);
      setNotice(updated.xml_regenerated ? "Saved and XML regenerated." : "Saved. XML regeneration did not complete.");
    } catch (requestError) {
      setError(requestError.message || "Save failed.");
    } finally {
      setBusyAction("");
    }
  };

  if (loading) {
    return <div className="min-h-screen bg-background-light font-display flex items-center justify-center">Loading order...</div>;
  }

  if (!order) {
    return (
      <div className="min-h-screen bg-background-light font-display p-6">
        <Link to="/orders" className="text-primary hover:underline">Back to Orders</Link>
        <p className="mt-4 text-danger">{error || "Order not found."}</p>
      </div>
    );
  }

  return (
    <div className="bg-background-light text-slate-800 min-h-screen flex flex-col font-display">
      <header className="bg-surface-light border-b border-slate-200 sticky top-0 z-30">
        <div className="px-6 py-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex flex-col gap-1">
            <nav className="flex items-center text-xs text-slate-500 gap-2">
              <Link className="hover:text-primary transition-colors" to="/">Dashboard</Link>
              <span className="material-icons text-base">chevron_right</span>
              <Link className="hover:text-primary transition-colors" to="/orders">Order Extractions</Link>
              <span className="material-icons text-base">chevron_right</span>
              <span className="text-primary font-medium">#{order.order_id}</span>
            </nav>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl font-bold tracking-tight text-slate-900">Order #{order.order_id}</h1>
              {order.is_editable ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-warning/20 text-warning border border-warning/30">
                  <span className="w-1.5 h-1.5 rounded-full bg-warning animate-pulse" />
                  Human Review
                </span>
              ) : null}
              <span className="text-xs text-slate-500">Received {formatDateTime(order.received_at)}</span>
            </div>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <button
              type="button"
              onClick={regenerateXml}
              disabled={busyAction === "regen"}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:text-primary transition-colors disabled:opacity-60"
            >
              <span className="material-icons text-lg">refresh</span>
              {busyAction === "regen" ? "Regenerating..." : "Regenerate XML"}
            </button>
            <button
              type="button"
              onClick={startEditing}
              disabled={!order.is_editable || isEditing}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-900 bg-primary rounded-lg shadow-lg shadow-primary/20 disabled:opacity-50"
            >
              <span className="material-icons text-lg">edit</span>
              Edit Fields
            </button>
            {order.reply_mailto ? (
              <a
                href={order.reply_mailto}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-slate-900 rounded-lg hover:bg-slate-700"
              >
                <span className="material-icons text-lg">send</span>
                Send Reply
              </a>
            ) : null}
          </div>
        </div>
      </header>

      <main className="flex-1 p-6 grid grid-cols-1 lg:grid-cols-12 gap-6 max-w-[1920px] mx-auto w-full">
        <div className="lg:col-span-8 flex flex-col gap-6">
          {error ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg p-3">{error}</div> : null}
          {notice ? <div className="text-sm text-success bg-success/10 border border-success/20 rounded-lg p-3">{notice}</div> : null}

          <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50/60">
              <h2 className="font-bold text-lg text-slate-800">Header Information</h2>
              <button
                type="button"
                onClick={() => setHighlightLowConfidence((value) => !value)}
                className={`text-xs px-3 py-1 rounded border ${highlightLowConfidence ? "bg-primary/10 border-primary/30 text-primary" : "bg-white border-slate-200 text-slate-600"}`}
              >
                Highlight Low Conf.
              </button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-slate-500 uppercase bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th className="px-6 py-3 font-medium tracking-wider">Field</th>
                    <th className="px-6 py-3 font-medium tracking-wider">Value</th>
                    <th className="px-6 py-3 font-medium tracking-wider">Source</th>
                    <th className="px-6 py-3 font-medium tracking-wider text-right">Confidence</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {headerRows.map(([field, entry]) => {
                    const confidence = entryConfidence(entry);
                    const lowConfidence = confidence !== null && confidence < 0.9;
                    const editable = editableHeaderFields.has(field) && isEditing;
                    return (
                      <tr key={field} className={highlightLowConfidence && lowConfidence ? "bg-warning/10" : ""}>
                        <td className="px-6 py-4 font-medium text-slate-900">{fieldLabel(field)}</td>
                        <td className="px-6 py-4">
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
                        <td className="px-6 py-4 text-slate-500">{entrySource(entry)}</td>
                        <td className="px-6 py-4 text-right">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${lowConfidence ? "bg-warning/20 text-warning" : "bg-primary/10 text-primary-dark"}`}>
                            {formatConfidence(confidence)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between bg-slate-50/60">
              <h2 className="font-bold text-lg text-slate-800">Line Items</h2>
              <span className="text-xs text-slate-500">{(order.items || []).length} items</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-slate-500 uppercase bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th className="px-6 py-3">#</th>
                    <th className="px-6 py-3">Artikelnummer</th>
                    <th className="px-6 py-3">Modellnummer</th>
                    <th className="px-6 py-3">Menge</th>
                    <th className="px-6 py-3">Furncloud ID</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {(order.items || []).map((item, index) => (
                    <tr key={`${order.order_id}-${index}`}>
                      <td className="px-6 py-4 text-slate-500">{item.line_no ?? index + 1}</td>
                      {["artikelnummer", "modellnummer", "menge", "furncloud_id"].map((field) => (
                        <td key={field} className="px-6 py-4">
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
                            <span>{entryValue(item[field]) || "-"}</span>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <aside className="lg:col-span-4 flex flex-col gap-6">
          <div className="bg-surface-light rounded-xl border border-slate-200 shadow-sm overflow-hidden sticky top-24">
            <div className="p-5 border-b border-slate-200 flex items-center justify-between">
              <h2 className="font-bold text-lg text-slate-800 flex items-center gap-2">
                <span className="material-icons text-primary">analytics</span>
                Operational Signals
              </h2>
              <span className="bg-slate-100 text-slate-600 text-xs font-bold px-2 py-1 rounded-full">
                {(order.errors || []).length + (order.warnings || []).length} issues
              </span>
            </div>

            <div className="p-5 space-y-3 max-h-[420px] overflow-y-auto">
              {(order.errors || []).map((message, index) => (
                <div key={`error-${index}`} className={`rounded-lg border p-3 ${levelClass("error")}`}>
                  <p className="font-semibold text-xs uppercase tracking-wide mb-1">Error</p>
                  <p className="text-sm">{message}</p>
                </div>
              ))}

              {(order.warnings || []).map((message, index) => (
                <div key={`warning-${index}`} className={`rounded-lg border p-3 ${levelClass("warning")}`}>
                  <p className="font-semibold text-xs uppercase tracking-wide mb-1">Warning</p>
                  <p className="text-sm">{message}</p>
                </div>
              ))}

              {!(order.errors || []).length && !(order.warnings || []).length ? (
                <div className={`rounded-lg border p-3 ${levelClass("info")}`}>
                  <p className="font-semibold text-xs uppercase tracking-wide mb-1">Info</p>
                  <p className="text-sm">No warnings or errors for this order.</p>
                </div>
              ) : null}
            </div>

            <div className="p-5 bg-slate-50 border-t border-slate-200">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-3">Generated XML</h3>
              <div className="space-y-2">
                {(order.xml_files || []).map((file) => (
                  <button
                    key={file.filename}
                    type="button"
                    onClick={() => downloadFile(file.filename)}
                    disabled={busyAction === `download:${file.filename}`}
                    className="w-full flex items-center justify-between p-2 rounded hover:bg-slate-100 transition-colors text-sm text-slate-700 disabled:opacity-60"
                  >
                    <span>{file.name}</span>
                    <span className="material-icons text-slate-400 text-lg">download</span>
                  </button>
                ))}
                {!(order.xml_files || []).length ? (
                  <p className="text-xs text-slate-500">No XML files generated yet.</p>
                ) : null}
              </div>
            </div>
          </div>
        </aside>
      </main>

      {isEditing ? (
        <div className="fixed bottom-0 left-0 w-full bg-white border-t border-primary/50 shadow-[0_-4px_20px_rgba(0,0,0,0.08)] py-4 px-6 z-40">
          <div className="max-w-[1920px] mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="material-icons text-primary animate-pulse">edit_note</span>
              <p className="text-sm font-medium text-slate-700">Review mode is active. Unsaved changes will be lost.</p>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={discardChanges}
                className="px-5 py-2.5 text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
              >
                Discard
              </button>
              <button
                type="button"
                onClick={saveChanges}
                disabled={busyAction === "save"}
                className="px-6 py-2.5 text-sm font-bold text-slate-900 bg-primary rounded-lg shadow-lg shadow-primary/20 transition-all flex items-center gap-2 disabled:opacity-60"
              >
                <span className="material-icons text-lg">check</span>
                {busyAction === "save" ? "Saving..." : "Save & Verify"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

