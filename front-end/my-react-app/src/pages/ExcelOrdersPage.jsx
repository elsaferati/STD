import { useState } from "react";
import { AppShell } from "../components/AppShell";
import { useI18n } from "../i18n/I18nContext";
import { downloadBlob } from "../utils/download";

export function ExcelOrdersPage() {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState(null);
  const [searchInput, setSearchInput] = useState("");
  const columnRows = [
    ["Kommission", "Commission / order reference number"],
    ["Artikelnummer", "Article number"],
    ["Modellnummer", "Model number"],
    ["Menge", "Quantity"],
    ["Furncloud_ID", "Furncloud product ID"],
    ["Kunde", "Customer name"],
    ["Filiale", "Store / branch"],
    ["Lieferwoche", "Delivery week"],
  ];

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("excel_file", file);
      const response = await fetch("/excel-to-xml/generate", {
        method: "POST",
        body: formData,
        credentials: "include",
      });
      if (!response.ok) {
        let msg = t("excelOrders.errorFallback");
        try {
          const ct = response.headers.get("content-type") || "";
          if (ct.includes("application/json")) {
            const json = await response.json();
            msg = json.error || json.message || msg;
          } else {
            const text = await response.text();
            if (text) msg = text;
          }
        } catch (_) {}
        setError(msg);
        return;
      }
      const blob = await response.blob();
      downloadBlob(blob, "orders_xml.zip");
    } catch (err) {
      setError(err.message || t("excelOrders.errorFallback"));
    } finally {
      setBusy(false);
    }
  };

  const handleSearchSubmit = (event) => {
    event.preventDefault();
  };

  return (
    <AppShell
      active="excelOrders"
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
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{t("excelOrders.title")}</h1>
            <p className="text-sm text-slate-500">{t("excelOrders.subtitle")}</p>
          </div>

          {error ? (
            <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{error}</div>
          ) : null}

          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(420px,0.9fr)] gap-6 items-start">
            <form
              onSubmit={handleSubmit}
              className="relative overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-blue-50 shadow-sm"
            >
              <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-sky-500 via-primary to-cyan-400" />
              <div className="p-6 md:p-8 space-y-6">
                <div className="space-y-3">
                  <span className="inline-flex items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">
                    <span className="material-icons text-sm">table_view</span>
                    XML Batch Export
                  </span>
                  <div className="space-y-2">
                    <h2 className="text-2xl font-semibold text-slate-900">Upload your order workbook</h2>
                    <p className="max-w-2xl text-sm leading-6 text-slate-600">
                      Import one Excel file and generate a ZIP package containing XML order files in one step.
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Accepted</p>
                    <p className="mt-1 text-sm font-medium text-slate-700">.xlsx, .xlsb, .xls</p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Output</p>
                    <p className="mt-1 text-sm font-medium text-slate-700">ZIP with XML files</p>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Process</p>
                    <p className="mt-1 text-sm font-medium text-slate-700">Single upload workflow</p>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
                  <label className="block text-sm font-medium text-slate-700" htmlFor="excel-file">
                    {t("excelOrders.selectFile")}
                  </label>
                  <input
                    id="excel-file"
                    type="file"
                    accept=".xlsx,.xlsb,.xls"
                    required
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="block w-full text-sm text-slate-600 file:mr-4 file:py-3 file:px-4 file:rounded-xl file:border file:border-sky-200 file:text-sm file:font-medium file:bg-sky-50 file:text-sky-700 hover:file:bg-sky-100"
                  />

                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div className="text-sm text-slate-500">
                      {file ? (
                        <span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-emerald-700">
                          <span className="material-icons text-sm">task_alt</span>
                          {file.name}
                        </span>
                      ) : (
                        <span>No file selected yet.</span>
                      )}
                    </div>

                    <button
                      type="submit"
                      disabled={busy}
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-60"
                    >
                      <span className="material-icons text-base">{busy ? "hourglass_top" : "download"}</span>
                      {busy ? t("excelOrders.generating") : t("excelOrders.generate")}
                    </button>
                  </div>
                </div>
              </div>
            </form>

            <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              <div className="border-b border-slate-200 bg-slate-50/80 px-6 py-5">
                <h2 className="text-lg font-semibold text-slate-900">{t("excelOrders.columnsTitle")}</h2>
                <p className="mt-1 text-sm text-slate-500">Use these exact columns in your Excel file.</p>
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-full text-sm text-slate-700">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="px-6 py-3 text-left font-semibold">Column</th>
                      <th className="px-6 py-3 text-left font-semibold">Description</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {columnRows.map(([col, desc]) => (
                      <tr key={col} className="hover:bg-slate-50/80">
                        <td className="px-6 py-4 font-mono text-[13px] text-slate-800">{col}</td>
                        <td className="px-6 py-4 text-slate-600">{desc}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
