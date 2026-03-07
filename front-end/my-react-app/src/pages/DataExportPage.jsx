import { useRef, useState } from "react";
import { fetchBlob } from "../api/http";
import { AppShell } from "../components/AppShell";
import { useI18n } from "../i18n/I18nContext";
import { downloadBlob } from "../utils/download";

const DATASET_ACTIONS = [
  {
    tableName: "filialen_import_stage",
    exportLabelKey: "filialenImportStage",
    importLabelKey: "filialenImportStageImport",
    badge: "ILN",
  },
  {
    tableName: "kunden_import_stage",
    exportLabelKey: "kundenImportStage",
    importLabelKey: "kundenImportStageImport",
    badge: "CRM",
  },
];

function buildExportFilename(tableName) {
  const dateStamp = new Date().toISOString().slice(0, 10);
  return `${tableName}_${dateStamp}.xlsx`;
}

function ImportControls({ tableName, labelKey }) {
  const { t } = useI18n();
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null); // { ok: bool, message: string }
  const inputRef = useRef(null);

  const handleImport = async () => {
    if (!file) return;
    setBusy(true);
    setStatus(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const resp = await fetch(`/api/data-import/${encodeURIComponent(tableName)}`, {
        method: "POST",
        body: formData,
        credentials: "include",
      });
      if (!resp.ok) {
        const json = await resp.json().catch(() => ({}));
        setStatus({ ok: false, message: json.message || t("dataExport.importFailed") });
        return;
      }
      const json = await resp.json();
      setStatus({
        ok: true,
        message: t("dataExport.importSuccess").replace("{count}", json.imported ?? 0),
      });
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch {
      setStatus({ ok: false, message: t("dataExport.importFailed") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm">
      <span className="text-sm font-semibold text-slate-800">{t(`dataExport.${labelKey}`)}</span>
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xls"
          className="max-w-full text-sm text-slate-600 file:mr-3 file:py-2.5 file:px-4 file:rounded-xl file:border file:border-sky-200 file:text-sm file:font-medium file:bg-sky-50 file:text-sky-700 hover:file:bg-sky-100"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setStatus(null);
          }}
          disabled={busy}
        />
        <button
          type="button"
          onClick={handleImport}
          disabled={!file || busy}
          className="inline-flex items-center justify-center rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {busy ? t("dataExport.importing") : t("dataExport.importButton")}
        </button>
      </div>
      <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
        {t("dataExport.importWarning")}
      </p>
      {status && (
        <p
          className={`rounded-xl px-3 py-2 text-xs font-medium ${
            status.ok
              ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border border-rose-200 bg-rose-50 text-danger"
          }`}
        >
          {status.message}
        </p>
      )}
    </div>
  );
}

export function DataExportPage() {
  const { t } = useI18n();
  const [actionBusy, setActionBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [searchInput, setSearchInput] = useState("");

  const handleExport = async (tableName) => {
    setActionBusy(tableName);
    setActionError("");
    try {
      const blob = await fetchBlob(`/api/data-export/${encodeURIComponent(tableName)}.xlsx`);
      downloadBlob(blob, buildExportFilename(tableName));
    } catch (requestError) {
      setActionError(requestError.message || t("dataExport.exportFailed"));
    } finally {
      setActionBusy("");
    }
  };

  const handleSearchSubmit = (event) => {
    event.preventDefault();
  };

  return (
    <AppShell
      active="dataExport"
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
          <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-cyan-50 shadow-sm">
            <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-sky-500 via-primary to-cyan-400" />
            <div className="px-6 py-6 md:px-8 md:py-7">
              <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
                <div className="space-y-2">
                  <span className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">
                    <span className="material-icons text-sm">sync_alt</span>
                    Data Exchange
                  </span>
                  <div>
                    <h1 className="text-3xl font-bold tracking-tight text-slate-900">{t("dataExport.title")}</h1>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">{t("dataExport.subtitle")}</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 shadow-sm">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Datasets</p>
                    <p className="mt-1 text-lg font-semibold text-slate-900">{DATASET_ACTIONS.length}</p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 shadow-sm">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Export</p>
                    <p className="mt-1 text-sm font-medium text-slate-700">Excel download</p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 shadow-sm">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Import</p>
                    <p className="mt-1 text-sm font-medium text-slate-700">Replace table data</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {actionError ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{actionError}</div> : null}

          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 bg-slate-50/80 px-6 py-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Export / Import Workspace</h2>
                  <p className="mt-1 text-sm text-slate-500">Manage both directions for each dataset in one place.</p>
                </div>
                <div className="hidden rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-500 md:block">
                  {DATASET_ACTIONS.length} active tables
                </div>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="px-6 py-4 text-left font-semibold">{t("dataExport.exportColumn")}</th>
                    <th className="px-6 py-4 text-left font-semibold">{t("dataExport.importColumn")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {DATASET_ACTIONS.map((item) => (
                    <tr key={item.tableName} className="align-top transition-colors hover:bg-slate-50/70">
                      <td className="px-6 py-5">
                        <div className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-gradient-to-br from-white to-slate-50 p-4 shadow-sm">
                          <div className="flex items-start justify-between gap-3">
                            <div className="space-y-1">
                              <span className="text-sm font-semibold text-slate-800">{t(`dataExport.${item.exportLabelKey}`)}</span>
                              <p className="text-xs text-slate-500">Download the latest spreadsheet generated from this staging table.</p>
                            </div>
                            <span className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-sky-700">
                              {item.badge}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={() => handleExport(item.tableName)}
                            disabled={actionBusy === item.tableName}
                            className="inline-flex items-center justify-center gap-2 self-start rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
                          >
                            <span className="material-icons text-base">file_download</span>
                            {actionBusy === item.tableName ? t("dataExport.exporting") : t(`dataExport.${item.exportLabelKey}`)}
                          </button>
                        </div>
                      </td>
                      <td className="min-w-[360px] px-6 py-5">
                        <ImportControls tableName={item.tableName} labelKey={item.importLabelKey} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
