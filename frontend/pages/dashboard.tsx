import { useEffect, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useRequireAuth } from "../lib/auth";
import {
  startAnalysis,
  getRecentAnalyses,
  getGithubRepos,
  startGithubConnect,
  createCheckoutSession,
  createPortalSession,
  getWatches,
  getAlerts,
  markAlertRead,
  type Analysis,
  type GithubRepo,
  type WatchedRepo,
  type DriftAlert,
} from "../lib/api";
import UpgradeModal from "../components/UpgradeModal";
import ConnectGitHubModal from "../components/ConnectGitHubModal";
import OwlLogo from "../components/OwlLogo";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  History,
  BarChart3,
  Users,
  Settings,
  Shield,
  LogOut,
  Github,
  Star,
  Lock,
  Folder,
  Search,
  Loader2,
  ArrowRight,
  Bell,
  Eye,
  Menu,
  Zap,
  AlertTriangle,
  Info,
  XCircle,
} from "lucide-react";

export default function DashboardPage() {
  const router = useRouter();
  const { user, logout, loading: authLoading } = useRequireAuth();

  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showUpgrade, setShowUpgrade] = useState<false | "limit" | "size">(false);
  const [showConnectGitHub, setShowConnectGitHub] = useState<string | false>(false);
  const [repos, setRepos] = useState<GithubRepo[]>([]);
  const [reposLoading, setReposLoading] = useState(false);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [watches, setWatches] = useState<WatchedRepo[]>([]);
  const [alerts, setAlerts] = useState<DriftAlert[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [repoQuery, setRepoQuery] = useState("");
  const [repoTab, setRepoTab] = useState<"all" | "starred">("all");
  const [repoLang, setRepoLang] = useState("all");
  const [repoSort, setRepoSort] = useState<"updated" | "name" | "analyzed">("updated");
  const [reposPage, setReposPage] = useState(1);
  const [hasMoreRepos, setHasMoreRepos] = useState(false);
  const [reposLoadingMore, setReposLoadingMore] = useState(false);

  // Persist tab selection
  useEffect(() => {
    try {
      const saved = localStorage.getItem("hootly_repo_tab");
      if (saved === "all" || saved === "starred") setRepoTab(saved as "all" | "starred");
    } catch {}
  }, []);

  // Load repos + recent analyses when user is available
  useEffect(() => {
    if (!user) return;
    if (user.github_connected) {
      setReposLoading(true);
      getGithubRepos(1).then((data) => {
        setRepos(data);
        setHasMoreRepos(data.length === 100);
      }).finally(() => setReposLoading(false));
    }
    getRecentAnalyses().then(setAnalyses).catch(() => {});
    getWatches().then(setWatches).catch(() => {});
    getAlerts(false, false, 5).then(setAlerts).catch(() => {});
  }, [user]);

  // Handle ?url= query param (from GitHub connect callback)
  useEffect(() => {
    if (!router.isReady || !user) return;
    const pendingUrl = router.query.url as string | undefined;
    if (pendingUrl) {
      const decoded = decodeURIComponent(pendingUrl);
      setUrl(decoded);
      router.replace("/dashboard", undefined, { shallow: true });
      handleAnalyze(decoded);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router.isReady, user]);

  async function handleAnalyze(target?: string) {
    const repoUrl = (target ?? url).trim();
    if (!repoUrl) return;
    setError("");
    setLoading(true);
    try {
      const data = await startAnalysis(repoUrl);
      router.push(`/analysis/${data.id}`);
    } catch (err: unknown) {
      const msg: string = err instanceof Error ? err.message : "Something went wrong";
      if (msg.toLowerCase().includes("free plan limit")) {
        setShowUpgrade("limit");
      } else if (msg.toLowerCase().includes("upgrade to pro")) {
        setShowUpgrade("size");
      } else if (msg === "PRIVATE_REPO_NO_TOKEN") {
        setShowConnectGitHub(repoUrl);
      } else if (msg === "PRIVATE_REPO_TOKEN_INVALID") {
        setError("Your GitHub token has expired. Go to Settings > Account to reconnect.");
      } else {
        setError(msg);
      }
      setLoading(false);
    }
  }

  function handleRepoClick(repo: GithubRepo) {
    const repoUrl = `https://github.com/${repo.full_name}`;
    setUrl(repoUrl);
    handleAnalyze(repoUrl);
  }

  async function handleUpgradeClick() {
    try {
      const { url: checkoutUrl } = await createCheckoutSession();
      window.location.href = checkoutUrl;
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Could not start checkout.");
    }
  }

  async function handleManageBilling() {
    try {
      const { url: portalUrl } = await createPortalSession();
      window.location.href = portalUrl;
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Could not open billing portal.");
    }
  }

  function switchRepoTab(tab: "all" | "starred") {
    setRepoTab(tab);
    setRepoQuery("");
    try { localStorage.setItem("hootly_repo_tab", tab); } catch {}
  }

  async function loadMoreRepos() {
    setReposLoadingMore(true);
    const nextPage = reposPage + 1;
    try {
      const more = await getGithubRepos(nextPage);
      setRepos((prev) => [...prev, ...more]);
      setReposPage(nextPage);
      setHasMoreRepos(more.length === 100);
    } finally {
      setReposLoadingMore(false);
    }
  }

  const recentAnalyses = analyses.slice(0, 5);
  const starredAnalyses = analyses.filter((a) => a.is_starred).slice(0, 5);
  const changedWatchCount = watches.filter((w) => w.last_changed_at).length;
  const debouncedQuery = useDebounce(repoQuery, 150);
  const languages = Array.from(new Set(repos.map((r) => r.language).filter(Boolean))).sort() as string[];
  const analyzedFullNames = new Set(
    analyses
      .filter((a) => a.status === "completed")
      .map((a) => { const m = a.repo_url?.match(/github\.com\/([^/?#]+\/[^/?#]+)/); return m ? m[1] : null; })
      .filter((x): x is string => Boolean(x))
  );
  const filteredRepos = repos
    .filter((r) => {
      const matchesQuery = r.name.toLowerCase().includes(debouncedQuery.toLowerCase());
      const matchesTab = repoTab === "all" || r.github_starred;
      const matchesLang = repoLang === "all" || r.language === repoLang;
      return matchesQuery && matchesTab && matchesLang;
    })
    .sort((a, b) => {
      if (repoSort === "name") return a.name.localeCompare(b.name);
      if (repoSort === "analyzed") {
        const aA = analyzedFullNames.has(a.full_name) ? 1 : 0;
        const bA = analyzedFullNames.has(b.full_name) ? 1 : 0;
        return bA - aA || a.name.localeCompare(b.name);
      }
      return 0;
    });
  const githubStarredCount = repos.filter((r) => r.github_starred).length;

  if (authLoading || !user) return null;

  return (
    <>
      <Head><title>Dashboard — Hootly</title></Head>

      {showUpgrade && <UpgradeModal reason={showUpgrade} onDismiss={() => setShowUpgrade(false)} />}
      {showConnectGitHub && (
        <ConnectGitHubModal repoUrl={showConnectGitHub} onDismiss={() => setShowConnectGitHub(false)} />
      )}

      <div className="flex h-screen overflow-hidden bg-slate-50">
        {/* Mobile sidebar overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/40 lg:hidden"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Sidebar */}
        <aside className={`fixed inset-y-0 left-0 z-30 w-64 bg-white border-r border-slate-200 flex flex-col overflow-hidden transform transition-transform duration-200 lg:relative lg:translate-x-0 ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}`}>
          {/* Logo */}
          <div className="h-16 flex items-center px-4 border-b border-slate-100 shrink-0">
            <OwlLogo size={72} />
          </div>

          {/* Scrollable content */}
          <div className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
            {/* GitHub Repos */}
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest px-2 mb-2">
                Your GitHub Repos
              </p>
              {user.github_connected ? (
                reposLoading ? (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="h-8 bg-slate-100 animate-pulse rounded-lg" />
                    ))}
                  </div>
                ) : repos.length > 0 ? (
                  <div className="space-y-2">
                    {/* Filter tabs */}
                    <div className="flex gap-1 px-1">
                      <button
                        onClick={() => switchRepoTab("all")}
                        className={`text-xs px-2 py-0.5 rounded-full transition-colors ${repoTab === "all" ? "bg-slate-200 text-slate-700 font-medium" : "text-slate-400 hover:text-slate-600"}`}
                      >
                        All ({repos.length})
                      </button>
                      <button
                        onClick={() => switchRepoTab("starred")}
                        className={`text-xs px-2 py-0.5 rounded-full transition-colors flex items-center gap-1 ${repoTab === "starred" ? "bg-slate-200 text-slate-700 font-medium" : "text-slate-400 hover:text-slate-600"}`}
                      >
                        <Star className="w-3 h-3" /> Starred ({githubStarredCount})
                      </button>
                    </div>
                    {/* Search */}
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                      <Input
                        type="text"
                        value={repoQuery}
                        onChange={(e) => setRepoQuery(e.target.value)}
                        placeholder="Search repos..."
                        className="h-7 pl-7 text-xs"
                      />
                    </div>
                    {/* Sort + Language */}
                    <div className="flex gap-1.5">
                      <select
                        value={repoSort}
                        onChange={(e) => setRepoSort(e.target.value as "updated" | "name" | "analyzed")}
                        className="flex-1 text-xs px-1.5 py-1.5 rounded-md border border-input bg-background text-slate-500 focus:outline-none focus:border-slate-400"
                      >
                        <option value="updated">Recent</option>
                        <option value="name">A-Z</option>
                        <option value="analyzed">Analyzed</option>
                      </select>
                      {languages.length > 0 && (
                        <select
                          value={repoLang}
                          onChange={(e) => setRepoLang(e.target.value)}
                          className="flex-1 text-xs px-1.5 py-1.5 rounded-md border border-input bg-background text-slate-500 focus:outline-none focus:border-slate-400"
                        >
                          <option value="all">All langs</option>
                          {languages.map((lang) => (
                            <option key={lang} value={lang}>{lang}</option>
                          ))}
                        </select>
                      )}
                    </div>
                    {/* Repo list */}
                    {filteredRepos.length > 0 ? (
                      <div className="space-y-0.5">
                        {filteredRepos.map((repo) => (
                          <button
                            key={repo.full_name}
                            title={repo.description || repo.full_name}
                            onClick={() => handleRepoClick(repo)}
                            className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-left hover:bg-accent transition-colors"
                          >
                            {repo.private ? (
                              <Lock className="w-3 h-3 text-slate-400 shrink-0" />
                            ) : (
                              <Folder className="w-3 h-3 text-slate-400 shrink-0" />
                            )}
                            <span className="text-sm text-slate-700 truncate font-mono flex-1">{repo.name}</span>
                            {analyzedFullNames.has(repo.full_name) && (
                              <span title="Previously analyzed" className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                            )}
                            {repo.github_starred && (
                              <Star className="w-3 h-3 text-amber-400 fill-amber-400 shrink-0" />
                            )}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground px-2">No repos match your filters.</p>
                    )}
                    {/* Load more */}
                    {hasMoreRepos && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={loadMoreRepos}
                        disabled={reposLoadingMore}
                        className="w-full justify-start text-xs text-muted-foreground"
                      >
                        {reposLoadingMore ? (
                          <><Loader2 className="w-3 h-3 animate-spin" /> Loading...</>
                        ) : (
                          <>Load more <ArrowRight className="w-3 h-3" /></>
                        )}
                      </Button>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground px-2">No repos found.</p>
                )
              ) : (
                <div className="px-2 space-y-2">
                  <p className="text-xs text-muted-foreground">Not connected</p>
                  <Button
                    size="sm"
                    onClick={async () => { window.location.href = await startGithubConnect(); }}
                    className="bg-[#24292f] hover:bg-[#1b1f24] text-white"
                  >
                    <Github className="w-3.5 h-3.5" />
                    Connect GitHub
                  </Button>
                </div>
              )}
            </div>

            {/* Recent */}
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest px-2 mb-2">Recent</p>
              {recentAnalyses.length > 0 ? (
                <div className="space-y-0.5">
                  {recentAnalyses.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => router.push(`/analysis/${a.id}`)}
                      className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left hover:bg-accent transition-colors"
                    >
                      <StatusDot status={a.status} />
                      <span className="text-sm text-slate-700 truncate flex-1 font-mono">{a.repo_name}</span>
                      <span className="text-xs text-muted-foreground shrink-0">{relativeTime(a.created_at)}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground px-2">No analyses yet.</p>
              )}
            </div>

            {/* Favorites */}
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest px-2 mb-2">Favorites</p>
              {starredAnalyses.length > 0 ? (
                <div className="space-y-0.5">
                  {starredAnalyses.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => router.push(`/analysis/${a.id}`)}
                      className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left hover:bg-accent transition-colors"
                    >
                      <Star className="w-3 h-3 text-amber-400 fill-amber-400 shrink-0" />
                      <span className="text-sm text-slate-700 truncate flex-1 font-mono">{a.repo_name}</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground px-2">No favorites yet.</p>
              )}
            </div>

            {/* Watching */}
            <div>
              <div className="flex items-center justify-between px-2 mb-2">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Watching</p>
                {changedWatchCount > 0 && (
                  <Badge variant="secondary" className="text-[10px] bg-amber-100 text-amber-700 hover:bg-amber-100">
                    {changedWatchCount} changed
                  </Badge>
                )}
              </div>
              {watches.length > 0 ? (
                <>
                  <div className="space-y-0.5">
                    {[...watches]
                      .sort((a, b) => (b.last_changed_at ? 1 : 0) - (a.last_changed_at ? 1 : 0))
                      .slice(0, 5)
                      .map((w) => {
                        const repoAnalyses = analyses
                          .filter((a) => a.repo_url === w.repo_url && a.status === "completed")
                          .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
                        const changelogAnalysis = repoAnalyses.find((a) => a.changelog);
                        const latestAnalysis = repoAnalyses[0];
                        const target = changelogAnalysis ?? latestAnalysis;
                        const hasChange = !!w.last_changed_at;

                        return (
                          <button
                            key={w.id}
                            onClick={() => target ? router.push(`/analysis/${target.id}`) : router.push("/analyses")}
                            className={`w-full flex items-start gap-2 px-2 py-2 rounded-lg text-left transition-colors ${
                              hasChange ? "bg-amber-50 hover:bg-amber-100 border border-amber-200" : "hover:bg-accent"
                            }`}
                          >
                            {hasChange ? (
                              <Bell className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
                            ) : (
                              <Eye className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
                            )}
                            <div className="flex-1 min-w-0">
                              <div className={`text-sm font-mono truncate ${hasChange ? "text-slate-900 font-semibold" : "text-slate-700"}`}>
                                {w.repo_name}
                              </div>
                              {hasChange ? (
                                <div className="flex items-center gap-1 mt-0.5">
                                  <span className="text-xs text-amber-600">Changed {relativeTime(w.last_changed_at!)}</span>
                                  {w.last_commit_hash && (
                                    <span className="text-xs text-muted-foreground font-mono">· {w.last_commit_hash.slice(0, 7)}</span>
                                  )}
                                </div>
                              ) : (
                                <div className="text-xs text-muted-foreground mt-0.5">No changes yet</div>
                              )}
                            </div>
                          </button>
                        );
                      })}
                  </div>
                  {watches.length > 5 && (
                    <Button variant="ghost" size="sm" className="w-full justify-start text-xs text-muted-foreground" onClick={() => router.push("/analyses")}>
                      +{watches.length - 5} more <ArrowRight className="w-3 h-3" />
                    </Button>
                  )}
                </>
              ) : (
                <p className="text-xs text-muted-foreground px-2">No watched repos yet. Open an analysis and click Watch.</p>
              )}
            </div>
          </div>

          {/* Bottom nav */}
          <Separator />
          <div className="p-3 space-y-0.5 shrink-0">
            <Button variant="ghost" size="sm" asChild className="w-full justify-start gap-2.5">
              <Link href="/analyses"><History className="w-4 h-4" /> History</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild className="w-full justify-start gap-2.5">
              <Link href="/alerts"><Bell className="w-4 h-4" /> Alerts</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild className="w-full justify-start gap-2.5">
              <Link href="/analytics"><BarChart3 className="w-4 h-4" /> Analytics</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild className="w-full justify-start gap-2.5">
              <Link href="/team"><Users className="w-4 h-4" /> Teams</Link>
            </Button>
            <Button variant="ghost" size="sm" asChild className="w-full justify-start gap-2.5">
              <Link href="/settings"><Settings className="w-4 h-4" /> Settings</Link>
            </Button>
            {user.is_admin && (
              <Button variant="ghost" size="sm" asChild className="w-full justify-start gap-2.5">
                <Link href="/admin"><Shield className="w-4 h-4" /> Admin</Link>
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={logout} className="w-full justify-start gap-2.5 text-muted-foreground">
              <LogOut className="w-4 h-4" /> Log out
            </Button>
          </div>
        </aside>

        {/* Main area */}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">
          {/* Top bar */}
          <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-4 sm:px-6 shrink-0">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSidebarOpen(true)}
                className="lg:hidden"
                aria-label="Open sidebar"
              >
                <Menu className="h-5 w-5" />
              </Button>
              <span className="text-lg font-semibold text-slate-700">Dashboard</span>
            </div>
            <div className="flex items-center gap-2">
              {user.plan === "free" ? (
                <Button variant="outline" size="sm" onClick={handleUpgradeClick} className="hidden sm:inline-flex text-amber-700 border-amber-200 bg-amber-50 hover:bg-amber-100 hover:text-amber-800">
                  <Zap className="w-3.5 h-3.5" />
                  Free plan · Upgrade
                </Button>
              ) : (
                <Button variant="outline" size="sm" onClick={handleManageBilling} className="hidden sm:inline-flex text-blue-700 border-blue-200 bg-blue-50 hover:bg-blue-100 hover:text-blue-800">
                  Manage billing
                </Button>
              )}
              <span className="hidden sm:block text-sm text-muted-foreground">{user.email}</span>
              <Button variant="ghost" size="sm" onClick={logout}>
                Log out
              </Button>
            </div>
          </header>

          {/* Content */}
          <main className="flex-1 overflow-y-auto flex flex-col items-center justify-center px-4 py-12">
            <div className="w-full max-w-2xl">
              {/* Alerts summary card */}
              {alerts.length > 0 && (
                <Card className="mb-6 border-slate-200">
                  <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
                    <div className="flex items-center gap-2">
                      <Bell className="w-4 h-4 text-slate-500" />
                      <span className="text-sm font-semibold text-slate-700">Recent Alerts</span>
                      <Badge variant="secondary" className="text-xs bg-red-100 text-red-700 hover:bg-red-100">
                        {alerts.length} new
                      </Badge>
                    </div>
                    <Link href="/alerts" className="text-xs text-blue-600 hover:text-blue-800 font-medium">
                      View all &rarr;
                    </Link>
                  </div>
                  <CardContent className="p-0">
                    {alerts.map((alert) => (
                      <button
                        key={alert.id}
                        onClick={async () => {
                          await markAlertRead(alert.id);
                          setAlerts((prev) => prev.filter((a) => a.id !== alert.id));
                          // Navigate to latest analysis for the repo
                          const match = analyses.find((a) => a.repo_url === alert.repo_url && a.status === "completed");
                          if (match) router.push(`/analysis/${match.id}`);
                        }}
                        className="w-full flex items-start gap-3 px-4 py-3 border-b border-slate-50 last:border-0 hover:bg-slate-50 transition-colors text-left"
                      >
                        {alert.severity === "critical" ? (
                          <XCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
                        ) : alert.severity === "warning" ? (
                          <AlertTriangle className="w-4 h-4 text-yellow-500 mt-0.5 shrink-0" />
                        ) : (
                          <Info className="w-4 h-4 text-blue-500 mt-0.5 shrink-0" />
                        )}
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-slate-800 truncate">{alert.message}</p>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {alert.repo_url.replace("https://github.com/", "")} &middot; {relativeTime(alert.created_at)}
                          </p>
                        </div>
                      </button>
                    ))}
                  </CardContent>
                </Card>
              )}

              <div className="text-center mb-8">
                <div className="mb-3 flex justify-center"><OwlLogo size={90} /></div>
                <h1 className="text-2xl font-bold text-slate-900 mb-2">Analyze a repository</h1>
                <p className="text-muted-foreground text-sm">
                  Select a repo from the sidebar or paste a GitHub URL below.
                </p>
              </div>

              {/* Analysis form */}
              <div className="space-y-3">
                <div className="flex gap-3 items-stretch">
                  <Input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleAnalyze(); }}
                    placeholder="https://github.com/owner/repo"
                    className="flex-1 h-12 text-base"
                    disabled={loading}
                  />
                  <Button
                    onClick={() => handleAnalyze()}
                    disabled={loading || !url.trim()}
                    size="lg"
                    className="px-6 shrink-0"
                  >
                    {loading ? (
                      <><Loader2 className="w-4 h-4 animate-spin" /> Analyzing...</>
                    ) : (
                      <>Analyze <ArrowRight className="w-4 h-4" /></>
                    )}
                  </Button>
                </div>

                {error && (
                  <Card className="border-red-200 bg-red-50">
                    <CardContent className="p-3">
                      <p className="text-sm text-red-600">{error}</p>
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
          </main>
        </div>
      </div>
    </>
  );
}

function StatusDot({ status }: { status: string }) {
  if (status === "completed") {
    return <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />;
  }
  if (status === "failed") {
    return <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" />;
  }
  return <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse shrink-0" />;
}

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}
