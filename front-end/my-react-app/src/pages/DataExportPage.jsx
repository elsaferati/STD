import { useState } from "react";
import { fetchBlob } from "../api/http";
import { AppShell } from "../components/AppShell";
import { useI18n } from "../i18n/I18nContext";
import { downloadBlob } from "../utils/download";

const TABLE_EXPORTS = [
  { tableName: "filialen_import_stage", labelKey: "filialenImportStage" },
  { tableName: "kunden_import_stage", labelKey: "kundenImportStage" },
  { tableName: "wochen_import_stage", labelKey: "wochenImportStage" },
];

function buildExportFilename(tableName) {
  const dateStamp = new Date().toISOString().slice(0, 10);
  return `${tableName}_${dateStamp}.xlsx`;
}

export function DataExportPage() {
  const { t } = useI18n();
  const [actionBusy, setActionBusy] = useState("");
  const [actionError, setActionError] = useState("");

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

  return (
    <AppShell active="dataExport">
      <div className="max-w-5xl space-y-4">
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
      </div>
    </AppShell>
  );
}
