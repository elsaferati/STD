import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { DEFAULT_LANG, LANGUAGES, LOCALES, translations } from "./translations";

const I18nContext = createContext({
  lang: DEFAULT_LANG,
  setLang: () => {},
  t: (key, _params, fallback) => fallback ?? key,
  available: LANGUAGES,
});

function resolveLocale(lang) {
  return LOCALES[lang] || undefined;
}

function getTranslationValue(lang, key) {
  const parts = String(key || "").split(".");
  let node = translations[lang];
  for (const part of parts) {
    if (!node || typeof node !== "object") {
      return undefined;
    }
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

function interpolate(template, params) {
  if (!params) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (_match, key) => {
    if (Object.prototype.hasOwnProperty.call(params, key)) {
      return String(params[key]);
    }
    return "";
  });
}

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => {
    if (typeof window === "undefined") {
      return DEFAULT_LANG;
    }
    return window.localStorage.getItem("app.lang") || DEFAULT_LANG;
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem("app.lang", lang);
  }, [lang]);

  const t = useCallback(
    (key, params, fallback) => {
      const value =
        getTranslationValue(lang, key) ??
        getTranslationValue(DEFAULT_LANG, key);
      if (!value) {
        return fallback ?? key;
      }
      return interpolate(value, params);
    },
    [lang],
  );

  const contextValue = useMemo(
    () => ({
      lang,
      setLang,
      t,
      available: LANGUAGES,
      locale: resolveLocale(lang),
    }),
    [lang, t],
  );

  return (
    <I18nContext.Provider value={contextValue}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}

export { resolveLocale };
