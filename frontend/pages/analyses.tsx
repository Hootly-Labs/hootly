import { useEffect, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useRequireAuth } from "../lib/auth";
import { getRecentAnalyses, startAnalysis, toggleStar, getWatches, unwatchRepo, type Analysis, type WatchedRepo } from "../lib/api";
import OwlLogo from "../components/OwlLogo";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Search,
  Star,
  Eye,
  RefreshCw,
  Loader2,
  ArrowRight,
  CheckCircle,
  XCircle,
  Inbox,
  Globe,
  GitCommit,
  Clock,
  ExternalLink,
} from "lucide-react";

type Filter = "all" | "starred" | "completed" | "failed";
type MainTab = "history" | "watching";

export default function AnalysesPage() {
  const { user, loading } = useRequireAuth();
  const router = useRouter();
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [reanalyzing, setReanalyzing] = useState<string | null>(null);
  const [starring, setStarring] = useState<string | null>(null);
  const [mainTab, setMainTab] = useState<MainTab>("history");
  const [watches, setWatches] = useState<WatchedRepo[]>([]);
  const [unwatching, setUnwatching] = useState<string | null>(null);

  useEffect(() => {
    if (loading || !user) return;
    getRecentAnalyses()
      .then(setAnalyses)
      .catch((e) => setError(e.message))
      .finally(() => setFetching(false));
    getWatches().then(setWatches).catch(() => {});
  }, [user, loading]);

  async function handleUnwatch(w: WatchedRepo) {
    setUnwatching(w.id);
    try {
      await unwatchRepo(w.id);
      setWatches((prev) => prev.filter((x) => x.id !== w.id));
    } catch {}
    setUnwatching(null);
  }

  async function handleReanalyze(a: Analysis) {
    setReanalyzing(a.id);
    try {
      const fresh = await startAnalysis(a.repo_url, true);
      router.push(`/analysis/${fresh.id}`);
    } catch (e: any) {
      setError(e.message);
      setReanalyzing(null);
    }
  }

  async function handleStar(a: Analysis) {
    setStarring(a.id);
    try {
      const { is_starred } = await toggleStar(a.id);
      setAnalyses((prev) => prev.map((x) => x.id === a.id ? { ...x, is_starred } : x));
    } catch {}
    setStarring(null);
  }

  const filtered = analyses.filter((a) => {
    if (search && !a.repo_name.toLowerCase().includes(search.toLowerCase())) return false;
    if (filter === "starred" && !a.is_starred) return false;
    if (filter === "completed" && a.status !== "completed") return false;
    if (filter === "failed" && a.status !== "failed") return false;
    return true;
  });

  if (loading || !user) return null;

  return (
    <>
      <Head><title>{mainTab === "watching" ? "Watching — Hootly" : "Analysis History — Hootly"}</title></Head>
      <div className="min-h-screen bg-slate-50">
        <header className="bg-white border-b border-slate-200">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/dashboard" className="flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
                <OwlLogo size={72} />
              </Link>
              <span className="text-xl text-slate-300">/</span>
              <span className="text-lg font-semibold text-slate-700">History</span>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild>
                <Link href="/analytics">Analytics</Link>
              </Button>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/team">Teams</Link>
              </Button>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/settings">Settings</Link>
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

        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
          {/* Main tab switcher */}
          <div className="flex items-center gap-1 mb-6 bg-slate-100 p-1 rounded-xl w-fit">
            <button
              onClick={() => setMainTab("history")}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5 ${mainTab === "history" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
            >
              <Clock className="w-3.5 h-3.5" />
              History
            </button>
            <button
              onClick={() => setMainTab("watching")}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5 ${mainTab === "watching" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
            >
              <Eye className="w-3.5 h-3.5" />
              Watching
              {watches.length > 0 && (
                <Badge variant="secondary" className="text-xs px-1.5 py-0 h-5">
                  {watches.length}
                </Badge>
              )}
            </button>
          </div>

          {mainTab === "watching" && (
            <WatchingPanel watches={watches} unwatching={unwatching} onUnwatch={handleUnwatch} />
          )}

          {mainTab === "history" && (<>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-6">
            <h1 className="text-xl font-bold text-slate-900 flex-1">Your analyses</h1>

            {/* Search */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Search repos…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8 w-52 h-9"
              />
            </div>

            {/* Filter tabs */}
            <div className="flex gap-1 bg-slate-100 p-1 rounded-lg">
              {(["all", "starred", "completed", "failed"] as Filter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1 rounded-md text-xs font-medium transition-colors capitalize flex items-center gap-1 ${
                    filter === f ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
                  }`}
                >
                  {f === "starred" && <Star className="w-3 h-3" />}
                  {f === "starred" ? "Favorites" : f}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <Card className="border-red-200 bg-red-50 mb-6">
              <CardContent className="py-3 px-4 text-red-700 text-sm">{error}</CardContent>
            </Card>
          )}

          <Card>
            {fetching ? (
              <CardContent className="py-8 text-center">
                <Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">Loading…</p>
              </CardContent>
            ) : filtered.length === 0 ? (
              <CardContent className="py-12 text-center">
                <Inbox className="w-8 h-8 mx-auto text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">
                  {search || filter !== "all" ? "No analyses match your filter." : "No analyses yet."}
                </p>
                {!search && filter === "all" && (
                  <Button variant="link" size="sm" asChild className="mt-2">
                    <Link href="/dashboard">
                      Analyze your first repo
                      <ArrowRight className="w-3 h-3 ml-1" />
                    </Link>
                  </Button>
                )}
              </CardContent>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 bg-slate-50/50">
                      <th className="text-left px-4 py-3 font-semibold text-muted-foreground w-6"></th>
                      <th className="text-left px-4 py-3 font-semibold text-muted-foreground">Repository</th>
                      <th className="text-left px-4 py-3 font-semibold text-muted-foreground">Status</th>
                      <th className="text-left px-4 py-3 font-semibold text-muted-foreground hidden sm:table-cell">Date</th>
                      <th className="px-4 py-3 text-right font-semibold text-muted-foreground">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((a) => (
                      <tr key={a.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/50 transition-colors">
                        {/* Star */}
                        <td className="px-4 py-3">
                          <button
                            onClick={() => handleStar(a)}
                            disabled={starring === a.id}
                            className="transition-colors disabled:opacity-50"
                            title={a.is_starred ? "Remove from favorites" : "Add to favorites"}
                          >
                            <Star className={`w-4 h-4 ${a.is_starred ? "text-amber-400 fill-amber-400" : "text-slate-300 hover:text-amber-400"}`} />
                          </button>
                        </td>
                        {/* Repo */}
                        <td className="px-4 py-3">
                          <div className="font-mono text-sm font-semibold text-slate-800">{a.repo_name}</div>
                          <div className="text-xs text-muted-foreground truncate max-w-xs">{a.repo_url}</div>
                        </td>
                        {/* Status */}
                        <td className="px-4 py-3">
                          <StatusBadge status={a.status} fromCache={a.from_cache} isPublic={a.is_public} />
                        </td>
                        {/* Date */}
                        <td className="px-4 py-3 text-muted-foreground hidden sm:table-cell whitespace-nowrap">
                          {new Date(a.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                        </td>
                        {/* Actions */}
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            {a.status === "completed" && (
                              <Button size="sm" asChild>
                                <Link href={`/analysis/${a.id}`}>
                                  <ExternalLink className="w-3 h-3 mr-1" />
                                  View
                                </Link>
                              </Button>
                            )}
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleReanalyze(a)}
                              disabled={reanalyzing === a.id}
                            >
                              {reanalyzing === a.id ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <RefreshCw className="w-3 h-3 mr-1" />
                              )}
                              {reanalyzing === a.id ? "" : "Re-analyze"}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          </>)}
        </main>
      </div>
    </>
  );
}

function WatchingPanel({
  watches,
  unwatching,
  onUnwatch,
}: {
  watches: WatchedRepo[];
  unwatching: string | null;
  onUnwatch: (w: WatchedRepo) => void;
}) {
  if (watches.length === 0) {
    return (
      <Card className="mb-6">
        <CardContent className="py-12 text-center">
          <Eye className="w-8 h-8 mx-auto text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">You&apos;re not watching any repos yet.</p>
          <p className="text-xs text-muted-foreground mt-1">
            Open any completed analysis and click <strong>Watch</strong> to get notified when it changes.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mb-6">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50/50">
              <th className="text-left px-4 py-3 font-semibold text-muted-foreground">Repository</th>
              <th className="text-left px-4 py-3 font-semibold text-muted-foreground hidden sm:table-cell">Last checked</th>
              <th className="text-left px-4 py-3 font-semibold text-muted-foreground hidden md:table-cell">Last changed</th>
              <th className="px-4 py-3 text-right font-semibold text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody>
            {watches.map((w) => (
              <tr key={w.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/50 transition-colors">
                <td className="px-4 py-3">
                  <div className="font-mono text-sm font-semibold text-slate-800">{w.repo_name}</div>
                  <div className="text-xs text-muted-foreground truncate max-w-xs">{w.repo_url}</div>
                  {w.last_commit_hash && (
                    <div className="flex items-center gap-1 mt-0.5">
                      <GitCommit className="w-3 h-3 text-muted-foreground" />
                      <span className="text-xs text-muted-foreground font-mono">{w.last_commit_hash.slice(0, 7)}</span>
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-muted-foreground hidden sm:table-cell whitespace-nowrap">
                  {w.last_checked_at
                    ? new Date(w.last_checked_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
                    : <span className="text-slate-300">Not yet</span>}
                </td>
                <td className="px-4 py-3 text-muted-foreground hidden md:table-cell whitespace-nowrap">
                  {w.last_changed_at
                    ? new Date(w.last_changed_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
                    : <span className="text-slate-300">No changes yet</span>}
                </td>
                <td className="px-4 py-3 text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onUnwatch(w)}
                    disabled={unwatching === w.id}
                    className="hover:bg-red-50 hover:text-red-600 hover:border-red-200"
                  >
                    {unwatching === w.id ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      "Unwatch"
                    )}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function StatusBadge({ status, fromCache, isPublic }: { status: string; fromCache?: boolean; isPublic?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {status === "completed" ? (
        <Badge variant="secondary" className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
          <CheckCircle className="w-3 h-3 mr-1" />
          Completed
        </Badge>
      ) : status === "failed" ? (
        <Badge variant="secondary" className="bg-red-100 text-red-700 hover:bg-red-100">
          <XCircle className="w-3 h-3 mr-1" />
          Failed
        </Badge>
      ) : (
        <Badge variant="secondary" className="bg-blue-100 text-blue-700 hover:bg-blue-100">
          <Loader2 className="w-3 h-3 mr-1 animate-spin" />
          In progress
        </Badge>
      )}
      {fromCache && (
        <Badge variant="secondary" className="bg-amber-100 text-amber-700 hover:bg-amber-100">
          Cached
        </Badge>
      )}
      {isPublic && (
        <Badge variant="secondary" className="bg-purple-100 text-purple-700 hover:bg-purple-100">
          <Globe className="w-3 h-3 mr-1" />
          Public
        </Badge>
      )}
    </div>
  );
}
