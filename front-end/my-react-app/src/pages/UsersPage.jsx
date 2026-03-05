import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate } from "react-router-dom";
import { fetchJson } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { useI18n } from "../i18n/I18nContext";
import { CLIENT_BRANCHES, UNKNOWN_CLIENT_BRANCH_ID } from "../constants/clientBranches";

const DEFAULT_USER_CLIENTS = [];

const toggleClientBranchSelection = (currentSelection, branchId) => {
  if (currentSelection.includes(branchId)) {
    return currentSelection.filter((entry) => entry !== branchId);
  }
  return [...currentSelection, branchId];
};

function ClientBranchPicker({
  label,
  options,
  selectedBranchIds,
  emptyStateLabel,
  helperLabel,
  selectAllLabel,
  clearLabel,
  onToggleBranch,
  onSelectAll,
  onClearAll,
}) {
  const selectedLabels = options
    .filter((option) => selectedBranchIds.includes(option.id))
    .map((option) => option.label);

  return (
    <div className="md:col-span-2 flex flex-col gap-2 text-sm text-slate-600">
      <div className="flex items-center justify-between gap-3">
        <span>{label}</span>
        <div className="inline-flex items-center gap-2">
          <button
            type="button"
            className="px-2.5 py-1 rounded-md border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50"
            onClick={onSelectAll}
          >
            {selectAllLabel}
          </button>
          <button
            type="button"
            className="px-2.5 py-1 rounded-md border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={onClearAll}
            disabled={selectedBranchIds.length === 0}
          >
            {clearLabel}
          </button>
        </div>
      </div>

      <div className="min-h-11 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 flex flex-wrap items-center gap-1.5">
        {selectedLabels.length ? (
          selectedLabels.map((selectedLabel) => (
            <span
              key={selectedLabel}
              className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary"
            >
              {selectedLabel}
            </span>
          ))
        ) : (
          <span className="text-xs text-slate-500">{emptyStateLabel}</span>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 p-2 bg-white max-h-48 overflow-y-auto">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {options.map((option) => {
            const checked = selectedBranchIds.includes(option.id);
            return (
              <label
                key={option.id}
                className={`flex items-center gap-2 px-2.5 py-2 rounded-md border cursor-pointer transition-colors ${
                  checked
                    ? "border-primary/40 bg-primary/5 text-slate-900"
                    : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                }`}
              >
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-primary"
                  checked={checked}
                  onChange={() => onToggleBranch(option.id)}
                />
                <span>{option.label}</span>
              </label>
            );
          })}
        </div>
      </div>

      <span className="text-xs text-slate-500">{helperLabel}</span>
    </div>
  );
}

