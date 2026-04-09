import { useEffect, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useRequireAuth } from "../lib/auth";
import { getUserStats, type UserStats } from "../lib/api";
import AdminLineChart from "../components/AdminLineChart";
import PlanUsageBar from "../components/PlanUsageBar";
import OwlLogo from "../components/OwlLogo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  BarChart3,
  CheckCircle,
  Star,
  Calendar,
  ArrowRight,
  Loader2,
  TrendingUp,
} from "lucide-react";

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

export default function AnalyticsPage() {
  const { user, loading } = useRequireAuth();
  const router = useRouter();
  const [stats, setStats] = useState<UserStats | null>(null);
  const [fetching, setFetching] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (loading || !user) return;
    getUserStats()
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setFetching(false));
  }, [user, loading]);

  if (loading || !user) return null;

  const maxRepoCount = stats ? Math.max(...stats.top_repos.map((r) => r.count), 1) : 1;

  return (
    <>
      <Head><title>Analytics — Hootly</title></Head>
      <div className="min-h-screen bg-slate-50">
        <header className="bg-white border-b border-slate-200">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/dashboard" className="flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors">
                <OwlLogo size={72} />
              </Link>
              <span className="text-xl text-slate-300">/</span>
              <span className="text-lg font-semibold text-slate-700">Analytics</span>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild>
                <Link href="/analyses">History</Link>
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
          <div className="flex items-start justify-between mb-6 gap-4 flex-col sm:flex-row">
            <h1 className="text-2xl font-bold text-slate-900">Usage Analytics</h1>
            {user.plan === "free" && (
              <div className="w-full sm:w-80">
                <PlanUsageBar />
              </div>
            )}
          </div>

          {error && (
            <Card className="border-red-200 bg-red-50 mb-6">
              <CardContent className="py-3 px-4 text-red-700 text-sm">{error}</CardContent>
            </Card>
          )}

          {fetching ? (
            <SkeletonLoader />
          ) : !stats || stats.total_analyses === 0 ? (
            <EmptyState />
          ) : (
            <>
              {/* Stat cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
                <StatCard label="Total analyses" value={stats.total_analyses} icon={<BarChart3 className="w-4 h-4 text-slate-400" />} />
                <StatCard label="Completed" value={stats.completed_analyses} icon={<CheckCircle className="w-4 h-4 text-emerald-500" />} accent="emerald" />
                <StatCard label="Starred" value={stats.starred_count} icon={<Star className="w-4 h-4 text-amber-400 fill-amber-400" />} accent="amber" />
                <StatCard
                  label="This month"
                  value={stats.analyses_this_month}
                  suffix={stats.monthly_limit !== null ? ` / ${stats.monthly_limit}` : undefined}
                  icon={<Calendar className="w-4 h-4 text-blue-500" />}
                  accent={
                    stats.monthly_limit !== null && stats.analyses_this_month >= stats.monthly_limit
                      ? "red"
                      : "blue"
                  }
                />
              </div>

              {/* Activity chart */}
              <Card className="mb-8">
                <CardHeader className="pb-2">
                  <CardTitle className="text-base flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-muted-foreground" />
                    Activity — last 30 days
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <AdminLineChart data={stats.daily_analyses} />
                </CardContent>
              </Card>

              {/* Top repos */}
              {stats.top_repos.length > 0 && (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Most Analyzed Repos</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {stats.top_repos.map((repo) => (
                        <div key={repo.repo_name} className="flex items-center gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between mb-1">
                              <span className="font-mono text-sm font-semibold text-slate-800 truncate">
                                {repo.repo_name}
                              </span>
                              <span className="text-xs text-muted-foreground shrink-0 ml-2">
                                {repo.count} {repo.count === 1 ? "analysis" : "analyses"} · Last {relativeTime(repo.last_analyzed_at)}
                              </span>
                            </div>
                            <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-blue-500 rounded-full transition-all"
                                style={{ width: `${Math.round((repo.count / maxRepoCount) * 100)}%` }}
                              />
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => router.push(`/analyses?repo=${encodeURIComponent(repo.repo_name)}`)}
                            className="shrink-0"
                          >
                            View latest
                            <ArrowRight className="w-3 h-3 ml-1" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </main>
      </div>
    </>
  );
}

function StatCard({
  label,
  value,
  suffix,
  accent,
  icon,
}: {
  label: string;
  value: number;
  suffix?: string;
  accent?: "emerald" | "amber" | "blue" | "red";
  icon?: React.ReactNode;
}) {
  const colors: Record<string, string> = {
    emerald: "text-emerald-600",
    amber: "text-amber-500",
    blue: "text-blue-600",
    red: "text-red-600",
  };
  const numColor = accent ? colors[accent] : "text-slate-900";

  return (
    <Card>
      <CardContent className="pt-5 pb-5">
        <div className="flex items-center gap-2 mb-2">
          {icon}
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
        </div>
        <p className={`text-3xl font-bold ${numColor}`}>
          {value}
          {suffix && <span className="text-lg font-semibold text-slate-400">{suffix}</span>}
        </p>
      </CardContent>
    </Card>
  );
}

function SkeletonLoader() {
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardContent className="pt-5 pb-5">
              <div className="h-3 w-24 bg-slate-100 animate-pulse rounded mb-3" />
              <div className="h-8 w-16 bg-slate-100 animate-pulse rounded" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardContent className="pt-6">
          <div className="h-4 w-40 bg-slate-100 animate-pulse rounded mb-4" />
          <div className="h-48 bg-slate-50 animate-pulse rounded-xl" />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-6">
          <div className="h-4 w-40 bg-slate-100 animate-pulse rounded mb-4" />
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="flex-1">
                  <div className="h-3 w-48 bg-slate-100 animate-pulse rounded mb-2" />
                  <div className="h-1.5 bg-slate-100 animate-pulse rounded-full" />
                </div>
                <div className="h-4 w-20 bg-slate-100 animate-pulse rounded" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function EmptyState() {
  return (
    <Card>
      <CardContent className="py-12 text-center">
        <BarChart3 className="w-10 h-10 mx-auto text-muted-foreground mb-4" />
        <p className="text-slate-600 font-medium mb-1">No analyses yet</p>
        <p className="text-muted-foreground text-sm mb-4">Run your first analysis to see your usage stats here.</p>
        <Button asChild>
          <Link href="/">
            Analyze a repo
            <ArrowRight className="w-3 h-3 ml-1" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
