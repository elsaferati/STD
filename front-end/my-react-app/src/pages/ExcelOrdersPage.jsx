import { useState } from "react";
import { AppShell } from "../components/AppShell";
import { useI18n } from "../i18n/I18nContext";
import { downloadBlob } from "../utils/download";

export function ExcelOrdersPage() {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState(null);

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

  return (
    <AppShell active="excelOrders">
      <div className="max-w-2xl space-y-4 py-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{t("excelOrders.title")}</h1>
          <p className="text-sm text-slate-500">{t("excelOrders.subtitle")}</p>
        </div>

        {error ? (
          <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-3">{error}</div>
        ) : null}

        <form onSubmit={handleSubmit} className="bg-surface-light border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
          <div className="space-y-2">
            <label className="block text-sm font-medium text-slate-700" htmlFor="excel-file">
              {t("excelOrders.selectFile")}
            </label>
            <input
              id="excel-file"
              type="file"
              accept=".xlsx,.xlsb,.xls"
              required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded file:border-0 file:text-sm file:font-medium file:bg-primary/10 file:text-primary hover:file:bg-primary/20"
            />
          </div>

          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-2 bg-primary text-white px-5 py-2.5 rounded text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-60"
          >
            <span className="material-icons text-base">{busy ? "hourglass_top" : "download"}</span>
            {busy ? t("excelOrders.generating") : t("excelOrders.generate")}
          </button>
        </form>

        <div className="bg-surface-light border border-slate-200 rounded-xl p-6 shadow-sm space-y-3">
          <h2 className="text-base font-semibold text-slate-900">{t("excelOrders.columnsTitle")}</h2>
          <table className="w-full text-sm text-slate-700 border-collapse">
            <thead>
              <tr className="bg-slate-100 text-left">
                <th className="px-3 py-2 font-semibold border border-slate-200">Column</th>
                <th className="px-3 py-2 font-semibold border border-slate-200">Description</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["Kommission", "Commission / order reference number"],
                ["Artikelnummer", "Article number"],
                ["Modellnummer", "Model number"],
                ["Menge", "Quantity"],
                ["Furncloud_ID", "Furncloud product ID"],
                ["Kunde", "Customer name"],
                ["Filiale", "Store / branch"],
                ["Lieferwoche", "Delivery week"],
              ].map(([col, desc]) => (
                <tr key={col} className="even:bg-slate-50">
                  <td className="px-3 py-1.5 border border-slate-200 font-mono">{col}</td>
                  <td className="px-3 py-1.5 border border-slate-200">{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  );
}
