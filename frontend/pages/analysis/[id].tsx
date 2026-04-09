import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  getAnalysis, startAnalysis, toggleStar, toggleVisibility, getWatches, watchRepo, unwatchRepo,
  getAssessment, getAnalysisHistory, getBenchmark, getAnnotations, createAnnotation, deleteAnnotation,
  type Analysis, type AssessmentResult, type RepoSnapshotSummary, type BenchmarkReport, type AnnotationData,
} from "../../lib/api";
import { useRequireAuth } from "../../lib/auth";
import ArchitectureCard from "../../components/ArchitectureCard";
import KeyFileCard from "../../components/KeyFileCard";
import ReadingOrder from "../../components/ReadingOrder";
import DependencyList from "../../components/DependencyList";
import FileTree from "../../components/FileTree";
import DependencyGraph from "../../components/DependencyGraph";
import OwlLogo from "../../components/OwlLogo";
import ChatPanel from "../../components/ChatPanel";
import HealthScoreCard from "../../components/HealthScoreCard";
import AssessmentCTA from "../../components/AssessmentCTA";
import BadgePrompt from "../../components/BadgePrompt";
import AlertBell from "../../components/AlertBell";
import ImpactView from "../../components/ImpactView";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Layers,
  Heart,
  FileText,
  BookOpen,
  Package,
  Map,
  Network,
  FolderTree,
  BarChart3,
  Star,
  Eye,
  EyeOff,
  Lock,
  Unlock,
  Share2,
  Download,
  RefreshCw,
  Printer,
  Github,
  MessageSquare,
  Search,
  ArrowLeft,
  Loader2,
  CheckCircle,
  AlertTriangle,
  Clock,
  History,
  Users,
  Settings,
  LogOut,
  Copy,
  ExternalLink,
  TrendingUp,
  StickyNote,
  Bell,
  Target,
} from "lucide-react";

const POLL_INTERVAL = 2500; // ms

type Tab = "overview" | "files" | "reading" | "deps" | "guide" | "graph" | "tree" | "health" | "benchmark" | "history" | "assessment";

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "overview", label: "Overview", icon: <Layers className="w-3.5 h-3.5" /> },
  { id: "health", label: "Health", icon: <Heart className="w-3.5 h-3.5" /> },
  { id: "benchmark", label: "Benchmark", icon: <TrendingUp className="w-3.5 h-3.5" /> },
  { id: "files", label: "Key Files", icon: <FileText className="w-3.5 h-3.5" /> },
  { id: "reading", label: "Reading Order", icon: <BookOpen className="w-3.5 h-3.5" /> },
  { id: "deps", label: "Dependencies", icon: <Package className="w-3.5 h-3.5" /> },
  { id: "guide", label: "Onboarding Guide", icon: <Map className="w-3.5 h-3.5" /> },
  { id: "graph", label: "Dep Graph", icon: <Network className="w-3.5 h-3.5" /> },
  { id: "tree", label: "File Tree", icon: <FolderTree className="w-3.5 h-3.5" /> },
  { id: "history", label: "History", icon: <History className="w-3.5 h-3.5" /> },
  { id: "assessment", label: "Assessment", icon: <BarChart3 className="w-3.5 h-3.5" /> },
];

