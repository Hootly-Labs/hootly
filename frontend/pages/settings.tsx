import { useState, useEffect, FormEvent } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRequireAuth } from "../lib/auth";
import {
  getSettings,
  updateSettings,
  changePassword,
  deleteAccount,
  createCheckoutSession,
  createPortalSession,
  getBillingUsage,
  startGithubConnect,
  disconnectGithub,
  createApiKey,
  listApiKeys,
  revokeApiKey,
  type ApiKeyInfo,
  type ApiKeyCreated,
} from "../lib/api";
import OwlLogo from "../components/OwlLogo";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Palette,
  User,
  Lock,
  Bell,
  Key,
  AlertTriangle,
  Sun,
  Moon,
  Github,
  Check,
  CreditCard,
  Zap,
  Copy,
  Trash2,
  ArrowRight,
  Eye,
  EyeOff,
  Globe,
  Shield,
  Monitor,
  Grip,
  Code,
  Network,
  Loader2,
} from "lucide-react";

type Tab = "appearance" | "account" | "privacy" | "notifications" | "api-keys" | "danger";

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "appearance", label: "Appearance", icon: <Palette className="w-4 h-4" /> },
  { id: "account",    label: "Account",    icon: <User className="w-4 h-4" /> },
  { id: "privacy",    label: "Privacy",    icon: <Lock className="w-4 h-4" /> },
  { id: "notifications", label: "Notifications", icon: <Bell className="w-4 h-4" /> },
  { id: "api-keys",   label: "API Keys",   icon: <Key className="w-4 h-4" /> },
  { id: "danger",     label: "Danger Zone", icon: <AlertTriangle className="w-4 h-4" /> },
];

function SavedBadge({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span className="ml-2 text-xs text-emerald-600 font-medium animate-pulse flex items-center gap-1">
      <Check className="w-3 h-3" />
      Saved
    </span>
  );
}

