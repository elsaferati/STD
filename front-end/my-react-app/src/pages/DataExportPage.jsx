import { useRef, useState } from "react";
import { fetchBlob } from "../api/http";
import { AppShell } from "../components/AppShell";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { useI18n } from "../i18n/I18nContext";
import { downloadBlob } from "../utils/download";

const TABLE_EXPORTS = [
  { tableName: "filialen_import_stage", labelKey: "filialenImportStage" },
  { tableName: "kunden_import_stage", labelKey: "kundenImportStage" },
  { tableName: "wochen_import_stage", labelKey: "wochenImportStage" },
];

const TABLE_IMPORTS = [
  { tableName: "filialen_import_stage", labelKey: "filialenImportStageImport" },
  { tableName: "kunden_import_stage", labelKey: "kundenImportStageImport" },
];

function buildExportFilename(tableName) {
  const dateStamp = new Date().toISOString().slice(0, 10);
  return `${tableName}_${dateStamp}.xlsx`;
}

function ImportRow({ tableName, labelKey }) {
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
    <div className="flex flex-col gap-2 bg-white border border-slate-200 rounded-lg p-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span className="text-sm font-medium text-slate-700">{t(`dataExport.${labelKey}`)}</span>
        <span className="text-xs text-amber-600">{t("dataExport.importWarning")}</span>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xls"
          className="text-sm text-slate-600 file:mr-2 file:py-1 file:px-3 file:rounded file:border file:border-slate-300 file:text-sm file:bg-slate-50 file:text-slate-700 hover:file:bg-slate-100"
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
          className="bg-primary text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {busy ? t("dataExport.importing") : t("dataExport.importButton")}
        </button>
      </div>
      {status && (
        <p className={`text-xs ${status.ok ? "text-green-600" : "text-danger"}`}>{status.message}</p>
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
    <AppShell active="dataExport">
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

        <div className="w-full px-6 py-6 max-w-5xl space-y-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{t("dataExport.title")}</h1>
            <p className="text-sm text-slate-500">{t("dataExport.subtitle")}</p>
          </div>

          {actionError ? <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{actionError}</div> : null}

          <div className="bg-surface-light border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">{t("dataExport.exportsTitle")}</h2>
              <p className="text-sm text-slate-500 mt-1">{t("dataExport.exportsSubtitle")}</p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {TABLE_EXPORTS.map((item) => (
                <button
                  key={item.tableName}
                  type="button"
                  onClick={() => handleExport(item.tableName)}
                  disabled={actionBusy === item.tableName}
                  className="bg-white border border-slate-200 text-slate-700 px-4 py-3 rounded text-sm font-medium hover:bg-slate-50 transition-colors flex items-center justify-center gap-2 disabled:opacity-60"
                >
                  <span className="material-icons text-base">file_download</span>
                  {actionBusy === item.tableName ? t("dataExport.exporting") : t(`dataExport.${item.labelKey}`)}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-surface-light border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">{t("dataExport.importsTitle")}</h2>
              <p className="text-sm text-slate-500 mt-1">{t("dataExport.importsSubtitle")}</p>
            </div>

            <div className="flex flex-col gap-3">
              {TABLE_IMPORTS.map((item) => (
                <ImportRow key={item.tableName} tableName={item.tableName} labelKey={item.labelKey} />
              ))}
            </div>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