export default function AnalysisPage() {
  const router = useRouter();
  const { id } = router.query as { id: string };
  const { user, logout, loading: authLoading } = useRequireAuth();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState("");
  const [reanalyzing, setReanalyzing] = useState(false);
  const [fileSearch, setFileSearch] = useState("");
  const [copied, setCopied] = useState<"link" | "md" | null>(null);
  const [starred, setStarred] = useState(false);
  const [starLoading, setStarLoading] = useState(false);
  const [isPublic, setIsPublic] = useState(false);
  const [visLoading, setVisLoading] = useState(false);
  const [watched, setWatched] = useState(false);
  const [watchId, setWatchId] = useState<string | null>(null);
  const [watchLoading, setWatchLoading] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [assessment, setAssessment] = useState<AssessmentResult | null>(null);
  const [snapshots, setSnapshots] = useState<RepoSnapshotSummary[]>([]);
  const [benchmark, setBenchmark] = useState<BenchmarkReport | null>(null);
  const [annotations, setAnnotations] = useState<AnnotationData[]>([]);
  const [newAnnotationFile, setNewAnnotationFile] = useState<string | null>(null);
  const [newAnnotationText, setNewAnnotationText] = useState("");

  const poll = useCallback(async () => {
    if (!id) return;
    try {
      const data = await getAnalysis(id);
      setAnalysis(data);
      setStarred(data.is_starred ?? false);
      setIsPublic(data.is_public ?? false);
      if (data.status === "completed" || data.status === "failed") {
        return false; // stop polling
      }
    } catch (e: any) {
      if (e.message === "UNAUTHORIZED") {
        setAnalysis(null);
        router.replace(`/login?next=/analysis/${id}`);
        return false;
      }
      setError(e.message);
      return false;
    }
    return true; // continue polling
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    async function run() {
      if (!active) return;
      const cont = await poll();
      if (cont && active) {
        timer = setTimeout(run, POLL_INTERVAL);
      }
    }
    run();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, poll]);

  // Load assessment status
  useEffect(() => {
    if (tab === "assessment" && analysis?.status === "completed" && !assessment) {
      getAssessment(analysis.id).then(setAssessment).catch(() => {});
    }
  }, [tab, analysis?.id, analysis?.status, assessment]);

  // Load watch status once analysis URL is known
  useEffect(() => {
    if (!analysis?.repo_url) return;
    getWatches().then((watches) => {
      const match = watches.find((w) => w.repo_url === analysis.repo_url);
      if (match) {
        setWatched(true);
        setWatchId(match.id);
      } else {
        setWatched(false);
        setWatchId(null);
      }
    }).catch(() => {});
  }, [analysis?.repo_url]);

  // Load history snapshots
  useEffect(() => {
    if (tab === "history" && analysis?.status === "completed" && snapshots.length === 0) {
      getAnalysisHistory(analysis.id).then(setSnapshots).catch(() => {});
    }
  }, [tab, analysis?.id, analysis?.status]);

  // Load benchmark
  useEffect(() => {
    if (tab === "benchmark" && analysis?.status === "completed" && !benchmark) {
      getBenchmark(analysis.id).then(setBenchmark).catch(() => {});
    }
  }, [tab, analysis?.id, analysis?.status]);

  // Load annotations
  useEffect(() => {
    if (tab === "files" && analysis?.status === "completed" && annotations.length === 0) {
      getAnnotations(analysis.id).then(setAnnotations).catch(() => {});
    }
  }, [tab, analysis?.id, analysis?.status]);

  async function handleWatch() {
    if (!analysis) return;
    setWatchLoading(true);
    try {
      if (watched && watchId) {
        await unwatchRepo(watchId);
        setWatched(false);
        setWatchId(null);
      } else {
        const w = await watchRepo(analysis.repo_url);
        setWatched(true);
        setWatchId(w.id);
      }
    } catch {}
    setWatchLoading(false);
  }

  function copyToClipboard(text: string, type: "link" | "md") {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(type);
      setTimeout(() => setCopied(null), 2000);
    });
  }

  async function handleStar() {
    if (!analysis) return;
    setStarLoading(true);
    try {
      const { is_starred } = await toggleStar(analysis.id);
      setStarred(is_starred);
    } catch {}
    setStarLoading(false);
  }

  async function handleVisibility() {
    if (!analysis) return;
    setVisLoading(true);
    try {
      const { is_public: pub } = await toggleVisibility(analysis.id);
      setIsPublic(pub);
    } catch {}
    setVisLoading(false);
  }

  function downloadMarkdown() {
    if (!analysis?.result) return;
    const r = analysis.result;
    const blocks: string[] = [];

    blocks.push(`# ${r.repo_name} — Hootly Analysis`);

    // Architecture
    const archMeta = [
      `**Type:** ${r.architecture.architecture_type}`,
      `**Stack:** ${r.architecture.tech_stack.join(", ")}`,
      `**Languages:** ${r.architecture.languages.join(", ")}`,
      `**Runtime:** ${r.architecture.runtime}`,
    ].join("  \n"); // trailing two-space = line break in markdown
    blocks.push(`## Architecture\n\n${archMeta}\n\n${r.architecture.architecture_summary}`);

    // Key files
    const keyFileBlocks = r.key_files.map(
      (f, i) => `### ${i + 1}. \`${f.path}\` (score: ${f.score}/10)\n\n${f.explanation}`
    );
    blocks.push(`## Key Files\n\n${keyFileBlocks.join("\n\n")}`);

    // Reading order — numbered list, items separated by single newline
    const readingLines = r.reading_order.map(
      (s) => `${s.step}. \`${s.path}\` — ${s.reason}`
    ).join("\n");
    blocks.push(`## Suggested Reading Order\n\n${readingLines}`);

    // Dependencies
    const depLines: string[] = [];
    if (r.dependencies.runtime.length) depLines.push(`**Runtime:** ${r.dependencies.runtime.join(", ")}`);
    if (r.dependencies.dev.length) depLines.push(`**Dev:** ${r.dependencies.dev.join(", ")}`);
    if (depLines.length) blocks.push(`## Dependencies\n\n${depLines.join("  \n")}`);

    // Quick start & guide
    if (r.quick_start) blocks.push(`## Quick Start\n\n${r.quick_start}`);
    blocks.push(`## Onboarding Guide\n\n${r.onboarding_guide}`);

    const blob = new Blob([blocks.join("\n\n---\n\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${r.repo_name.replace(/\//g, "-")}-hootly.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const handleReanalyze = useCallback(async () => {
    if (!analysis) return;
    setReanalyzing(true);
    try {
      const fresh = await startAnalysis(analysis.repo_url, true);
      router.push(`/analysis/${fresh.id}`);
    } catch (e: any) {
      setError(e.message);
      setReanalyzing(false);
    }
  }, [analysis, router]);

  if (authLoading) return <LoadingScreen stage="Loading..." />;

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-600 mb-4">{error}</p>
          <Link href="/" className="text-blue-600 hover:underline">← Back home</Link>
        </div>
      </div>
    );
  }

  if (!analysis) {
    return <LoadingScreen stage="Loading..." />;
  }

  if (analysis.status === "failed") {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-lg w-full bg-white border border-red-200 rounded-2xl p-8 text-center shadow-sm">
          <AlertTriangle className="w-10 h-10 mx-auto text-red-400 mb-4" />
          <h1 className="text-xl font-semibold text-slate-900 mb-2">Analysis Failed</h1>
          <p className="text-red-600 text-sm mb-2">{analysis.error_message || "Unknown error"}</p>
          <p className="text-slate-500 text-sm mb-6">
            Make sure the repository is public and the URL is correct.
          </p>
          <Button asChild>
            <Link href="/">Try another repo</Link>
          </Button>
        </div>
      </div>
    );
  }

  if (analysis.status !== "completed") {
    return <LoadingScreen stage={analysis.stage} repoName={analysis.repo_name} />;
  }

  const r = analysis.result!;

  return (
    <>
      <Head>
        <title>{r.repo_name} — Hootly</title>
      </Head>

      {/* ── Print-only layout ─────────────────────────────────────────────── */}
      <div className="hidden print:block print-prose px-2 py-0">
        <div className="flex items-center justify-between border-b border-slate-300 pb-3 mb-4">
          <h1 style={{ margin: 0 }}>{r.repo_name}</h1>
          <span style={{ fontSize: "0.8rem", color: "#64748b" }}>
            Hootly Analysis · {new Date(analysis.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
          </span>
        </div>

        <h2>Architecture</h2>
        <p>
          <strong>Type:</strong> {r.architecture.architecture_type}<br />
          <strong>Stack:</strong> {r.architecture.tech_stack.join(", ")}<br />
          <strong>Languages:</strong> {r.architecture.languages.join(", ")}<br />
          <strong>Runtime:</strong> {r.architecture.runtime}
        </p>
        <p>{r.architecture.architecture_summary}</p>

        {r.quick_start && <>
          <h2>Quick Start</h2>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.quick_start}</ReactMarkdown>
        </>}

        <h2>Key Files</h2>
        {r.key_files.map((f, i) => (
          <div key={f.path} style={{ marginBottom: "0.75rem" }}>
            <h3 style={{ marginBottom: "0.25rem" }}>
              {i + 1}. <code>{f.path}</code>{" "}
              <span style={{ fontWeight: 400, fontSize: "0.8rem", color: "#64748b" }}>(score: {f.score}/10)</span>
            </h3>
            <p style={{ marginBottom: 0 }}>{f.explanation}</p>
          </div>
        ))}

        <h2>Suggested Reading Order</h2>
        <ol>
          {r.reading_order.map((s) => (
            <li key={s.step}><code>{s.path}</code> — {s.reason}</li>
          ))}
        </ol>

        {(r.dependencies.runtime.length > 0 || r.dependencies.dev.length > 0) && <>
          <h2>Dependencies</h2>
          {r.dependencies.runtime.length > 0 && <p><strong>Runtime:</strong> {r.dependencies.runtime.join(", ")}</p>}
          {r.dependencies.dev.length > 0 && <p><strong>Dev:</strong> {r.dependencies.dev.join(", ")}</p>}
        </>}

        <h2>Onboarding Guide</h2>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.onboarding_guide}</ReactMarkdown>
      </div>

      {/* ── Screen layout (hidden when printing) ─────────────────────────── */}
      <div className="print:hidden min-h-screen bg-slate-50">
        {/* Header */}
        <header className="sticky top-0 z-20 bg-white border-b border-slate-200 shadow-sm">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">

            {/* Row 1 — logo + repo name + user nav */}
            <div className="flex items-center gap-3 h-14 border-b border-slate-100">
              <Button variant="ghost" size="icon" asChild className="shrink-0 h-8 w-8">
                <Link href="/dashboard">
                  <ArrowLeft className="h-4 w-4" />
                </Link>
              </Button>
              <OwlLogo size={40} />
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <span className="font-semibold text-slate-900 truncate">{r.repo_name}</span>
                {analysis.from_cache ? (
                  <Badge variant="secondary" className="hidden sm:inline-flex bg-amber-100 text-amber-700 hover:bg-amber-100">
                    <Clock className="w-3 h-3 mr-1" />
                    Cached
                  </Badge>
                ) : (
                  <Badge variant="secondary" className="hidden sm:inline-flex bg-emerald-100 text-emerald-700 hover:bg-emerald-100">
                    <CheckCircle className="w-3 h-3 mr-1" />
                    Complete
                  </Badge>
                )}
                {analysis.created_at && (
                  <span className="hidden md:inline text-xs text-muted-foreground shrink-0">
                    {new Date(analysis.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                )}
              </div>
              {user && (
                <div className="flex items-center gap-1 shrink-0">
                  <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                    <Link href="/analyses">
                      <History className="w-3 h-3 mr-1" />
                      History
                    </Link>
                  </Button>
                  <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                    <Link href="/team">
                      <Users className="w-3 h-3 mr-1" />
                      Teams
                    </Link>
                  </Button>
                  <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                    <Link href="/settings">
                      <Settings className="w-3 h-3 mr-1" />
                      Settings
                    </Link>
                  </Button>
                  <AlertBell />
                  <Button variant="ghost" size="sm" onClick={logout}>
                    <LogOut className="w-3 h-3 mr-1" />
                    Log out
                  </Button>
                </div>
              )}
            </div>

            {/* Row 2 — action buttons */}
            <div className="flex items-center gap-1.5 py-2 overflow-x-auto">
              <Button
                variant={starred ? "secondary" : "outline"}
                size="sm"
                onClick={handleStar}
                disabled={starLoading}
                className={`shrink-0 ${starred ? "bg-amber-50 text-amber-600 hover:bg-amber-100 border-amber-200" : ""}`}
                title={starred ? "Remove from favorites" : "Add to favorites"}
              >
                <Star className={`w-3.5 h-3.5 ${starred ? "fill-amber-400" : ""}`} />
                {starred ? "Starred" : "Star"}
              </Button>
              <Button
                variant={watched ? "secondary" : "outline"}
                size="sm"
                onClick={handleWatch}
                disabled={watchLoading}
                className={`shrink-0 ${watched ? "bg-blue-50 text-blue-700 hover:bg-blue-100 border-blue-200" : ""}`}
                title={watched ? "Stop watching" : "Watch — get notified when this repo changes"}
              >
                <Eye className="w-3.5 h-3.5" />
                {watched ? "Watching" : "Watch"}
              </Button>
              <Button
                variant={isPublic ? "secondary" : "outline"}
                size="sm"
                onClick={handleVisibility}
                disabled={visLoading}
                className={`shrink-0 ${isPublic ? "bg-purple-50 text-purple-700 hover:bg-purple-100 border-purple-200" : ""}`}
                title={isPublic ? "Make private" : "Make public"}
              >
                {isPublic ? <Unlock className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5" />}
                {isPublic ? "Public" : "Private"}
              </Button>
              <div className="w-px h-4 bg-slate-200 shrink-0 mx-0.5" />
              <Button
                variant="outline"
                size="sm"
                onClick={() => copyToClipboard(window.location.href, "link")}
                className="shrink-0"
                title="Copy shareable link"
              >
                {copied === "link" ? <CheckCircle className="w-3.5 h-3.5" /> : <Share2 className="w-3.5 h-3.5" />}
                {copied === "link" ? "Copied!" : "Share"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={downloadMarkdown}
                className="shrink-0"
                title="Download as Markdown"
              >
                <Download className="w-3.5 h-3.5" />
                .md
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleReanalyze}
                disabled={reanalyzing}
                className="shrink-0"
                title="Force a fresh analysis ignoring the cache"
              >
                {reanalyzing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                {reanalyzing ? "Starting…" : "Re-analyze"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => window.print()}
                className="shrink-0"
                title="Print / Save as PDF"
              >
                <Printer className="w-3.5 h-3.5" />
                PDF
              </Button>
              <Button
                variant="outline"
                size="sm"
                asChild
                className="shrink-0"
              >
                <a
                  href={analysis.repo_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Github className="w-3.5 h-3.5" />
                  GitHub
                  <ExternalLink className="w-3 h-3" />
                </a>
              </Button>
            </div>

            {/* Floating Ask button */}
            <Button
              onClick={() => setChatOpen(true)}
              className="fixed bottom-6 right-6 z-30 rounded-full shadow-lg hover:shadow-xl px-5 py-3 h-auto"
              title="Ask about this codebase"
            >
              <MessageSquare className="w-4 h-4" />
              <span className="text-sm">Ask</span>
            </Button>

            {/* Tabs */}
            <div className="flex gap-0.5 -mb-px overflow-x-auto">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`flex items-center gap-1.5 px-3.5 py-2.5 text-sm font-medium border-b-2 whitespace-nowrap transition-colors ${
                    tab === t.id
                      ? "border-blue-600 text-blue-700"
                      : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
                  }`}
                >
                  {t.icon}
                  <span>{t.label}</span>
                </button>
              ))}
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
          {analysis.changelog && <ChangelogPanel changelog={analysis.changelog} />}

          {/* Badge adoption prompt */}
          {isPublic && (() => {
            const match = analysis.repo_url.match(/github\.com\/([^/]+)\/([^/]+)/);
            if (!match) return null;
            return (
              <BadgePrompt
                analysisId={analysis.id}
                owner={match[1]}
                repo={match[2].replace(/\.git$/, "")}
                healthGrade={analysis.health_score?.grade}
              />
            );
          })()}

          {tab === "overview" && (
            <ArchitectureCard
              arch={r.architecture}
              quickStart={r.quick_start}
              keyConcepts={r.key_concepts}
              patterns={r.patterns}
              testFileCount={r.test_files?.length}
            />
          )}

          {tab === "files" && (
            <div>
              <div className="flex items-center gap-3 mb-4">
                <p className="text-sm text-slate-500 dark:text-slate-400 flex-1">
                  Top {r.key_files.length} files ranked by importance for understanding this codebase.
                </p>
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    type="text"
                    placeholder="Filter files…"
                    value={fileSearch}
                    onChange={(e) => setFileSearch(e.target.value)}
                    className="pl-8 w-44 h-9"
                  />
                </div>
              </div>
              <div className="space-y-3">
                {r.key_files
                  .filter((f) => !fileSearch || f.path.toLowerCase().includes(fileSearch.toLowerCase()))
                  .map((file, i) => (
                    <div key={file.path}>
                      <KeyFileCard file={file} index={i} />
                      <div className="ml-4 mt-1 flex items-center gap-2 flex-wrap">
                        <ImpactView analysisId={analysis.id} filePath={file.path} />
                        <Button
                          variant="outline"
                          size="sm"
                          className="gap-1.5 text-xs"
                          onClick={() => setNewAnnotationFile(newAnnotationFile === file.path ? null : file.path)}
                        >
                          <StickyNote className="h-3 w-3" />
                          Add note
                          {annotations.filter(a => a.file_path === file.path).length > 0 && (
                            <Badge variant="secondary" className="ml-1 text-[10px] px-1">
                              {annotations.filter(a => a.file_path === file.path).length}
                            </Badge>
                          )}
                        </Button>
                      </div>
                      {/* Existing annotations for this file */}
                      {annotations.filter(a => a.file_path === file.path).map(ann => (
                        <div key={ann.id} className="ml-4 mt-1 p-2 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded text-xs flex items-start gap-2">
                          <StickyNote className="h-3 w-3 text-amber-600 shrink-0 mt-0.5" />
                          <span className="flex-1">{ann.content}</span>
                          <button
                            className="text-red-400 hover:text-red-600 text-xs"
                            onClick={async () => {
                              await deleteAnnotation(ann.id);
                              setAnnotations(prev => prev.filter(a => a.id !== ann.id));
                            }}
                          >
                            &times;
                          </button>
                        </div>
                      ))}
                      {/* New annotation input */}
                      {newAnnotationFile === file.path && (
                        <div className="ml-4 mt-2 flex gap-2">
                          <Input
                            placeholder="Add a note about this file..."
                            value={newAnnotationText}
                            onChange={e => setNewAnnotationText(e.target.value)}
                            className="text-xs h-8"
                            onKeyDown={async (e) => {
                              if (e.key === "Enter" && newAnnotationText.trim()) {
                                const ann = await createAnnotation(analysis.id, {
                                  file_path: file.path,
                                  content: newAnnotationText.trim(),
                                });
                                setAnnotations(prev => [ann, ...prev]);
                                setNewAnnotationText("");
                                setNewAnnotationFile(null);
                              }
                            }}
                          />
                          <Button
                            size="sm"
                            className="h-8 text-xs"
                            disabled={!newAnnotationText.trim()}
                            onClick={async () => {
                              if (!newAnnotationText.trim()) return;
                              const ann = await createAnnotation(analysis.id, {
                                file_path: file.path,
                                content: newAnnotationText.trim(),
                              });
                              setAnnotations(prev => [ann, ...prev]);
                              setNewAnnotationText("");
                              setNewAnnotationFile(null);
                            }}
                          >
                            Save
                          </Button>
                        </div>
                      )}
                    </div>
                  ))}
                {fileSearch && r.key_files.filter((f) => f.path.toLowerCase().includes(fileSearch.toLowerCase())).length === 0 && (
                  <p className="text-sm text-slate-400 text-center py-8">No files match &ldquo;{fileSearch}&rdquo;</p>
                )}
              </div>
            </div>
          )}

          {tab === "reading" && (
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                Suggested order for reading through the codebase as a new engineer.
              </p>
              <ReadingOrder steps={r.reading_order} />
            </div>
          )}

          {tab === "deps" && (
            <DependencyList deps={r.dependencies} />
          )}

          {tab === "guide" && (
            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6 sm:p-8 shadow-sm">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-200">Onboarding Guide</h2>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => copyToClipboard(r.onboarding_guide, "md")}
                >
                  {copied === "md" ? <CheckCircle className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied === "md" ? "Copied!" : "Copy Markdown"}
                </Button>
              </div>
              <div className="guide-prose">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {r.onboarding_guide}
                </ReactMarkdown>
              </div>
            </div>
          )}

          {tab === "graph" && (
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                Directed import graph — arrows show which files import which.
                Click a node to see its connections. Drag to rearrange, scroll to zoom.
              </p>
              {r.dependency_graph ? (
                <DependencyGraph graph={r.dependency_graph} keyFiles={r.key_files} />
              ) : (
                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-10 text-center text-slate-500 dark:text-slate-400 shadow-sm">
                  <p className="text-sm">Dependency graph not available for this analysis.</p>
                  <p className="text-xs text-slate-400 mt-1">Re-analyze the repo to generate it.</p>
                </div>
              )}
            </div>
          )}

          {tab === "tree" && (
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                Full file tree of the repository ({r.file_tree.length} files).
              </p>
              <FileTree files={r.file_tree} />
            </div>
          )}

          {tab === "health" && (
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                Automated architecture health assessment based on code structure, tests, documentation, and dependencies.
              </p>
              {analysis.health_score ? (
                <HealthScoreCard healthScore={analysis.health_score} isPro={user?.plan === "pro" || user?.is_admin} />
              ) : (
                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-10 text-center">
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Health score not available. Re-analyze to generate it.
                  </p>
                </div>
              )}
            </div>
          )}

          {tab === "benchmark" && (
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                Compare this repo against similar projects to see how it stacks up.
              </p>
              {benchmark ? (
                benchmark.has_benchmark ? (
                  <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-6 shadow-sm space-y-6">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-lg font-semibold">
                          {benchmark.category_label} Benchmark
                        </h3>
                        <p className="text-sm text-slate-500">
                          Compared against {benchmark.sample_size} {benchmark.category_label} projects
                        </p>
                      </div>
                      <div className="text-center">
                        <div className="text-3xl font-bold">{benchmark.overall_percentile}th</div>
                        <div className="text-xs text-slate-500">percentile</div>
                      </div>
                    </div>

                    {benchmark.dimensions && (
                      <div className="space-y-3">
                        {Object.entries(benchmark.dimensions).map(([key, dim]) => (
                          <div key={key} className="space-y-1">
                            <div className="flex justify-between text-sm">
                              <span className="font-medium">{dim.label}</span>
                              <span className="text-slate-500">
                                {dim.score}/100 &middot; {dim.percentile}th percentile
                              </span>
                            </div>
                            <div className="h-2 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${
                                  dim.percentile >= 75 ? "bg-emerald-500" :
                                  dim.percentile >= 50 ? "bg-blue-500" :
                                  dim.percentile >= 25 ? "bg-amber-500" : "bg-red-500"
                                }`}
                                style={{ width: `${dim.percentile}%` }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {benchmark.callouts && benchmark.callouts.length > 0 && (
                      <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-slate-700">
                        {benchmark.callouts.map((c, i) => (
                          <p key={i} className="text-sm text-slate-600 dark:text-slate-400 flex items-start gap-2">
                            <TrendingUp className="w-4 h-4 shrink-0 mt-0.5" />
                            {c}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-10 text-center">
                    <TrendingUp className="w-8 h-8 mx-auto mb-3 text-slate-400" />
                    <p className="text-sm text-slate-500">{benchmark.message}</p>
                  </div>
                )
              ) : (
                <div className="flex items-center justify-center p-10">
                  <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
                </div>
              )}
            </div>
          )}

          {tab === "history" && (
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                Analysis history showing how this repo has evolved over time.
              </p>
              {snapshots.length > 0 ? (
                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900">
                        <th className="text-left p-3 font-medium">Date</th>
                        <th className="text-left p-3 font-medium">Commit</th>
                        <th className="text-right p-3 font-medium">Files</th>
                        <th className="text-right p-3 font-medium">Health</th>
                        <th className="text-left p-3 font-medium">Stack</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshots.map((s) => (
                        <tr key={s.id} className="border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                          <td className="p-3 text-slate-600 dark:text-slate-400">
                            {new Date(s.snapshot_date).toLocaleDateString()}
                          </td>
                          <td className="p-3 font-mono text-xs text-slate-500">
                            {s.commit_hash?.slice(0, 7) || "—"}
                          </td>
                          <td className="p-3 text-right">{s.file_count}</td>
                          <td className="p-3 text-right">
                            {s.health_score ? (
                              <Badge variant={s.health_score.grade === "A" || s.health_score.grade === "B" ? "default" : "secondary"}>
                                {s.health_score.grade} ({s.health_score.overall_score})
                              </Badge>
                            ) : "—"}
                          </td>
                          <td className="p-3">
                            <div className="flex gap-1 flex-wrap">
                              {(s.tech_stack || []).slice(0, 3).map((t) => (
                                <Badge key={t} variant="outline" className="text-xs">{t}</Badge>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl p-10 text-center">
                  <History className="w-8 h-8 mx-auto mb-3 text-slate-400" />
                  <p className="text-sm text-slate-500">No history yet. Re-analyze this repo to start tracking changes.</p>
                </div>
              )}
            </div>
          )}

          {tab === "assessment" && (
            <div>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                Professional assessment with health narrative, tech debt analysis, and prioritized recommendations.
              </p>
              <AssessmentCTA
                analysisId={analysis.id}
                assessment={assessment}
                onAssessmentCreated={setAssessment}
              />
            </div>
          )}
        </main>

        {/* Chat Panel */}
        <ChatPanel
          analysisId={analysis.id}
          repoName={r.repo_name}
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          analysisResult={r}
        />
      </div>{/* end print:hidden screen layout */}
    </>
  );
}

function LoadingScreen({ stage, repoName }: { stage: string; repoName?: string }) {
  const STAGES = [
    { key: "Queued",          label: "Queued" },
    { key: "Cloning",         label: "Cloning repository" },
    { key: "Walking",         label: "Reading file tree" },
    { key: "Pass 1",          label: "Analyzing architecture" },
    { key: "Pass 2",          label: "Ranking key files" },
    { key: "Pass 3",          label: "Explaining files" },
    { key: "Pass 4",          label: "Writing onboarding guide" },
    { key: "changelog",       label: "Generating changelog" },
  ];

  const currentIdx = STAGES.findIndex((s) => stage.toLowerCase().includes(s.key.toLowerCase()));

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4">
      <div className="max-w-md w-full">
        <div className="text-center mb-8">
          <div className="mb-3 flex justify-center"><OwlLogo size={90} /></div>
          <h1 className="text-2xl font-bold text-slate-900 mb-1">Analyzing repository</h1>
          {repoName && <p className="text-slate-500 font-mono text-sm">{repoName}</p>}
        </div>

        {/* Progress stages */}
        <div className="space-y-2 mb-8">
          {STAGES.map((s, i) => {
            const done = currentIdx > i;
            const active = currentIdx === i || (currentIdx === -1 && i === 0);
            return (
              <div key={s.key} className={`flex items-center gap-3 p-3 rounded-xl transition-all ${
                active ? "bg-blue-50 border border-blue-200" :
                done ? "opacity-50" : "opacity-30"
              }`}>
                {done ? (
                  <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center shrink-0">
                    <svg className="w-3 h-3 text-white" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  </div>
                ) : active ? (
                  <div className="w-5 h-5 rounded-full border-2 border-blue-600 border-t-transparent animate-spin shrink-0" />
                ) : (
                  <div className="w-5 h-5 rounded-full border-2 border-slate-200 shrink-0" />
                )}
                <span className={`text-sm font-medium ${active ? "text-blue-700" : done ? "text-emerald-700" : "text-slate-500"}`}>
                  {s.label}
                </span>
              </div>
            );
          })}
        </div>

        <p className="text-center text-sm text-slate-400">
          This usually takes 30–90 seconds depending on repo size.
        </p>
      </div>
    </div>
  );
}

function ChangelogPanel({ changelog }: { changelog: import("../../lib/api").Changelog }) {
  const hasNew = changelog.new_files?.length > 0;
  const hasRemoved = changelog.removed_files?.length > 0;
  const hasArch = changelog.architecture_changes?.length > 0;
  const hasDepAdded = changelog.dependency_changes?.added?.length > 0;
  const hasDepRemoved = changelog.dependency_changes?.removed?.length > 0;
  const hasDeps = hasDepAdded || hasDepRemoved;

  return (
    <div className="mb-6 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-700 rounded-2xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-lg">🔔</span>
        <h2 className="font-semibold text-blue-900 dark:text-blue-200 text-sm">What changed</h2>
        <span className="text-xs text-blue-500 dark:text-blue-300 bg-blue-100 dark:bg-blue-800/50 rounded-full px-2 py-0.5">auto-detected</span>
      </div>

      {changelog.summary && (
        <p className="text-sm text-blue-800 dark:text-blue-300 mb-4 leading-relaxed">{changelog.summary}</p>
      )}

      {changelog.highlights?.length > 0 && (
        <ul className="mb-4 space-y-1">
          {changelog.highlights.map((h, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-blue-800 dark:text-blue-300">
              <span className="text-blue-400 mt-0.5 shrink-0">→</span>
              {h}
            </li>
          ))}
        </ul>
      )}

      {(hasNew || hasRemoved || hasArch || hasDeps) && (
        <div className="grid sm:grid-cols-2 gap-3 mt-3">
          {hasNew && (
            <div className="bg-white dark:bg-slate-800 rounded-xl p-3 border border-blue-100 dark:border-slate-700">
              <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-300 mb-1.5">New files</p>
              <ul className="space-y-0.5">
                {changelog.new_files.map((f, i) => (
                  <li key={i} className="text-xs font-mono text-slate-700 dark:text-slate-300 truncate">+ {f}</li>
                ))}
              </ul>
            </div>
          )}
          {hasRemoved && (
            <div className="bg-white dark:bg-slate-800 rounded-xl p-3 border border-blue-100 dark:border-slate-700">
              <p className="text-xs font-semibold text-red-600 dark:text-red-300 mb-1.5">Removed files</p>
              <ul className="space-y-0.5">
                {changelog.removed_files.map((f, i) => (
                  <li key={i} className="text-xs font-mono text-slate-700 dark:text-slate-300 truncate">− {f}</li>
                ))}
              </ul>
            </div>
          )}
          {hasArch && (
            <div className="bg-white dark:bg-slate-800 rounded-xl p-3 border border-blue-100 dark:border-slate-700">
              <p className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Architecture changes</p>
              <ul className="space-y-0.5">
                {changelog.architecture_changes.map((c, i) => (
                  <li key={i} className="text-xs text-slate-600 dark:text-slate-400">• {c}</li>
                ))}
              </ul>
            </div>
          )}
          {hasDeps && (
            <div className="bg-white dark:bg-slate-800 rounded-xl p-3 border border-blue-100 dark:border-slate-700">
              <p className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Dependencies</p>
              {hasDepAdded && changelog.dependency_changes.added.map((d, i) => (
                <div key={i} className="text-xs font-mono text-emerald-700 dark:text-emerald-300 truncate">+ {d}</div>
              ))}
              {hasDepRemoved && changelog.dependency_changes.removed.map((d, i) => (
                <div key={i} className="text-xs font-mono text-red-600 dark:text-red-300 truncate">− {d}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

