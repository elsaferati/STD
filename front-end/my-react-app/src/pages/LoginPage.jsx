import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { useI18n } from "../i18n/I18nContext";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from || "/";
  const { t } = useI18n();

  const [tokenInput, setTokenInput] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    const token = tokenInput.trim();
    if (!token) {
      setError(t("login.tokenRequired"));
      return;
    }

    setSubmitting(true);
    setError("");

    try {
      await fetchJson("/api/auth/check", { token });
      login(token);
      navigate(from, { replace: true });
    } catch (requestError) {
      setError(requestError.message || t("login.authFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-background-light min-h-screen flex items-center justify-center p-4 font-login text-slate-800">
      <div className="fixed top-4 right-4 z-20">
        <LanguageSwitcher compact />
      </div>
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0 opacity-40">
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2" />
        <div className="absolute bottom-0 left-0 w-[600px] h-[600px] bg-primary/5 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2" />
      </div>

      <main className="w-full max-w-md relative z-10">
        <div className="bg-surface-light shadow-xl rounded-xl overflow-hidden border border-slate-200">
          <div className="px-8 pt-10 pb-6 text-center">
            <div className="w-16 h-16 bg-primary/10 rounded-xl flex items-center justify-center mx-auto mb-6 text-primary">
              <span className="material-icons text-4xl">inventory_2</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900 mb-2">
              <span className="text-red-600 font-black">XX</span>LUTZ <span className="text-slate-500 font-medium">Order Agent</span>
            </h1>
            <p className="text-sm text-slate-500">{t("login.secureAccess")}</p>
          </div>

          <div className="px-8 pb-10">
            <form className="space-y-5" onSubmit={handleSubmit}>
              <div className="space-y-1.5">
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-500" htmlFor="token">
                  {t("login.bearerToken")}
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <span className="material-icons text-slate-400 text-lg">vpn_key</span>
                  </div>
                  <input
                    id="token"
                    value={tokenInput}
                    onChange={(event) => setTokenInput(event.target.value)}
                    className="block w-full pl-10 pr-3 py-3 border border-slate-200 rounded-lg bg-slate-50 text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                    placeholder={t("login.tokenPlaceholder")}
                    autoComplete="off"
                  />
                </div>
              </div>

              {error ? (
                <p className="text-sm text-danger bg-danger/10 border border-danger/20 rounded p-2">{error}</p>
              ) : null}

              <button
                type="submit"
                disabled={submitting}
                className="w-full flex justify-center items-center py-3 px-4 border border-transparent rounded-lg shadow-sm text-sm font-semibold text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary transition-all disabled:opacity-60"
              >
                {submitting ? t("login.checking") : t("login.signIn")}
                <span className="material-icons ml-2 text-sm">arrow_forward</span>
              </button>
            </form>
          </div>

          <div className="bg-slate-50 px-8 py-4 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>{t("login.dashboardLogin")}</span>
            <span className="flex items-center gap-1">
              <span className="material-icons text-[14px]">shield</span>
              {t("login.bearerAuth")}
            </span>
          </div>
        </div>
      </main>
    </div>
  );
}

