import { useEffect, useState } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useRequireAuth } from "../lib/auth";
import {
  getAlerts,
  getRecentAnalyses,
  markAlertRead,
  dismissAlert,
  type DriftAlert,
  type Analysis,
} from "../lib/api";
import OwlLogo from "../components/OwlLogo";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Bell,
  AlertTriangle,
  Info,
  XCircle,
  Check,
  X,
  Loader2,
  ArrowRight,
  Inbox,
} from "lucide-react";

type ReadFilter = "all" | "unread" | "dismissed";
type SeverityFilter = "all" | "critical" | "warning" | "info";

const PAGE_SIZE = 20;

export default function AlertsPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const router = useRouter();

  const [alerts, setAlerts] = useState<DriftAlert[]>([]);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [fetching, setFetching] = useState(true);
  const [readFilter, setReadFilter] = useState<ReadFilter>("all");
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    if (authLoading || !user) return;
    loadAlerts(true);
    getRecentAnalyses().then(setAnalyses).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, authLoading]);

  async function loadAlerts(reset: boolean) {
    const newOffset = reset ? 0 : offset;
    if (reset) setFetching(true);
    else setLoadingMore(true);

    try {
      const readParam = readFilter === "unread" ? false : undefined;
      const dismissedParam = readFilter === "dismissed" ? true : false;
      // For "all" filter, pass dismissed=undefined to get both; but API returns non-dismissed by default
      const data = await getAlerts(
        readParam,
        readFilter === "all" ? undefined : dismissedParam,
        PAGE_SIZE,
        newOffset,
      );
      if (reset) {
        setAlerts(data);
        setOffset(PAGE_SIZE);
      } else {
        setAlerts((prev) => [...prev, ...data]);
        setOffset(newOffset + PAGE_SIZE);
      }
      setHasMore(data.length === PAGE_SIZE);
    } catch {
      // silently fail
    } finally {
      setFetching(false);
      setLoadingMore(false);
    }
  }

  // Reload when filters change
  useEffect(() => {
    if (!user) return;
    loadAlerts(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readFilter]);

  async function handleMarkRead(id: string) {
    await markAlertRead(id).catch(() => {});
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, read: true } : a)),
    );
  }

  async function handleDismiss(id: string) {
    await dismissAlert(id).catch(() => {});
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, dismissed: true, read: true } : a)),
    );
  }

  function navigateToRepo(repoUrl: string) {
    const match = analyses.find(
      (a) => a.repo_url === repoUrl && a.status === "completed",
    );
    if (match) router.push(`/analysis/${match.id}`);
  }

  // Client-side severity filtering
  const filtered = alerts.filter((a) => {
    if (severityFilter !== "all" && a.severity !== severityFilter) return false;
    return true;
  });

  if (authLoading || !user) return null;

  return (
    <>
      <Head>
        <title>Alerts — Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50">
        {/* Header */}
        <header className="bg-white border-b border-slate-200">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link
                href="/dashboard"
                className="flex items-center gap-2 text-slate-700 hover:text-slate-900 transition-colors"
              >
                <OwlLogo size={72} />
              </Link>
              <span className="text-xl text-slate-300">/</span>
              <div className="flex items-center gap-2">
                <Bell className="w-4 h-4 text-slate-500" />
                <span className="text-lg font-semibold text-slate-700">
                  Alerts
                </span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild>
                <Link href="/analyses">History</Link>
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

        <main className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
          {/* Filter bar */}
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-6">
            <h1 className="text-xl font-bold text-slate-900 flex-1">
              Drift Alerts
            </h1>

            {/* Read/dismissed filter */}
            <div className="flex gap-1 bg-slate-100 p-1 rounded-lg">
              {(["all", "unread", "dismissed"] as ReadFilter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setReadFilter(f)}
                  className={`px-3 py-1 rounded-md text-xs font-medium transition-colors capitalize ${
                    readFilter === f
                      ? "bg-white text-slate-900 shadow-sm"
                      : "text-slate-500 hover:text-slate-700"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>

            {/* Severity filter */}
            <div className="flex gap-1 bg-slate-100 p-1 rounded-lg">
              {(["all", "critical", "warning", "info"] as SeverityFilter[]).map(
                (f) => (
                  <button
                    key={f}
                    onClick={() => setSeverityFilter(f)}
                    className={`px-3 py-1 rounded-md text-xs font-medium transition-colors capitalize flex items-center gap-1 ${
                      severityFilter === f
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-500 hover:text-slate-700"
                    }`}
                  >
                    {f === "critical" && (
                      <XCircle className="w-3 h-3 text-red-500" />
                    )}
                    {f === "warning" && (
                      <AlertTriangle className="w-3 h-3 text-yellow-500" />
                    )}
                    {f === "info" && (
                      <Info className="w-3 h-3 text-blue-500" />
                    )}
                    {f}
                  </button>
                ),
              )}
            </div>
          </div>

          {/* Alert list */}
          <Card>
            {fetching ? (
              <CardContent className="py-8 text-center">
                <Loader2 className="w-5 h-5 animate-spin mx-auto text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  Loading alerts...
                </p>
              </CardContent>
            ) : filtered.length === 0 ? (
              <CardContent className="py-12 text-center">
                <Inbox className="w-8 h-8 mx-auto text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">
                  {readFilter !== "all" || severityFilter !== "all"
                    ? "No alerts match your filters."
                    : "No alerts yet. Watch a repo to get notified when it changes."}
                </p>
                {readFilter === "all" && severityFilter === "all" && (
                  <Button variant="link" size="sm" asChild className="mt-2">
                    <Link href="/dashboard">
                      Go to Dashboard
                      <ArrowRight className="w-3 h-3 ml-1" />
                    </Link>
                  </Button>
                )}
              </CardContent>
            ) : (
              <div>
                {filtered.map((alert) => (
                  <div
                    key={alert.id}
                    className={`flex items-start gap-3 px-4 py-4 border-b border-slate-100 last:border-0 transition-colors ${
                      !alert.read
                        ? "bg-blue-50/50 hover:bg-blue-50"
                        : alert.dismissed
                          ? "opacity-60 hover:opacity-80"
                          : "hover:bg-slate-50"
                    }`}
                  >
                    {/* Severity icon */}
                    {alert.severity === "critical" ? (
                      <XCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
                    ) : alert.severity === "warning" ? (
                      <AlertTriangle className="w-5 h-5 text-yellow-500 mt-0.5 shrink-0" />
                    ) : (
                      <Info className="w-5 h-5 text-blue-500 mt-0.5 shrink-0" />
                    )}

                    {/* Content */}
                    <button
                      onClick={() => navigateToRepo(alert.repo_url)}
                      className="flex-1 min-w-0 text-left"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        {alert.message}
                      </p>
                      <div className="flex items-center gap-2 mt-1 flex-wrap">
                        <span className="text-xs text-muted-foreground font-mono">
                          {alert.repo_url.replace("https://github.com/", "")}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          &middot;
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {new Date(alert.created_at).toLocaleDateString(
                            undefined,
                            { month: "short", day: "numeric", year: "numeric" },
                          )}
                        </span>
                        <Badge
                          variant="secondary"
                          className={`text-[10px] px-1.5 py-0 h-4 ${
                            alert.severity === "critical"
                              ? "bg-red-100 text-red-700"
                              : alert.severity === "warning"
                                ? "bg-yellow-100 text-yellow-700"
                                : "bg-blue-100 text-blue-700"
                          }`}
                        >
                          {alert.severity}
                        </Badge>
                      </div>
                      {/* Details if present */}
                      {alert.details &&
                        Object.keys(alert.details).length > 0 && (
                          <p className="text-xs text-muted-foreground mt-1.5">
                            {Object.entries(alert.details)
                              .slice(0, 2)
                              .map(([k, v]) => `${k}: ${v}`)
                              .join(" · ")}
                          </p>
                        )}
                    </button>

                    {/* Action buttons */}
                    <div className="flex items-center gap-1 shrink-0">
                      {!alert.read && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          title="Mark as read"
                          onClick={() => handleMarkRead(alert.id)}
                        >
                          <Check className="w-3.5 h-3.5" />
                        </Button>
                      )}
                      {!alert.dismissed && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 hover:text-red-600"
                          title="Dismiss"
                          onClick={() => handleDismiss(alert.id)}
                        >
                          <X className="w-3.5 h-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                ))}

                {/* Load more */}
                {hasMore && (
                  <div className="p-4 text-center border-t border-slate-100">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => loadAlerts(false)}
                      disabled={loadingMore}
                    >
                      {loadingMore ? (
                        <>
                          <Loader2 className="w-3 h-3 animate-spin" />{" "}
                          Loading...
                        </>
                      ) : (
                        "Load more"
                      )}
                    </Button>
                  </div>
                )}
              </div>
            )}
          </Card>
        </main>
      </div>
    </>
  );
}