export function UsersPage() {
  const { user } = useAuth();
  const { t } = useI18n();

  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    username: "",
    password: "",
    email: "",
    role: "user",
    client_branches: [...DEFAULT_USER_CLIENTS],
    is_active: true,
  });
  const [saving, setSaving] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [editForm, setEditForm] = useState({
    username: "",
    email: "",
    role: "user",
    client_branches: [...DEFAULT_USER_CLIENTS],
    is_active: true,
    password: "",
  });
  const [editSaving, setEditSaving] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchInput, setSearchInput] = useState("");

  const loadUsers = useCallback(async () => {
    try {
      const payload = await fetchJson("/api/users");
      setUsers(payload?.users || []);
      setError("");
    } catch (requestError) {
      setError(requestError.message || t("users.loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const clientOptions = useMemo(
    () => [
      ...CLIENT_BRANCHES.map((branch) => ({
        id: branch.id,
        label: t(branch.labelKey, null, branch.defaultLabel),
      })),
      {
        id: UNKNOWN_CLIENT_BRANCH_ID,
        label: t("clients.branch.unknown", null, "Unknown"),
      },
    ],
    [t],
  );

  const branchLabelMap = useMemo(() => {
    const labels = {};
    clientOptions.forEach((option) => {
      labels[option.id] = option.label;
    });
    return labels;
  }, [clientOptions]);

  const allClientBranchIds = useMemo(
    () => clientOptions.map((option) => option.id),
    [clientOptions],
  );

  const handleChange = (event) => {
    const { name, value, type, checked } = event.target;
    setForm((current) => ({
      ...current,
      [name]: type === "checkbox" ? checked : value,
    }));
  };

  const handleEditChange = (event) => {
    const { name, value, type, checked } = event.target;
    setEditForm((current) => ({
      ...current,
      [name]: type === "checkbox" ? checked : value,
    }));
  };

  const handleCreateClientBranchToggle = (branchId) => {
    setForm((current) => ({
      ...current,
      client_branches: toggleClientBranchSelection(current.client_branches, branchId),
    }));
  };

  const handleEditClientBranchToggle = (branchId) => {
    setEditForm((current) => ({
      ...current,
      client_branches: toggleClientBranchSelection(current.client_branches, branchId),
    }));
  };

  const handleCreateSelectAllClientBranches = () => {
    setForm((current) => ({
      ...current,
      client_branches: [...allClientBranchIds],
    }));
  };

  const handleCreateClearClientBranches = () => {
    setForm((current) => ({
      ...current,
      client_branches: [],
    }));
  };

  const handleEditSelectAllClientBranches = () => {
    setEditForm((current) => ({
      ...current,
      client_branches: [...allClientBranchIds],
    }));
  };

  const handleEditClearClientBranches = () => {
    setEditForm((current) => ({
      ...current,
      client_branches: [],
    }));
  };

  const openEdit = (entry) => {
    const assignedBranches = Array.isArray(entry.client_branches)
      ? entry.client_branches.filter((item) => typeof item === "string" && item.trim())
      : [];
    setEditUser(entry);
    setEditForm({
      username: entry.username || "",
      email: entry.email || "",
      role: entry.role || "user",
      client_branches: assignedBranches.length ? assignedBranches : [],
      is_active: Boolean(entry.is_active),
      password: "",
    });
  };

  const closeEdit = () => {
    setEditUser(null);
    setEditForm({
      username: "",
      email: "",
      role: "user",
      client_branches: [...DEFAULT_USER_CLIENTS],
      is_active: true,
      password: "",
    });
  };

  const handleCreate = async (event) => {
    event.preventDefault();
    if (!form.username.trim() || !form.password) {
      setError(t("users.missingCredentials"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      await fetchJson("/api/users", {
        method: "POST",
        body: {
          username: form.username.trim(),
          password: form.password,
          email: form.email.trim() || null,
          role: form.role,
          client_branches: form.role === "admin" ? [] : form.client_branches,
          is_active: form.is_active,
        },
      });
      setForm({
        username: "",
        password: "",
        email: "",
        role: "user",
        client_branches: [...DEFAULT_USER_CLIENTS],
        is_active: true,
      });
      await loadUsers();
    } catch (requestError) {
      setError(requestError.message || t("users.createError"));
    } finally {
      setSaving(false);
    }
  };

  const filteredUsers = users.filter((entry) => {
    if (statusFilter === "active" && !entry.is_active) return false;
    if (statusFilter === "inactive" && entry.is_active) return false;
    const query = searchInput.trim().toLowerCase();
    if (!query) return true;
    return [entry.username, entry.email, entry.role]
      .concat(Array.isArray(entry.client_branches) ? entry.client_branches : [])
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
  });

  const handleUpdate = async (event) => {
    event.preventDefault();
    if (!editUser) return;
    setEditSaving(true);
    setError("");
    try {
      await fetchJson(`/api/users/${encodeURIComponent(editUser.id)}`, {
        method: "PATCH",
        body: {
          username: editForm.username.trim(),
          email: editForm.email.trim() || null,
          role: editForm.role,
          client_branches: editForm.role === "admin" ? [] : editForm.client_branches,
          is_active: editForm.is_active,
          password: editForm.password || undefined,
        },
      });
      closeEdit();
      await loadUsers();
    } catch (requestError) {
      setError(requestError.message || t("users.updateError"));
    } finally {
      setEditSaving(false);
    }
  };

  const handleToggleActive = async (entry) => {
    setError("");
    try {
      const nextState = !entry.is_active;
      const confirmText = nextState ? t("users.confirmActivate") : t("users.confirmDeactivate");
      if (!window.confirm(confirmText)) {
        return;
      }
      await fetchJson(`/api/users/${encodeURIComponent(entry.id)}`, {
        method: "PATCH",
        body: { is_active: nextState },
      });
      await loadUsers();
    } catch (requestError) {
      setError(requestError.message || t("users.updateError"));
    }
  };

  if (user && user.role !== "admin") {
    return <Navigate to="/" replace />;
  }

  return (
    <AppShell active="users">
      <main className="flex-1 flex flex-col min-w-0">
        <div className="sticky top-0 z-30">
          <header className="h-16 bg-surface-light border-b border-slate-200 flex items-center justify-between px-6">
            <div className="relative w-full max-w-xl">
              <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">search</span>
              <input
                className="w-full bg-slate-50 border-none rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-2 focus:ring-primary"
                placeholder={t("orders.searchPlaceholder")}
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </div>
            <div className="flex items-center gap-3 ml-4">
              <LanguageSwitcher compact className="hidden md:flex" />
            </div>
          </header>
        </div>

        <div className="w-full px-6 py-6 space-y-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{t("users.title")}</h1>
            <p className="text-sm text-slate-500">{t("users.subtitle")}</p>
          </div>

          <div className="bg-surface-light border border-slate-200 rounded-xl p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900 mb-4">{t("users.createTitle")}</h2>
            <form className="grid grid-cols-1 md:grid-cols-2 gap-4" onSubmit={handleCreate}>
              <label className="flex flex-col gap-1 text-sm text-slate-600">
                {t("users.username")}
                <input
                  className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                  name="username"
                  value={form.username}
                  onChange={handleChange}
                  autoComplete="off"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm text-slate-600">
                {t("users.password")}
                <input
                  className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                  name="password"
                  type="password"
                  value={form.password}
                  onChange={handleChange}
                  autoComplete="new-password"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm text-slate-600">
                {t("users.email")}
                <input
                  className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                  name="email"
                  value={form.email}
                  onChange={handleChange}
                  autoComplete="off"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm text-slate-600">
                {t("users.role")}
                <select
                  className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                  name="role"
                  value={form.role}
                  onChange={handleChange}
                >
                  <option value="user">{t("users.roleUser")}</option>
                  <option value="admin">{t("users.roleAdmin")}</option>
                </select>
              </label>
              {form.role === "user" ? (
                <ClientBranchPicker
                  label={t("users.client")}
                  options={clientOptions}
                  selectedBranchIds={form.client_branches}
                  emptyStateLabel={t("users.clientNoneSelected")}
                  helperLabel={t("users.clientPickerHint")}
                  selectAllLabel={t("users.selectAllClients")}
                  clearLabel={t("users.clearClients")}
                  onToggleBranch={handleCreateClientBranchToggle}
                  onSelectAll={handleCreateSelectAllClientBranches}
                  onClearAll={handleCreateClearClientBranches}
                />
              ) : null}
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  name="is_active"
                  checked={form.is_active}
                  onChange={handleChange}
                />
                {t("users.active")}
              </label>
              <div className="md:col-span-2 flex items-center gap-3">
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 rounded-lg bg-primary text-white font-semibold disabled:opacity-60"
                >
                  {saving ? t("users.creating") : t("users.createButton")}
                </button>
                {error ? <span className="text-sm text-red-600">{error}</span> : null}
              </div>
            </form>
          </div>

          <div className="bg-surface-light border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <h2 className="text-lg font-semibold text-slate-900">{t("users.listTitle")}</h2>
              <div className="inline-flex items-center gap-2 text-sm text-slate-600">
                <div className="inline-flex rounded-lg border border-slate-200 overflow-hidden">
                  <button
                    type="button"
                    className={`px-3 py-1.5 ${statusFilter === "all" ? "bg-primary text-white" : "bg-white text-slate-600"}`}
                    onClick={() => setStatusFilter("all")}
                  >
                    {t("users.filterAll")}
                  </button>
                  <button
                    type="button"
                    className={`px-3 py-1.5 ${statusFilter === "active" ? "bg-primary text-white" : "bg-white text-slate-600"}`}
                    onClick={() => setStatusFilter("active")}
                  >
                    {t("users.filterActive")}
                  </button>
                  <button
                    type="button"
                    className={`px-3 py-1.5 ${statusFilter === "inactive" ? "bg-primary text-white" : "bg-white text-slate-600"}`}
                    onClick={() => setStatusFilter("inactive")}
                  >
                    {t("users.filterInactive")}
                  </button>
                </div>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-slate-500">
                  <tr>
                    <th className="px-4 py-3 text-left">Nr</th>
                    <th className="px-4 py-3 text-left">{t("users.username")}</th>
                    <th className="px-4 py-3 text-left">{t("users.email")}</th>
                    <th className="px-4 py-3 text-left">{t("users.role")}</th>
                    <th className="px-4 py-3 text-left">{t("users.client")}</th>
                    <th className="px-4 py-3 text-left">{t("users.active")}</th>
                    <th className="px-4 py-3 text-left">{t("users.lastLogin")}</th>
                    <th className="px-4 py-3 text-right">{t("users.actions")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {loading ? (
                    <tr>
                      <td className="px-4 py-4 text-slate-500" colSpan={8}>
                        {t("users.loading")}
                      </td>
                    </tr>
                  ) : filteredUsers.length ? (
                    filteredUsers.map((entry, index) => (
                      <tr key={entry.id}>
                        <td className="px-4 py-3 text-slate-500">{index + 1}</td>
                        <td className="px-4 py-3 font-medium text-slate-900">{entry.username}</td>
                        <td className="px-4 py-3 text-slate-600">{entry.email || "-"}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                              entry.role === "admin"
                                ? "bg-indigo-50 text-indigo-700"
                                : "bg-slate-100 text-slate-700"
                            }`}
                          >
                            {entry.role}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-600">
                          {entry.role === "admin"
                            ? "-"
                            : (
                              Array.isArray(entry.client_branches) && entry.client_branches.length > 0 ? (
                                <div className="flex flex-wrap gap-1">
                                  {entry.client_branches.map((branchId) => (
                                    <span
                                      key={`${entry.id}-${branchId}`}
                                      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700"
                                    >
                                      {branchLabelMap[branchId] || branchId}
                                    </span>
                                  ))}
                                </div>
                              ) : "-"
                            )}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                              entry.is_active ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"
                            }`}
                          >
                            {entry.is_active ? t("users.activeYes") : t("users.activeNo")}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-600">{entry.last_login_at ? new Date(entry.last_login_at).toLocaleString() : "-"}</td>
                        <td className="px-4 py-3 text-right">
                          <div className="inline-flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => openEdit(entry)}
                              className="px-3 py-1.5 rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50"
                            >
                              {t("users.edit")}
                            </button>
                            {entry.role !== "admin" ? (
                              <button
                                type="button"
                                onClick={() => handleToggleActive(entry)}
                                className={`px-3 py-1.5 rounded-lg border ${
                                  entry.is_active
                                    ? "border-amber-200 text-amber-700 hover:bg-amber-50"
                                    : "border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                                }`}
                              >
                                {entry.is_active ? t("users.deactivate") : t("users.activate")}
                              </button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td className="px-4 py-4 text-slate-500" colSpan={8}>
                        {t("users.noUsers")}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </main>

        {editUser ? (
          <div className="bg-white/80 backdrop-blur fixed inset-0 z-40 flex items-center justify-center p-6">
            <div className="w-full max-w-xl bg-surface-light border border-slate-200 rounded-2xl shadow-xl">
              <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
                <h3 className="text-lg font-semibold text-slate-900">{t("users.editTitle")}</h3>
                <button type="button" className="text-slate-500 hover:text-slate-700" onClick={closeEdit}>
                  ✕
                </button>
              </div>
              <form className="p-6 grid grid-cols-1 md:grid-cols-2 gap-4" onSubmit={handleUpdate}>
                <label className="flex flex-col gap-1 text-sm text-slate-600">
                  {t("users.username")}
                  <input
                    className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                    name="username"
                    value={editForm.username}
                    onChange={handleEditChange}
                    autoComplete="off"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm text-slate-600">
                  {t("users.email")}
                  <input
                    className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                    name="email"
                    value={editForm.email}
                    onChange={handleEditChange}
                    autoComplete="off"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm text-slate-600">
                  {t("users.role")}
                  <select
                    className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                    name="role"
                    value={editForm.role}
                    onChange={handleEditChange}
                  >
                    <option value="user">{t("users.roleUser")}</option>
                    <option value="admin">{t("users.roleAdmin")}</option>
                  </select>
                </label>
                {editForm.role === "user" ? (
                  <ClientBranchPicker
                    label={t("users.client")}
                    options={clientOptions}
                    selectedBranchIds={editForm.client_branches}
                    emptyStateLabel={t("users.clientNoneSelected")}
                    helperLabel={t("users.clientPickerHint")}
                    selectAllLabel={t("users.selectAllClients")}
                    clearLabel={t("users.clearClients")}
                    onToggleBranch={handleEditClientBranchToggle}
                    onSelectAll={handleEditSelectAllClientBranches}
                    onClearAll={handleEditClearClientBranches}
                  />
                ) : null}
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input
                    type="checkbox"
                    name="is_active"
                    checked={editForm.is_active}
                    onChange={handleEditChange}
                  />
                  {t("users.active")}
                </label>
                <label className="md:col-span-2 flex flex-col gap-1 text-sm text-slate-600">
                  {t("users.resetPassword")}
                  <input
                    className="rounded-lg border border-slate-200 px-3 py-2 text-slate-900"
                    name="password"
                    type="password"
                    value={editForm.password}
                    onChange={handleEditChange}
                    autoComplete="new-password"
                    placeholder={t("users.resetPasswordHint")}
                  />
                </label>
                <div className="md:col-span-2 flex items-center justify-end gap-3">
                  <button
                    type="button"
                    className="px-4 py-2 rounded-lg border border-slate-200 text-slate-700"
                    onClick={closeEdit}
                  >
                    {t("users.cancel")}
                  </button>
                  <button
                    type="submit"
                    disabled={editSaving}
                    className="px-4 py-2 rounded-lg bg-primary text-white font-semibold disabled:opacity-60"
                  >
                    {editSaving ? t("users.saving") : t("users.saveChanges")}
                  </button>
                </div>
              </form>
            </div>
          </div>
        ) : null}
    </AppShell>
  );
}
