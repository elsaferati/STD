import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { ApiError, fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { useI18n } from "../i18n/I18nContext";

function createDraftRange(rowId) {
  return {
    rowId,
    week_from: "",
    week_to: "",
    prep_weeks: "",
  };
}

function coerceInteger(value) {
  if (typeof value === "number" && Number.isInteger(value)) {
    return value;
  }
  const normalized = String(value ?? "").trim();
  if (!/^-?\d+$/.test(normalized)) {
    return null;
  }
  return Number.parseInt(normalized, 10);
}

function validateSettingsDraft(defaultPrepWeeksInput, ranges) {
  const errors = [];
  const defaultPrepWeeks = coerceInteger(defaultPrepWeeksInput);
  if (defaultPrepWeeks === null || defaultPrepWeeks < 0) {
    errors.push("Default preparation weeks must be a whole number greater than or equal to 0.");
  }

  const normalizedRanges = [];
  ranges.forEach((range, index) => {
    const weekFrom = coerceInteger(range.week_from);
    const weekTo = coerceInteger(range.week_to);
    const prepWeeks = coerceInteger(range.prep_weeks);

    if (weekFrom === null || weekFrom < 1 || weekFrom > 52) {
      errors.push(`Range ${index + 1}: Week from must be between 1 and 52.`);
    }
    if (weekTo === null || weekTo < 1 || weekTo > 52) {
      errors.push(`Range ${index + 1}: Week to must be between 1 and 52.`);
    }
    if (prepWeeks === null || prepWeeks < 0) {
      errors.push(`Range ${index + 1}: Preparation weeks must be a whole number greater than or equal to 0.`);
    }
    if (weekFrom !== null && weekTo !== null && weekFrom > weekTo) {
      errors.push(`Range ${index + 1}: Week from cannot be greater than week to.`);
    }

    if (
      weekFrom !== null && weekFrom >= 1 && weekFrom <= 52 &&
      weekTo !== null && weekTo >= 1 && weekTo <= 52 &&
      prepWeeks !== null && prepWeeks >= 0 &&
      weekFrom <= weekTo
    ) {
      normalizedRanges.push({
        rowId: range.rowId,
        week_from: weekFrom,
        week_to: weekTo,
        prep_weeks: prepWeeks,
      });
    }
  });

  const sortedRanges = [...normalizedRanges].sort((left, right) => {
    if (left.week_from !== right.week_from) {
      return left.week_from - right.week_from;
    }
    return left.week_to - right.week_to;
  });

  for (let index = 1; index < sortedRanges.length; index += 1) {
    const previous = sortedRanges[index - 1];
    const current = sortedRanges[index];
    if (current.week_from <= previous.week_to) {
      errors.push(
        `Custom ranges overlap between weeks ${previous.week_from}-${previous.week_to} and ${current.week_from}-${current.week_to}.`,
      );
    }
  }

  return {
    errors,
    payload: {
      default_prep_weeks: defaultPrepWeeks ?? 0,
      ranges: sortedRanges.map(({ week_from, week_to, prep_weeks }) => ({
        week_from,
        week_to,
        prep_weeks,
      })),
    },
  };
}

export function SettingsPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [defaultPrepWeeksInput, setDefaultPrepWeeksInput] = useState("2");
  const [ranges, setRanges] = useState([]);
  const [nextRowId, setNextRowId] = useState(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saveSuccess, setSaveSuccess] = useState("");

  const loadSettings = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchJson("/api/settings/delivery-preparation");
      const loadedRanges = Array.isArray(payload?.ranges)
        ? payload.ranges.map((range, index) => ({
          rowId: index + 1,
          week_from: String(range.week_from ?? ""),
          week_to: String(range.week_to ?? ""),
          prep_weeks: String(range.prep_weeks ?? ""),
        }))
        : [];
      setDefaultPrepWeeksInput(String(payload?.default_prep_weeks ?? 2));
      setRanges(loadedRanges);
      setNextRowId(loadedRanges.length + 1);
      setLoadError("");
    } catch (requestError) {
      setLoadError(requestError.message || "Failed to load delivery preparation settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user?.role === "admin") {
      loadSettings();
    }
  }, [loadSettings, user?.role]);

  const validation = useMemo(
    () => validateSettingsDraft(defaultPrepWeeksInput, ranges),
    [defaultPrepWeeksInput, ranges],
  );

  const handleRangeChange = (rowId, field, value) => {
    setRanges((current) => current.map((range) => (
      range.rowId === rowId ? { ...range, [field]: value } : range
    )));
    setSaveError("");
    setSaveSuccess("");
  };

  const handleAddRange = () => {
    setRanges((current) => [...current, createDraftRange(nextRowId)]);
    setNextRowId((current) => current + 1);
    setSaveError("");
    setSaveSuccess("");
  };

  const handleRemoveRange = (rowId) => {
    setRanges((current) => current.filter((range) => range.rowId !== rowId));
    setSaveError("");
    setSaveSuccess("");
  };

  const handleSave = async (event) => {
    event.preventDefault();
    if (validation.errors.length > 0) {
      setSaveError(validation.errors[0]);
      setSaveSuccess("");
      return;
    }

    setSaving(true);
    setSaveError("");
    setSaveSuccess("");
    try {
      let payload;
      try {
        payload = await fetchJson("/api/settings/delivery-preparation", {
          method: "PUT",
          body: validation.payload,
        });
      } catch (requestError) {
        if (!(requestError instanceof ApiError) || requestError.status !== 405) {
          throw requestError;
        }
        payload = await fetchJson("/api/settings/delivery-preparation", {
          method: "POST",
          body: validation.payload,
        });
      }
      const savedRanges = Array.isArray(payload?.ranges)
        ? payload.ranges.map((range, index) => ({
          rowId: index + 1,
          week_from: String(range.week_from ?? ""),
          week_to: String(range.week_to ?? ""),
          prep_weeks: String(range.prep_weeks ?? ""),
        }))
        : [];
      setDefaultPrepWeeksInput(String(payload?.default_prep_weeks ?? validation.payload.default_prep_weeks));
      setRanges(savedRanges);
      setNextRowId(savedRanges.length + 1);
      setSaveSuccess("Delivery preparation settings saved.");
    } catch (requestError) {
      setSaveError(requestError.message || "Failed to save delivery preparation settings.");
    } finally {
      setSaving(false);
    }
  };

  if (user && user.role !== "admin") {
    return <Navigate to="/" replace />;
  }

  return (
    <AppShell active="settings">
      <main className="flex-1 flex flex-col min-w-0">
        <div className="w-full px-6 py-6 space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">
              {t("settings.title", null, "Delivery Preparation Settings")}
            </h1>
            <p className="text-sm text-slate-500">
              {t("settings.subtitle", null, "Configure the default preparation buffer and week-based overrides.")}
            </p>
          </div>

          <div className="bg-surface-light border border-slate-200 rounded-xl p-6 shadow-sm space-y-5">
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,280px)_1fr] gap-6 items-start">
              <div className="space-y-3">
                <div className="inline-flex items-center px-3 py-1 rounded-full bg-primary/10 text-primary text-xs font-semibold uppercase tracking-[0.12em]">
                  Global rule
                </div>
                <h2 className="text-lg font-semibold text-slate-900">
                  Default preparation weeks
                </h2>
                <p className="text-sm text-slate-500">
                  This applies outside custom week ranges and remains the fallback when no database settings are available.
                </p>
              </div>

              <label className="flex flex-col gap-2 text-sm text-slate-600 max-w-xs">
                <span>Default prep weeks</span>
                <input
                  className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                  type="number"
                  min="0"
                  step="1"
                  value={defaultPrepWeeksInput}
                  onChange={(event) => {
                    setDefaultPrepWeeksInput(event.target.value);
                    setSaveError("");
                    setSaveSuccess("");
                  }}
                  disabled={loading || saving}
                />
              </label>
            </div>

            <div className="border-t border-slate-200 pt-5 space-y-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Custom week ranges</h2>
                  <p className="text-sm text-slate-500">
                    Add non-overlapping ISO week ranges that override the default preparation time.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleAddRange}
                  disabled={loading || saving}
                  className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                >
                  <span className="material-icons text-base">add</span>
                  <span>Add range</span>
                </button>
              </div>

              <form onSubmit={handleSave} className="space-y-4">
                <div className="overflow-x-auto border border-slate-200 rounded-xl">
                  <table className="min-w-full text-sm">
                    <thead className="bg-slate-50 text-slate-500">
                      <tr>
                        <th className="px-4 py-3 text-left">Range</th>
                        <th className="px-4 py-3 text-left">Week from</th>
                        <th className="px-4 py-3 text-left">Week to</th>
                        <th className="px-4 py-3 text-left">Prep weeks</th>
                        <th className="px-4 py-3 text-right">{t("common.actions")}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white">
                      {loading ? (
                        <tr>
                          <td className="px-4 py-4 text-slate-500" colSpan={5}>
                            Loading delivery preparation settings...
                          </td>
                        </tr>
                      ) : ranges.length ? (
                        ranges.map((range, index) => (
                          <tr key={range.rowId}>
                            <td className="px-4 py-3 font-medium text-slate-900">Range {index + 1}</td>
                            <td className="px-4 py-3">
                              <input
                                className="w-24 rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                                type="number"
                                min="1"
                                max="52"
                                step="1"
                                value={range.week_from}
                                onChange={(event) => handleRangeChange(range.rowId, "week_from", event.target.value)}
                                disabled={saving}
                              />
                            </td>
                            <td className="px-4 py-3">
                              <input
                                className="w-24 rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                                type="number"
                                min="1"
                                max="52"
                                step="1"
                                value={range.week_to}
                                onChange={(event) => handleRangeChange(range.rowId, "week_to", event.target.value)}
                                disabled={saving}
                              />
                            </td>
                            <td className="px-4 py-3">
                              <input
                                className="w-28 rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                                type="number"
                                min="0"
                                step="1"
                                value={range.prep_weeks}
                                onChange={(event) => handleRangeChange(range.rowId, "prep_weeks", event.target.value)}
                                disabled={saving}
                              />
                            </td>
                            <td className="px-4 py-3 text-right">
                              <button
                                type="button"
                                onClick={() => handleRemoveRange(range.rowId)}
                                disabled={saving}
                                className="inline-flex items-center px-3 py-1.5 rounded-lg border border-red-200 text-red-700 hover:bg-red-50 disabled:opacity-60"
                              >
                                Remove
                              </button>
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td className="px-4 py-4 text-slate-500" colSpan={5}>
                            No custom ranges configured. The default value will be used for all weeks.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {loadError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {loadError}
                  </div>
                ) : null}

                {validation.errors.length ? (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                    {validation.errors[0]}
                  </div>
                ) : null}

                {saveError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {saveError}
                  </div>
                ) : null}

                {saveSuccess ? (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                    {saveSuccess}
                  </div>
                ) : null}

                <div className="flex items-center justify-end gap-3">
                  <button
                    type="button"
                    onClick={loadSettings}
                    disabled={loading || saving}
                    className="px-4 py-2 rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                  >
                    Reload
                  </button>
                  <button
                    type="submit"
                    disabled={loading || saving}
                    className="px-4 py-2 rounded-lg bg-primary text-white font-semibold disabled:opacity-60"
                  >
                    {saving ? t("common.saving") : t("common.save")}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
