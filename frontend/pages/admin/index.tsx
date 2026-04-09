import { useEffect, useState, useMemo } from "react";
import Head from "next/head";
import Link from "next/link";
import { useAuth } from "../../lib/auth";
import {
  getAdminStats, getAdminUsers, getAdminCharts,
  patchUserPlan, patchUserAdmin, deleteAdminUser,
  type AdminStats, type AdminUser, type AdminCharts,
} from "../../lib/api";
import { useRouter } from "next/router";
import ConfirmDialog from "../../components/ConfirmDialog";
import AdminLineChart from "../../components/AdminLineChart";
import AdminBarChart from "../../components/AdminBarChart";
import OwlLogo from "../../components/OwlLogo";

type UserFilter = "all" | "pro" | "free" | "verified" | "unverified" | "admins" | "active";

interface ConfirmState {
  open: boolean;
  userId: string;
  action: "downgrade" | "remove_admin" | "delete";
  targetEmail: string;
}

export default function AdminPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [show404, setShow404] = useState(false);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [charts, setCharts] = useState<AdminCharts | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [error, setError] = useState("");
  const [toggling, setToggling] = useState<string | null>(null);
  const [togglingAdmin, setTogglingAdmin] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [userFilter, setUserFilter] = useState<UserFilter>("all");
  const [userSearch, setUserSearch] = useState("");
  const [userSort, setUserSort] = useState<"newest" | "oldest" | "top_month" | "top_total" | "recent_login">("newest");
  const [confirmDialog, setConfirmDialog] = useState<ConfirmState | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!user || !user.is_admin) {
      setShow404(true);
      return;
    }
    loadData();
  }, [user, loading]);

  async function loadData() {
    setLoadingData(true);
    try {
      const [s, u, c] = await Promise.all([getAdminStats(), getAdminUsers(), getAdminCharts()]);
      setStats(s);
      setUsers(u);
      setCharts(c);
    } catch (e: any) {
      setError(e.message || "Failed to load admin data");
    } finally {
      setLoadingData(false);
    }
  }

  async function togglePlan(userId: string, currentPlan: "free" | "pro") {
    const newPlan = currentPlan === "free" ? "pro" : "free";
    setToggling(userId);
    try {
      await patchUserPlan(userId, newPlan);
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, plan: newPlan } : u));
      if (stats) {
        setStats({
          ...stats,
          free_users: newPlan === "pro" ? stats.free_users - 1 : stats.free_users + 1,
          pro_users: newPlan === "pro" ? stats.pro_users + 1 : stats.pro_users - 1,
        });
      }
    } catch (e: any) {
      setError(e.message || "Failed to update plan");
    } finally {
      setToggling(null);
    }
  }

  async function toggleAdmin(userId: string, currentIsAdmin: boolean) {
    setTogglingAdmin(userId);
    try {
      await patchUserAdmin(userId, !currentIsAdmin);
      setUsers((prev) =>
        prev.map((u) =>
          u.id === userId
            ? { ...u, is_admin: !currentIsAdmin, plan: !currentIsAdmin ? "pro" : "free" }
            : u
        )
      );
    } catch (e: any) {
      setError(e.message || "Failed to update admin status");
    } finally {
      setTogglingAdmin(null);
    }
  }

  function handlePlanButtonClick(u: AdminUser) {
    if (u.plan === "pro") {
      // Downgrade is destructive — confirm first
      setConfirmDialog({ open: true, userId: u.id, action: "downgrade", targetEmail: u.email });
    } else {
      // Upgrade is non-destructive — proceed immediately
      togglePlan(u.id, u.plan as "free" | "pro");
    }
  }

  function handleAdminButtonClick(u: AdminUser) {
    if (u.is_admin) {
      // Removal is destructive — confirm first
      setConfirmDialog({ open: true, userId: u.id, action: "remove_admin", targetEmail: u.email });
    } else {
      // Grant is non-destructive — proceed immediately
      toggleAdmin(u.id, u.is_admin);
    }
  }

  async function deleteUser(userId: string) {
    setDeleting(userId);
    try {
      await deleteAdminUser(userId);
      setUsers((prev) => prev.filter((u) => u.id !== userId));
    } catch (e: any) {
      setError(e.message || "Failed to delete user");
    } finally {
      setDeleting(null);
    }
  }

  function handleConfirm() {
    if (!confirmDialog) return;
    const { userId, action } = confirmDialog;
    setConfirmDialog(null);
    if (action === "downgrade") {
      togglePlan(userId, "pro");
    } else if (action === "remove_admin") {
      toggleAdmin(userId, true);
    } else {
      deleteUser(userId);
    }
  }

  const filteredUsers = useMemo(() => {
    const now = Date.now();
    let list = users;
    if (userFilter === "pro")        list = users.filter((u) => u.plan === "pro");
    if (userFilter === "free")       list = users.filter((u) => u.plan === "free");
    if (userFilter === "verified")   list = users.filter((u) => u.is_verified);
    if (userFilter === "unverified") list = users.filter((u) => !u.is_verified);
    if (userFilter === "admins")     list = users.filter((u) => u.is_admin);
    if (userFilter === "active")     list = users.filter((u) =>
      u.last_login && (now - new Date(u.last_login).getTime()) < 30 * 24 * 60 * 60 * 1000
    );
    if (userSearch.trim()) {
      const q = userSearch.toLowerCase();
      list = list.filter((u) => u.email.toLowerCase().includes(q));
    }
    list = [...list].sort((a, b) => {
      switch (userSort) {
        case "oldest":       return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
        case "top_month":    return b.analyses_this_month - a.analyses_this_month;
        case "top_total":    return b.analysis_count - a.analysis_count;
        case "recent_login": {
          if (!a.last_login && !b.last_login) return 0;
          if (!a.last_login) return 1;
          if (!b.last_login) return -1;
          return new Date(b.last_login).getTime() - new Date(a.last_login).getTime();
        }
        default:             return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      }
    });
    return list;
  }, [users, userFilter, userSearch, userSort]);

  // Tab counts from full (unfiltered) list
  const tabCounts: Record<UserFilter, number> = useMemo(() => {
    const now = Date.now();
    return {
      all: users.length,
      pro: users.filter((u) => u.plan === "pro").length,
      free: users.filter((u) => u.plan === "free").length,
      verified: users.filter((u) => u.is_verified).length,
      unverified: users.filter((u) => !u.is_verified).length,
      admins: users.filter((u) => u.is_admin).length,
      active: users.filter((u) => u.last_login && (now - new Date(u.last_login).getTime()) < 30 * 24 * 60 * 60 * 1000).length,
    };
  }, [users]);

  if (loading) return null;
  if (show404 || !user || !user.is_admin) {
    return (
      <>
        <Head><title>404 — Hootly</title></Head>
        <div className="min-h-screen bg-slate-50 flex items-center justify-center">
          <div className="text-center">
            <h1 className="text-6xl font-bold text-slate-300 mb-4">404</h1>
            <p className="text-slate-500 mb-6">This page could not be found.</p>
            <Link href="/" className="text-blue-600 hover:underline font-medium">Go home</Link>
          </div>
        </div>
      </>
    );
  }

  const FILTER_TABS: { key: UserFilter; label: string }[] = [
    { key: "all", label: "All" },
    { key: "pro", label: "Pro" },
    { key: "free", label: "Free" },
    { key: "verified", label: "Verified" },
    { key: "unverified", label: "Unverified" },
    { key: "admins", label: "Admins" },
    { key: "active", label: "Active (30d)" },
  ];

  return (
    <>
      <Head>
        <title>Admin — Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50">
        {/* Header */}
        <header className="bg-white border-b border-slate-200 shadow-sm">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 h-24 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/" className="flex items-center gap-2">
                <OwlLogo size={90} />
              </Link>
              <span className="text-xl text-slate-300">/</span>
              <span className="text-xl font-semibold text-slate-700">Admin</span>
            </div>
            <div className="flex items-center gap-4 text-sm">
              <span className="text-slate-500 hidden sm:block">{user.email}</span>
              <Link href="/" className="text-slate-600 hover:text-slate-900 font-medium transition-colors">← Home</Link>
            </div>
          </div>
        </header>

        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-10">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm flex items-center gap-2">
              <span className="text-red-400">⚠</span> {error}
            </div>
          )}

          {/* Stats cards */}
          <section>
            <h2 className="text-base font-semibold text-slate-500 uppercase tracking-wider mb-4">Overview</h2>
            {loadingData ? (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                {[...Array(7)].map((_, i) => (
                  <div key={i} className="bg-white border border-slate-200 rounded-2xl p-5 h-24 animate-pulse" />
                ))}
              </div>
            ) : stats ? (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <StatCard label="Total users"     value={stats.total_users} />
                <StatCard label="Free users"      value={stats.free_users} />
                <StatCard label="Pro users"       value={stats.pro_users}           accent="blue" />
                <StatCard label="Total analyses"  value={stats.total_analyses} />
                <StatCard label="Completed"       value={stats.completed_analyses}  accent="green" />
                <StatCard label="Signups (30d)"   value={stats.recent_signups_30d}  accent="indigo" />
                <StatCard label="Analyses today"  value={stats.analyses_today}      accent="amber" />
              </div>
            ) : null}
          </section>

          {/* Charts */}
          <section>
            <h2 className="text-base font-semibold text-slate-500 uppercase tracking-wider mb-4">Trends — last 30 days</h2>
            {loadingData ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white border border-slate-200 rounded-2xl p-6 h-56 animate-pulse" />
                <div className="bg-white border border-slate-200 rounded-2xl p-6 h-56 animate-pulse" />
              </div>
            ) : charts ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
                  <p className="text-sm font-semibold text-slate-700 mb-4">Daily Analyses</p>
                  <AdminLineChart data={charts.daily_analyses} />
                </div>
                <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
                  <p className="text-sm font-semibold text-slate-700 mb-4">Daily Signups</p>
                  <AdminBarChart data={charts.daily_signups} />
                </div>
              </div>
            ) : null}
          </section>

          {/* Users table */}
          <section>
            <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
              <h2 className="text-base font-semibold text-slate-500 uppercase tracking-wider">
                Users <span className="text-slate-300 font-normal normal-case">({filteredUsers.length})</span>
              </h2>

              {/* Filter tabs */}
              <div className="flex flex-wrap gap-1 sm:ml-2">
                {FILTER_TABS.map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => setUserFilter(key)}
                    className={`text-xs font-medium px-2.5 py-1 rounded-full transition-colors ${
                      userFilter === key
                        ? "bg-slate-800 text-white"
                        : "bg-white border border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-700"
                    }`}
                  >
                    {label} <span className="opacity-60">{tabCounts[key]}</span>
                  </button>
                ))}
              </div>

              {/* Sort */}
              <select
                value={userSort}
                onChange={(e) => setUserSort(e.target.value as typeof userSort)}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="newest">Newest</option>
                <option value="oldest">Oldest</option>
                <option value="top_month">Top this month</option>
                <option value="top_total">Top all time</option>
                <option value="recent_login">Recent login</option>
              </select>

              {/* Search */}
              <div className="relative sm:ml-auto">
                <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clipRule="evenodd" />
                </svg>
                <input
                  type="text"
                  placeholder="Search by email…"
                  value={userSearch}
                  onChange={(e) => setUserSearch(e.target.value)}
                  className="text-sm border border-slate-200 rounded-lg pl-8 pr-3 py-1.5 w-full sm:w-56 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
              {loadingData ? (
                <div className="p-12 text-center text-slate-400 text-sm">Loading…</div>
              ) : filteredUsers.length === 0 ? (
                <div className="p-12 text-center text-slate-400 text-sm">No users match the current filter.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-100 bg-slate-50/80">
                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">User</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Plan</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider hidden sm:table-cell">Status</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider hidden md:table-cell">Analyses</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider hidden lg:table-cell">Joined</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider hidden lg:table-cell">Last login</th>
                        <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-50">
                      {filteredUsers.map((u) => (
                        <tr key={u.id} className="hover:bg-slate-50/60 transition-colors group">
                          {/* User */}
                          <td className="px-4 py-3.5">
                            <div className="font-medium text-slate-800">{u.email}</div>
                            {u.is_admin && (
                              <span className="inline-flex items-center mt-0.5 text-xs bg-purple-100 text-purple-700 rounded-full px-2 py-0.5 font-medium">
                                admin
                              </span>
                            )}
                          </td>
                          {/* Plan */}
                          <td className="px-4 py-3.5">
                            <span className={`inline-flex items-center text-xs font-semibold rounded-full px-2.5 py-1 ${
                              u.plan === "pro"
                                ? "bg-blue-100 text-blue-700"
                                : "bg-slate-100 text-slate-500"
                            }`}>
                              {u.plan === "pro" ? "✦ Pro" : "Free"}
                            </span>
                          </td>
                          {/* Status */}
                          <td className="px-4 py-3.5 hidden sm:table-cell">
                            {u.is_verified ? (
                              <span className="inline-flex items-center text-xs font-medium text-emerald-600">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1.5" />Verified
                              </span>
                            ) : (
                              <span className="inline-flex items-center text-xs font-medium text-amber-600">
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 mr-1.5" />Unverified
                              </span>
                            )}
                          </td>
                          {/* Analyses */}
                          <td className="px-4 py-3.5 hidden md:table-cell">
                            {u.plan === "free" ? (
                              <>
                                <span className="text-slate-800 font-medium">{u.analyses_this_month}</span>
                                <span className="text-slate-400"> / 1</span>
                              </>
                            ) : (
                              <span className="text-slate-800 font-medium">{u.analysis_count}</span>
                            )}
                          </td>
                          {/* Joined */}
                          <td className="px-4 py-3.5 text-slate-500 hidden lg:table-cell whitespace-nowrap">
                            {new Date(u.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                          </td>
                          {/* Last login */}
                          <td className="px-4 py-3.5 text-slate-500 hidden lg:table-cell whitespace-nowrap">
                            {u.last_login
                              ? new Date(u.last_login).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
                              : <span className="text-slate-300">Never</span>}
                          </td>
                          {/* Actions */}
                          <td className="px-4 py-3.5">
                            <div className="flex items-center justify-end gap-1.5">
                              {/* Plan toggle */}
                              {!u.is_admin && u.id !== user.id && (
                                <button
                                  onClick={() => handlePlanButtonClick(u)}
                                  disabled={toggling === u.id}
                                  className={`text-xs font-semibold px-2.5 py-1 rounded-lg transition-colors disabled:opacity-40 ${
                                    u.plan === "pro"
                                      ? "bg-slate-100 hover:bg-slate-200 text-slate-600"
                                      : "bg-blue-600 hover:bg-blue-700 text-white"
                                  }`}
                                >
                                  {toggling === u.id ? "…" : u.plan === "pro" ? "→ Free" : "→ Pro"}
                                </button>
                              )}
                              {/* Admin toggle */}
                              {u.id !== user.id && (
                                <button
                                  onClick={() => handleAdminButtonClick(u)}
                                  disabled={togglingAdmin === u.id}
                                  className={`text-xs font-semibold px-2.5 py-1 rounded-lg transition-colors disabled:opacity-40 ${
                                    u.is_admin
                                      ? "bg-purple-100 hover:bg-purple-200 text-purple-700"
                                      : "bg-slate-100 hover:bg-slate-200 text-slate-600"
                                  }`}
                                >
                                  {togglingAdmin === u.id ? "…" : u.is_admin ? "− Admin" : "+ Admin"}
                                </button>
                              )}
                              {/* Delete */}
                              {u.id !== user.id && !u.is_admin && (
                                <>
                                  <span className="w-px h-4 bg-slate-200 mx-0.5" />
                                  <button
                                    onClick={() => setConfirmDialog({ open: true, userId: u.id, action: "delete", targetEmail: u.email })}
                                    disabled={deleting === u.id}
                                    title="Delete user"
                                    className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors disabled:opacity-40"
                                  >
                                    {deleting === u.id ? (
                                      <span className="text-xs">…</span>
                                    ) : (
                                      <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                                        <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                                      </svg>
                                    )}
                                  </button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section>
        </main>
      </div>

      {/* Confirm dialog */}
      {confirmDialog && (
        <ConfirmDialog
          open={confirmDialog.open}
          title={
            confirmDialog.action === "downgrade" ? "Downgrade to Free?" :
            confirmDialog.action === "remove_admin" ? "Remove admin access?" :
            "Delete user?"
          }
          message={
            confirmDialog.action === "downgrade"
              ? `This will downgrade ${confirmDialog.targetEmail} to the Free plan and restrict their analysis limit.`
              : confirmDialog.action === "remove_admin"
              ? `This will remove admin access from ${confirmDialog.targetEmail}. They will no longer be able to access this dashboard.`
              : `This will permanently delete ${confirmDialog.targetEmail} and all their analyses. This cannot be undone.`
          }
          confirmLabel={
            confirmDialog.action === "downgrade" ? "Downgrade" :
            confirmDialog.action === "remove_admin" ? "Remove admin" :
            "Delete user"
          }
          confirmVariant="danger"
          onConfirm={handleConfirm}
          onCancel={() => setConfirmDialog(null)}
        />
      )}
    </>
  );
}

function StatCard({ label, value, accent }: { label: string; value: number; accent?: "blue" | "green" | "indigo" | "amber" }) {
  const border = accent ? ({
    blue:   "border-l-blue-400",
    green:  "border-l-emerald-400",
    indigo: "border-l-indigo-400",
    amber:  "border-l-amber-400",
  } as const)[accent] : "border-l-slate-200";

  const valueColor = accent ? ({
    blue:   "text-blue-700",
    green:  "text-emerald-700",
    indigo: "text-indigo-700",
    amber:  "text-amber-700",
  } as const)[accent] : "text-slate-900";

  return (
    <div className={`bg-white border border-slate-200 border-l-4 ${border} rounded-2xl p-5 shadow-sm`}>
      <p className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">{label}</p>
      <p className={`text-3xl font-bold ${valueColor}`}>{value.toLocaleString()}</p>
    </div>
  );
}
