import { useRef, useState } from "react";
import { AppShell } from "../components/AppShell";
import { useI18n } from "../i18n/I18nContext";
import { downloadBlob } from "../utils/download";

export function ExcelOrdersPage() {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState(null);
  const [searchInput, setSearchInput] = useState("");
  const inputRef = useRef(null);
  const columnRows = [
    ["Kommission", t("excelOrders.columnDescriptionKommission")],
    ["Artikelnummer", t("excelOrders.columnDescriptionArtikelnummer")],
    ["Modellnummer", t("excelOrders.columnDescriptionModellnummer")],
    ["Menge", t("excelOrders.columnDescriptionMenge")],
    ["Furncloud_ID", t("excelOrders.columnDescriptionFurncloudId")],
    ["Kunde", t("excelOrders.columnDescriptionKunde")],
    ["Filiale", t("excelOrders.columnDescriptionFiliale")],
    ["Lieferwoche", t("excelOrders.columnDescriptionLieferwoche")],
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
            {t("excelOrders.subtitle") ? <p className="text-sm text-slate-500">{t("excelOrders.subtitle")}</p> : null}
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
                    {t("excelOrders.uploadBadge")}
                  </span>
                  <div className="space-y-2">
                    <h2 className="text-2xl font-semibold text-slate-900">{t("excelOrders.uploadTitle")}</h2>
                    <p className="max-w-2xl text-sm leading-6 text-slate-600">
                      {t("excelOrders.uploadSubtitle")}
                    </p>
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4">
                  <label className="block text-sm font-medium text-slate-700" htmlFor="excel-file">
                    {t("excelOrders.selectFile")}
                  </label>
                  <div className="flex flex-col gap-3 md:flex-row md:items-center">
                    <input
                      ref={inputRef}
                      id="excel-file"
                      type="file"
                      accept=".xlsx,.xlsb,.xls"
                      required
                      onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                      className="hidden"
                    />
                    <button
                      type="button"
                      onClick={() => inputRef.current?.click()}
                      className="inline-flex items-center justify-center rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm font-medium text-sky-700 transition-colors hover:bg-sky-100"
                    >
                      {t("excelOrders.chooseFile")}
                    </button>
                    <span className="text-sm text-slate-600">
                      {file?.name || t("excelOrders.noFileSelected")}
                    </span>
                  </div>

                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div className="text-sm text-slate-500">
                      {file ? (
                        <span className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-emerald-700">
                          <span className="material-icons text-sm">task_alt</span>
                          {file.name}
                        </span>
                      ) : (
                        <span>{t("excelOrders.noFileSelectedYet")}</span>
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
                <p className="mt-1 text-sm text-slate-500">{t("excelOrders.columnsSubtitle")}</p>
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-full text-sm text-slate-700">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="px-6 py-3 text-left font-semibold">{t("excelOrders.columnHeader")}</th>
                      <th className="px-6 py-3 text-left font-semibold">{t("excelOrders.descriptionHeader")}</th>
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