export default function SettingsPage() {
  const { user, logout, loading } = useRequireAuth();
  const [tab, setTab] = useState<Tab>("appearance");

  // ── Appearance ──────────────────────────────────────────────────────────────
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [codeFont, setCodeFont] = useState<"mono" | "sans">("mono");
  const [compactMode, setCompactMode] = useState(false);
  const [graphColor, setGraphColor] = useState<"language" | "directory">("language");
  const [themeSaved, setThemeSaved] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("theme");
    if (saved === "dark") setTheme("dark");
    else setTheme("light");
    setCodeFont((localStorage.getItem("hl_code_font") as "mono" | "sans") || "mono");
    setCompactMode(localStorage.getItem("hl_compact") === "1");
    setGraphColor((localStorage.getItem("hl_graph_color") as "language" | "directory") || "language");
  }, []);

  function applyTheme(t: "light" | "dark") {
    setTheme(t);
    localStorage.setItem("theme", t);
    document.documentElement.classList.toggle("dark", t === "dark");
    setThemeSaved(true);
    setTimeout(() => setThemeSaved(false), 2000);
  }

  function saveAppearancePref(key: string, value: string) {
    localStorage.setItem(key, value);
    setThemeSaved(true);
    setTimeout(() => setThemeSaved(false), 2000);
  }

  function applyCompact(compact: boolean) {
    document.documentElement.dataset.compact = compact ? "1" : "0";
  }

  function applyCodeFont(font: "mono" | "sans") {
    document.documentElement.dataset.codeFont = font;
  }

  // ── Account / Billing ───────────────────────────────────────────────────────
  const [usage, setUsage] = useState<{ analyses_this_month: number; limit: number | null } | null>(null);
  const [billingLoading, setBillingLoading] = useState(false);

  useEffect(() => {
    if (user) {
      getBillingUsage().then(u => setUsage({ analyses_this_month: u.analyses_this_month, limit: u.limit })).catch(() => {});
    }
  }, [user]);

  async function handleUpgrade() {
    setBillingLoading(true);
    try {
      const { url } = await createCheckoutSession();
      window.location.href = url;
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Something went wrong");
    }
    setBillingLoading(false);
  }

  async function handleManageBilling() {
    setBillingLoading(true);
    try {
      const { url } = await createPortalSession();
      window.location.href = url;
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Something went wrong");
    }
    setBillingLoading(false);
  }

  // GitHub connect
  const [ghLoading, setGhLoading] = useState(false);
  const [ghError, setGhError] = useState("");
  const [ghConnectedToast, setGhConnectedToast] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("connected") === "github") {
      setGhConnectedToast(true);
      setTimeout(() => setGhConnectedToast(false), 4000);
      window.history.replaceState({}, "", "/settings");
    }
  }, []);

  // Change password
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwError, setPwError] = useState("");
  const [pwSuccess, setPwSuccess] = useState(false);
  const [pwLoading, setPwLoading] = useState(false);

  async function handleChangePassword(e: FormEvent) {
    e.preventDefault();
    if (newPw !== confirmPw) { setPwError("Passwords do not match."); return; }
    setPwError(""); setPwLoading(true); setPwSuccess(false);
    try {
      await changePassword(oldPw, newPw);
      setPwSuccess(true);
      setOldPw(""); setNewPw(""); setConfirmPw("");
    } catch (err: unknown) {
      setPwError(err instanceof Error ? err.message : "Failed to change password.");
    } finally {
      setPwLoading(false);
    }
  }

  // ── Privacy ─────────────────────────────────────────────────────────────────
  const [defaultVisibility, setDefaultVisibility] = useState<"private" | "public">("private");
  const [visibilitySaved, setVisibilitySaved] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("hl_default_visibility");
    if (saved === "public") setDefaultVisibility("public");
  }, []);

  function saveVisibility(v: "private" | "public") {
    setDefaultVisibility(v);
    localStorage.setItem("hl_default_visibility", v);
    setVisibilitySaved(true);
    setTimeout(() => setVisibilitySaved(false), 2000);
  }

  // ── Notifications ───────────────────────────────────────────────────────────
  const [notify, setNotify] = useState(false);
  const [notifyLoading, setNotifyLoading] = useState(false);
  const [notifySuccess, setNotifySuccess] = useState(false);

  useEffect(() => {
    if (user) {
      getSettings().then((s) => setNotify(s.notify_on_complete)).catch(() => {});
    }
  }, [user]);

  // ── API Keys ───────────────────────────────────────────────────────────────
  const [apiKeys, setApiKeys] = useState<ApiKeyInfo[]>([]);
  const [apiKeysLoaded, setApiKeysLoaded] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyResult, setNewKeyResult] = useState<ApiKeyCreated | null>(null);
  const [apiKeyLoading, setApiKeyLoading] = useState(false);
  const [apiKeyError, setApiKeyError] = useState("");
  const [keyCopied, setKeyCopied] = useState(false);

  useEffect(() => {
    if (tab === "api-keys" && !apiKeysLoaded && user) {
      listApiKeys().then((keys) => { setApiKeys(keys); setApiKeysLoaded(true); }).catch(() => {});
    }
  }, [tab, apiKeysLoaded, user]);

  async function handleCreateApiKey() {
    const name = newKeyName.trim();
    if (!name) { setApiKeyError("Please enter a name."); return; }
    setApiKeyLoading(true);
    setApiKeyError("");
    try {
      const result = await createApiKey(name);
      setNewKeyResult(result);
      setNewKeyName("");
      setApiKeys((prev) => [{ id: result.id, prefix: result.prefix, name: result.name, last_used: null, created_at: result.created_at }, ...prev]);
    } catch (err: unknown) {
      setApiKeyError(err instanceof Error ? err.message : "Failed to create API key");
    }
    setApiKeyLoading(false);
  }

  async function handleRevokeApiKey(keyId: string) {
    if (!confirm("Revoke this API key? Any integrations using it will stop working.")) return;
    try {
      await revokeApiKey(keyId);
      setApiKeys((prev) => prev.filter((k) => k.id !== keyId));
    } catch {
      alert("Failed to revoke API key.");
    }
  }

  // ── Danger Zone ─────────────────────────────────────────────────────────────
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteError, setDeleteError] = useState("");

  async function handleDeleteAccount() {
    if (deleteConfirm !== "delete my account") {
      setDeleteError('Type "delete my account" to confirm.');
      return;
    }
    setDeleteLoading(true);
    try {
      await deleteAccount();
      logout();
    } catch (err: unknown) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete account.");
      setDeleteLoading(false);
    }
  }

  if (loading || !user) return null;

  return (
    <>
      <Head><title>Settings — Hootly</title></Head>
      <div className="min-h-screen bg-slate-50">
        <header className="bg-white border-b border-slate-200">
          <div className="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/dashboard" className="flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
                <OwlLogo size={72} />
              </Link>
              <span className="text-xl text-slate-300">/</span>
              <span className="text-lg font-semibold text-slate-700">Settings</span>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild>
                <Link href="/analyses">History</Link>
              </Button>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/analytics">Analytics</Link>
              </Button>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/team">Teams</Link>
              </Button>
              <Separator orientation="vertical" className="h-4 mx-1" />
              <Button variant="ghost" size="sm" asChild>
                <Link href="/dashboard">
                  <ArrowRight className="w-3 h-3 rotate-180" />
                  Dashboard
                </Link>
              </Button>
            </div>
          </div>
        </header>

        <main className="max-w-5xl mx-auto px-4 sm:px-6 py-10">
          <div className="flex flex-col sm:flex-row gap-8">

            {/* Sidebar */}
            <nav className="sm:w-52 shrink-0">
              <ul className="space-y-0.5">
                {TABS.map((t) => (
                  <li key={t.id}>
                    <button
                      onClick={() => setTab(t.id)}
                      className={`w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium transition-colors flex items-center gap-2.5 ${
                        tab === t.id
                          ? "bg-blue-50 text-blue-700"
                          : t.id === "danger"
                          ? "text-red-600 hover:bg-red-50"
                          : "text-slate-600 hover:bg-slate-100"
                      }`}
                    >
                      {t.icon}
                      {t.label}
                    </button>
                  </li>
                ))}
              </ul>

              {/* Plan badge in sidebar */}
              <div className="mt-6 px-3 py-3 bg-slate-100 rounded-xl">
                <p className="text-xs text-muted-foreground mb-1">Current plan</p>
                {user.plan === "pro" ? (
                  <Badge className="bg-blue-600">
                    <Zap className="w-3 h-3 mr-1" />
                    Pro
                  </Badge>
                ) : (
                  <Badge variant="secondary">Free</Badge>
                )}
                {usage && user.plan === "free" && (
                  <p className="text-xs text-muted-foreground mt-1">{usage.analyses_this_month} / {usage.limit} analyses this month</p>
                )}
              </div>
            </nav>

            {/* Content */}
            <div className="flex-1 space-y-5">

              {/* ── Appearance ── */}
              {tab === "appearance" && (
                <>
                  <Section title="Theme" description="Choose how Hootly looks for you." icon={<Sun className="w-4 h-4" />}>
                    <div className="space-y-2">
                      {([
                        { id: "light", icon: <Sun className="w-5 h-5" />, label: "Light", desc: "Always use light mode" },
                        { id: "dark",  icon: <Moon className="w-5 h-5" />, label: "Dark",  desc: "Always use dark mode" },
                      ] as const).map((t) => (
                        <label key={t.id} className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                          theme === t.id ? "border-blue-400 bg-blue-50" : "border-slate-200 hover:border-slate-300"
                        }`}>
                          <input type="radio" name="theme" value={t.id} checked={theme === t.id}
                            onChange={() => applyTheme(t.id)} className="accent-blue-600" />
                          <span className="text-slate-500">{t.icon}</span>
                          <div>
                            <p className="text-sm font-medium text-slate-900">{t.label}</p>
                            <p className="text-xs text-muted-foreground">{t.desc}</p>
                          </div>
                        </label>
                      ))}
                    </div>
                  </Section>

                  <Section title="Display density" description="Adjust how information is spaced on the page." icon={<Grip className="w-4 h-4" />} trailing={<SavedBadge show={themeSaved} />}>
                    <div className="flex gap-3">
                      {[
                        { id: "0", label: "Comfortable", desc: "More whitespace, easier to read", icon: <Monitor className="w-4 h-4" /> },
                        { id: "1", label: "Compact",     desc: "Denser layout, more content visible", icon: <Grip className="w-4 h-4" /> },
                      ].map((opt) => (
                        <label key={opt.id} className={`flex-1 flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                          compactMode === (opt.id === "1") ? "border-blue-400 bg-blue-50" : "border-slate-200 hover:border-slate-300"
                        }`}>
                          <input type="radio" name="density" value={opt.id}
                            checked={compactMode === (opt.id === "1")}
                            onChange={() => { const v = opt.id === "1"; setCompactMode(v); saveAppearancePref("hl_compact", v ? "1" : "0"); applyCompact(v); }}
                            className="accent-blue-600 mt-0.5" />
                          <div>
                            <p className="text-sm font-medium text-slate-900">{opt.label}</p>
                            <p className="text-xs text-muted-foreground">{opt.desc}</p>
                          </div>
                        </label>
                      ))}
                    </div>
                  </Section>

                  <Section title="Code font" description="Font used for file paths, key exports, and inline code." icon={<Code className="w-4 h-4" />} trailing={<SavedBadge show={themeSaved} />}>
                    <div className="flex gap-3">
                      {[
                        { id: "mono", label: "Monospace", example: "backend/api/routes.py" },
                        { id: "sans", label: "Sans-serif", example: "backend/api/routes.py" },
                      ].map((opt) => (
                        <label key={opt.id} className={`flex-1 flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                          codeFont === opt.id ? "border-blue-400 bg-blue-50" : "border-slate-200 hover:border-slate-300"
                        }`}>
                          <input type="radio" name="codeFont" value={opt.id} checked={codeFont === opt.id}
                            onChange={() => { setCodeFont(opt.id as "mono" | "sans"); saveAppearancePref("hl_code_font", opt.id); applyCodeFont(opt.id as "mono" | "sans"); }}
                            className="accent-blue-600 mt-0.5" />
                          <div>
                            <p className="text-sm font-medium text-slate-900">{opt.label}</p>
                            <p className={`text-xs text-muted-foreground mt-1 ${opt.id === "mono" ? "font-mono" : "font-sans"}`} style={opt.id === "sans" ? { fontFamily: "ui-sans-serif, system-ui, sans-serif" } : {}}>
                              {opt.example}
                            </p>
                          </div>
                        </label>
                      ))}
                    </div>
                  </Section>

                  <Section title="Dependency graph color" description="Default color mode when opening the dependency graph tab." icon={<Network className="w-4 h-4" />} trailing={<SavedBadge show={themeSaved} />}>
                    <div className="flex gap-3">
                      {([
                        { id: "language",  label: "By language",  desc: "Color nodes by programming language" },
                        { id: "directory", label: "By directory", desc: "Color nodes by top-level folder" },
                      ] as const).map((opt) => (
                        <label key={opt.id} className={`flex-1 flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                          graphColor === opt.id ? "border-blue-400 bg-blue-50" : "border-slate-200 hover:border-slate-300"
                        }`}>
                          <input type="radio" name="graphColor" value={opt.id} checked={graphColor === opt.id}
                            onChange={() => { setGraphColor(opt.id); saveAppearancePref("hl_graph_color", opt.id); }}
                            className="accent-blue-600 mt-0.5" />
                          <div>
                            <p className="text-sm font-medium text-slate-900">{opt.label}</p>
                            <p className="text-xs text-muted-foreground mt-0.5">{opt.desc}</p>
                          </div>
                        </label>
                      ))}
                    </div>
                  </Section>
                </>
              )}

              {/* ── Account ── */}
              {tab === "account" && (
                <>
                  {/* Profile info */}
                  <Section title="Profile" icon={<User className="w-4 h-4" />}>
                    <div className="space-y-3">
                      <Row label="Email">
                        <span className="text-sm text-slate-700 font-medium">{user.email}</span>
                        {user.is_verified ? (
                          <Badge variant="secondary" className="ml-2 bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
                            <Check className="w-3 h-3 mr-1" />
                            Verified
                          </Badge>
                        ) : (
                          <Badge variant="secondary" className="ml-2 bg-amber-100 text-amber-700 hover:bg-amber-100">
                            Unverified
                          </Badge>
                        )}
                      </Row>
                      <Row label="Plan">
                        {user.plan === "pro" ? (
                          <Badge className="bg-blue-600">
                            <Zap className="w-3 h-3 mr-1" />
                            Pro
                          </Badge>
                        ) : (
                          <Badge variant="secondary">Free</Badge>
                        )}
                      </Row>
                      {usage && (
                        <Row label="Usage this month">
                          <span className="text-sm text-slate-700">
                            {usage.analyses_this_month}{usage.limit !== null ? ` / ${usage.limit}` : ""} analyses
                          </span>
                        </Row>
                      )}
                      <Row label="GitHub">
                        {user.github_connected ? (
                          <div className="flex items-center gap-2">
                            <Badge variant="secondary" className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
                              <Check className="w-3 h-3 mr-1" />
                              Connected
                            </Badge>
                            {user.github_username && (
                              <span className="text-xs font-mono text-slate-600">@{user.github_username}</span>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={async () => {
                                setGhLoading(true);
                                setGhError("");
                                try {
                                  await disconnectGithub();
                                  window.location.reload();
                                } catch (err: unknown) {
                                  setGhError(err instanceof Error ? err.message : "Failed to disconnect");
                                } finally {
                                  setGhLoading(false);
                                }
                              }}
                              disabled={ghLoading}
                              className="text-slate-500 hover:text-red-600 h-7"
                            >
                              {ghLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Disconnect"}
                            </Button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="text-sm text-muted-foreground">Not connected</span>
                            <Button
                              size="sm"
                              onClick={async () => { window.location.href = await startGithubConnect(); }}
                              className="bg-[#24292f] hover:bg-[#1b1f24] text-white h-7"
                            >
                              <Github className="w-3.5 h-3.5 mr-1" />
                              Connect GitHub
                            </Button>
                          </div>
                        )}
                      </Row>
                      {ghError && (
                        <p className="text-xs text-red-600 mt-1">{ghError}</p>
                      )}
                      {ghConnectedToast && (
                        <p className="text-xs text-emerald-600 mt-1 flex items-center gap-1">
                          <Check className="w-3 h-3" />
                          GitHub connected successfully.
                        </p>
                      )}
                    </div>
                  </Section>

                  {/* Billing */}
                  <Section title="Billing" description="Manage your subscription." icon={<CreditCard className="w-4 h-4" />}>
                    {user.plan === "free" ? (
                      <div className="flex items-center justify-between p-4 bg-blue-50 border border-blue-200 rounded-xl">
                        <div>
                          <p className="text-sm font-semibold text-slate-900">Upgrade to Pro</p>
                          <p className="text-xs text-muted-foreground mt-0.5">Unlimited analyses · Repos up to 10,000 files · $15/mo</p>
                        </div>
                        <Button onClick={handleUpgrade} disabled={billingLoading}>
                          {billingLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : (
                            <>
                              <Zap className="w-4 h-4 mr-1" />
                              Upgrade
                            </>
                          )}
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-between p-4 bg-emerald-50 border border-emerald-200 rounded-xl">
                        <div>
                          <p className="text-sm font-semibold text-slate-900 flex items-center gap-1">
                            <Zap className="w-4 h-4 text-blue-600" />
                            Pro plan active
                          </p>
                          <p className="text-xs text-muted-foreground mt-0.5">Unlimited analyses · Cancel or change card any time</p>
                        </div>
                        <Button variant="outline" onClick={handleManageBilling} disabled={billingLoading}>
                          {billingLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Manage"}
                        </Button>
                      </div>
                    )}
                  </Section>

                  {/* Change password — only for email users */}
                  {user && (
                    <Section title="Change password" description="Must be 10+ characters with uppercase, lowercase, number, and special character." icon={<Lock className="w-4 h-4" />}>
                      <form onSubmit={handleChangePassword} className="space-y-4 max-w-sm">
                        <div>
                          <label className="block text-sm font-medium text-slate-700 mb-1">Current password</label>
                          <Input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} required />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-slate-700 mb-1">New password</label>
                          <Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} required minLength={10} />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-slate-700 mb-1">Confirm new password</label>
                          <Input type="password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} required />
                        </div>
                        {pwError && (
                          <Card className="border-red-200 bg-red-50">
                            <CardContent className="py-2 px-4 text-sm text-red-600">{pwError}</CardContent>
                          </Card>
                        )}
                        {pwSuccess && (
                          <Card className="border-emerald-200 bg-emerald-50">
                            <CardContent className="py-2 px-4 text-sm text-emerald-700 flex items-center gap-1">
                              <Check className="w-3 h-3" />
                              Password updated successfully.
                            </CardContent>
                          </Card>
                        )}
                        <Button type="submit" disabled={pwLoading}>
                          {pwLoading ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : null}
                          {pwLoading ? "Saving…" : "Update password"}
                        </Button>
                      </form>
                    </Section>
                  )}
                </>
              )}

              {/* ── Privacy ── */}
              {tab === "privacy" && (
                <>
                  <Section title="Default analysis visibility" description="Controls whether new analyses are public or private when created." icon={<Eye className="w-4 h-4" />} trailing={<SavedBadge show={visibilitySaved} />}>
                    <div className="space-y-2">
                      {([
                        { id: "private", label: "Private", desc: "Only you can see your analyses (recommended)", icon: <Lock className="w-5 h-5" /> },
                        { id: "public",  label: "Public",  desc: "Anyone with the link can view your analyses", icon: <Globe className="w-5 h-5" /> },
                      ] as const).map((opt) => (
                        <label key={opt.id} className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                          defaultVisibility === opt.id ? "border-blue-400 bg-blue-50" : "border-slate-200 hover:border-slate-300"
                        }`}>
                          <input type="radio" name="visibility" value={opt.id} checked={defaultVisibility === opt.id}
                            onChange={() => saveVisibility(opt.id)} className="accent-blue-600" />
                          <span className="text-slate-500">{opt.icon}</span>
                          <div>
                            <p className="text-sm font-medium text-slate-900">{opt.label}</p>
                            <p className="text-xs text-muted-foreground">{opt.desc}</p>
                          </div>
                        </label>
                      ))}
                    </div>
                    <p className="mt-3 text-xs text-muted-foreground">
                      You can toggle visibility on any individual analysis after it&apos;s created.
                    </p>
                  </Section>

                  <Section title="Data & analysis history" description="Your analyses are stored securely and are never shared without your permission." icon={<Shield className="w-4 h-4" />}>
                    <div className="space-y-3 text-sm text-slate-600">
                      {[
                        "Analysis results are tied to your account only",
                        "Private repo access token stored securely and only used for cloning — disconnect any time",
                        "Cloned repos are deleted immediately after analysis",
                        "You can delete all your data at any time in the Danger Zone",
                      ].map((text, i) => (
                        <div key={i} className="flex items-start gap-2">
                          <Check className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                          <span>{text}</span>
                        </div>
                      ))}
                    </div>
                  </Section>
                </>
              )}

              {/* ── Notifications ── */}
              {tab === "notifications" && (
                <Section title="Email notifications" description="Choose when Hootly emails you. Requires SMTP to be configured." icon={<Bell className="w-4 h-4" />}>
                  <div className="space-y-3">
                    <Toggle
                      label="Email me when analysis completes"
                      description="Useful for large repos that take a while to process."
                      checked={notify}
                      loading={notifyLoading}
                      saved={notifySuccess}
                      onChange={async (val) => {
                        setNotify(val);
                        setNotifyLoading(true);
                        setNotifySuccess(false);
                        try {
                          await updateSettings(val);
                          setNotifySuccess(true);
                          setTimeout(() => setNotifySuccess(false), 2000);
                        } catch {}
                        setNotifyLoading(false);
                      }}
                    />
                  </div>
                </Section>
              )}

              {/* ── API Keys ── */}
              {tab === "api-keys" && (
                <>
                  <Section title="API Keys" description="Use API keys to authenticate programmatic access to Hootly's API and MCP server." icon={<Key className="w-4 h-4" />}>
                    {/* Create new key */}
                    {newKeyResult ? (
                      <Card className="border-emerald-200 bg-emerald-50 mb-4">
                        <CardContent className="py-4">
                          <p className="text-sm font-semibold text-emerald-800 mb-2 flex items-center gap-1">
                            <Check className="w-4 h-4" />
                            API key created! Copy it now — you won&apos;t see it again.
                          </p>
                          <div className="flex items-center gap-2">
                            <code className="flex-1 bg-white border border-emerald-200 rounded-lg px-3 py-2 text-sm font-mono text-slate-800 break-all">
                              {newKeyResult.key}
                            </code>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                navigator.clipboard.writeText(newKeyResult.key);
                                setKeyCopied(true);
                                setTimeout(() => setKeyCopied(false), 2000);
                              }}
                              className="shrink-0"
                            >
                              {keyCopied ? <Check className="w-3 h-3 mr-1" /> : <Copy className="w-3 h-3 mr-1" />}
                              {keyCopied ? "Copied!" : "Copy"}
                            </Button>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setNewKeyResult(null)}
                            className="mt-2"
                          >
                            Done
                          </Button>
                        </CardContent>
                      </Card>
                    ) : (
                      <div className="flex items-end gap-3 mb-4">
                        <div className="flex-1">
                          <label className="block text-sm font-medium text-slate-700 mb-1">Key name</label>
                          <Input
                            type="text"
                            value={newKeyName}
                            onChange={(e) => setNewKeyName(e.target.value)}
                            placeholder="e.g. MCP Server, CI Pipeline"
                            maxLength={100}
                          />
                        </div>
                        <Button
                          onClick={handleCreateApiKey}
                          disabled={apiKeyLoading}
                        >
                          {apiKeyLoading ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Key className="w-4 h-4 mr-1" />}
                          {apiKeyLoading ? "Creating..." : "Create key"}
                        </Button>
                      </div>
                    )}
                    {apiKeyError && <p className="text-sm text-red-600 mb-3">{apiKeyError}</p>}

                    {/* Existing keys */}
                    {apiKeys.length > 0 ? (
                      <div className="space-y-2">
                        {apiKeys.map((k) => (
                          <div key={k.id} className="flex items-center justify-between p-3 border border-slate-200 rounded-xl">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <Key className="w-3.5 h-3.5 text-muted-foreground" />
                                <span className="text-sm font-medium text-slate-800">{k.name}</span>
                                <code className="text-xs text-muted-foreground font-mono">{k.prefix}...</code>
                              </div>
                              <div className="text-xs text-muted-foreground mt-0.5 ml-5.5">
                                Created {new Date(k.created_at).toLocaleDateString()}
                                {k.last_used && ` · Last used ${new Date(k.last_used).toLocaleDateString()}`}
                              </div>
                            </div>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleRevokeApiKey(k.id)}
                              className="text-red-500 hover:text-red-700 hover:bg-red-50 shrink-0"
                            >
                              <Trash2 className="w-3 h-3 mr-1" />
                              Revoke
                            </Button>
                          </div>
                        ))}
                      </div>
                    ) : apiKeysLoaded ? (
                      <p className="text-sm text-muted-foreground text-center py-4">No API keys yet.</p>
                    ) : null}
                  </Section>

                  <Section title="Usage" description="API keys can be used with the Hootly API and MCP server." icon={<Code className="w-4 h-4" />}>
                    <div className="space-y-3 text-sm text-slate-600">
                      <div>
                        <p className="font-medium text-slate-800 mb-1">REST API</p>
                        <code className="block bg-slate-100 rounded-lg p-3 text-xs text-slate-700 break-all">
                          curl -H &quot;X-API-Key: hk_your_key&quot; https://api.hootlylabs.com/api/analyses
                        </code>
                      </div>
                      <div>
                        <p className="font-medium text-slate-800 mb-1">MCP Server</p>
                        <code className="block bg-slate-100 rounded-lg p-3 text-xs text-slate-700 break-all">
                          HOOTLY_API_KEY=hk_your_key python mcp_server.py
                        </code>
                      </div>
                    </div>
                  </Section>
                </>
              )}

              {/* ── Danger Zone ── */}
              {tab === "danger" && (
                <Card className="border-red-200">
                  <CardContent className="pt-6">
                    <h2 className="text-lg font-bold text-red-700 mb-1 flex items-center gap-2">
                      <AlertTriangle className="w-5 h-5" />
                      Danger Zone
                    </h2>
                    <p className="text-sm text-muted-foreground mb-6">
                      Permanently delete your account and all your analyses. This cannot be undone.
                    </p>
                    <div className="space-y-3 max-w-sm">
                      <label className="block text-sm font-medium text-slate-700">
                        Type <code className="bg-slate-100 px-1.5 py-0.5 rounded text-red-600 text-xs">delete my account</code> to confirm
                      </label>
                      <Input
                        type="text"
                        value={deleteConfirm}
                        onChange={(e) => setDeleteConfirm(e.target.value)}
                        placeholder="delete my account"
                      />
                      {deleteError && <p className="text-sm text-red-600">{deleteError}</p>}
                      <Button
                        variant="destructive"
                        onClick={handleDeleteAccount}
                        disabled={deleteLoading || deleteConfirm !== "delete my account"}
                      >
                        {deleteLoading ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Trash2 className="w-4 h-4 mr-1" />}
                        {deleteLoading ? "Deleting…" : "Delete my account"}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}

            </div>
          </div>
        </main>
      </div>
    </>
  );
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function Section({ title, description, children, trailing, icon }: {
  title: string;
  description?: string;
  children: React.ReactNode;
  trailing?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center mb-1 gap-2">
          {icon && <span className="text-muted-foreground">{icon}</span>}
          <h2 className="text-base font-bold text-slate-900">{title}</h2>
          {trailing}
        </div>
        {description && <p className="text-sm text-muted-foreground mb-5">{description}</p>}
        {!description && <div className="mb-4" />}
        {children}
      </CardContent>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-slate-100 last:border-0">
      <span className="text-sm text-muted-foreground w-36 shrink-0">{label}</span>
      <div className="flex items-center">{children}</div>
    </div>
  );
}

function Toggle({ label, description, checked, loading, saved, onChange }: {
  label: string;
  description: string;
  checked: boolean;
  loading: boolean;
  saved: boolean;
  onChange: (val: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer p-3 rounded-xl border border-slate-200 hover:border-slate-300 transition-colors">
      <div className="relative mt-0.5">
        <input
          type="checkbox"
          checked={checked}
          disabled={loading}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only"
        />
        <button
          type="button"
          onClick={() => !loading && onChange(!checked)}
          className={`w-9 h-5 rounded-full transition-colors ${checked ? "bg-blue-600" : "bg-slate-200"}`}
        >
          <div className={`w-4 h-4 bg-white rounded-full shadow transition-transform mt-0.5 ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
        </button>
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-slate-900">{label}</p>
          {saved && (
            <span className="text-xs text-emerald-600 font-medium flex items-center gap-1">
              <Check className="w-3 h-3" />
              Saved
            </span>
          )}
          {loading && <span className="text-xs text-muted-foreground">Saving…</span>}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
      </div>
    </label>
  );
}
