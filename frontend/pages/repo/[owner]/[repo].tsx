import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { getRepoAnalysis, type Analysis } from "../../../lib/api";
import OwlLogo from "../../../components/OwlLogo";
import HealthScoreCard from "../../../components/HealthScoreCard";

export default function RepoPage() {
  const router = useRouter();
  const { owner, repo } = router.query as { owner: string; repo: string };
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [tab, setTab] = useState<"overview" | "health">("overview");

  useEffect(() => {
    if (!owner || !repo) return;
    setLoading(true);
    getRepoAnalysis(owner, repo)
      .then((a) => {
        if (a) {
          setAnalysis(a);
        } else {
          setNotFound(true);
        }
        setLoading(false);
      })
      .catch(() => {
        setNotFound(true);
        setLoading(false);
      });
  }, [owner, repo]);

  const fullName = `${owner}/${repo}`;
  const title = analysis?.result?.architecture?.project_name || fullName;

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-500">Loading analysis...</p>
        </div>
      </div>
    );
  }

  if (notFound || !analysis?.result) {
    return (
      <>
        <Head>
          <title>{fullName} — Hootly</title>
          <meta name="description" content={`Codebase analysis for ${fullName}`} />
        </Head>
        <div className="min-h-screen flex flex-col items-center justify-center px-4">
          <OwlLogo size={80} />
          <h1 className="text-2xl font-bold text-slate-900 mt-4 mb-2">{fullName}</h1>
          <p className="text-slate-500 mb-6 text-center max-w-md">
            No public analysis found for this repository. Be the first to analyze it!
          </p>
          <Link
            href={`/?repo=https://github.com/${fullName}`}
            className="bg-blue-600 text-white font-semibold px-6 py-3 rounded-xl hover:bg-blue-700 transition-colors"
          >
            Analyze this repo
          </Link>
        </div>
      </>
    );
  }

  const r = analysis.result;
  const arch = r.architecture;
  const badgeUrl = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/badge/${owner}/${repo}`;
  const badgeMarkdown = `[![Hootly](${badgeUrl})](https://www.hootlylabs.com/repo/${owner}/${repo})`;

  return (
    <>
      <Head>
        <title>{title} — Hootly Analysis</title>
        <meta name="description" content={arch.description} />
        <meta property="og:title" content={`${title} — Hootly Analysis`} />
        <meta property="og:description" content={arch.description} />
        <meta property="og:type" content="website" />
      </Head>

      <div className="min-h-screen bg-slate-50">
        {/* Header */}
        <header className="bg-white border-b border-slate-200 shadow-sm">
          <div className="max-w-4xl mx-auto px-4 py-4 flex items-center gap-3">
            <Link href="/">
              <OwlLogo size={36} />
            </Link>
            <div className="flex-1 min-w-0">
              <h1 className="font-bold text-slate-900 truncate">{fullName}</h1>
              <p className="text-sm text-slate-500 truncate">{arch.architecture_type} &middot; {arch.tech_stack.slice(0, 4).join(", ")}</p>
            </div>
            <a
              href={`https://github.com/${fullName}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-slate-500 hover:text-blue-600 border border-slate-200 px-3 py-1.5 rounded-lg transition-colors"
            >
              GitHub ↗
            </a>
          </div>

          {/* Tabs */}
          <div className="max-w-4xl mx-auto px-4 flex gap-4 -mb-px">
            <button
              onClick={() => setTab("overview")}
              className={`text-sm font-medium py-2 border-b-2 transition-colors ${
                tab === "overview" ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              Overview
            </button>
            {analysis.health_score && (
              <button
                onClick={() => setTab("health")}
                className={`text-sm font-medium py-2 border-b-2 transition-colors ${
                  tab === "health" ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                Health ({analysis.health_score.grade})
              </button>
            )}
          </div>
        </header>

        <main className="max-w-4xl mx-auto px-4 py-8">
          {tab === "overview" && (
            <div className="space-y-6">
              {/* Description */}
              <div className="bg-white border border-slate-200 rounded-2xl p-6">
                <h2 className="font-semibold text-slate-900 mb-2">About</h2>
                <p className="text-slate-700 leading-relaxed">{arch.description}</p>
                <p className="text-sm text-slate-600 mt-3 leading-relaxed">{arch.architecture_summary}</p>
              </div>

              {/* Quick info */}
              <div className="grid sm:grid-cols-3 gap-4">
                <div className="bg-white border border-slate-200 rounded-xl p-4">
                  <p className="text-xs text-slate-500 mb-1">Stack</p>
                  <div className="flex flex-wrap gap-1">
                    {arch.tech_stack.map((t) => (
                      <span key={t} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">{t}</span>
                    ))}
                  </div>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl p-4">
                  <p className="text-xs text-slate-500 mb-1">Languages</p>
                  <p className="text-sm text-slate-800">{arch.languages.join(", ")}</p>
                </div>
                <div className="bg-white border border-slate-200 rounded-xl p-4">
                  <p className="text-xs text-slate-500 mb-1">Type</p>
                  <p className="text-sm text-slate-800">{arch.architecture_type}</p>
                </div>
              </div>

              {/* Key files preview */}
              <div className="bg-white border border-slate-200 rounded-2xl p-6">
                <h2 className="font-semibold text-slate-900 mb-3">Key Files</h2>
                <div className="space-y-2">
                  {r.key_files.slice(0, 8).map((f, i) => (
                    <div key={f.path} className="flex items-start gap-2">
                      <span className="text-xs text-slate-400 mt-0.5 shrink-0">{i + 1}.</span>
                      <div>
                        <code className="text-sm text-blue-700">{f.path}</code>
                        <p className="text-xs text-slate-500 mt-0.5">{f.reason}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Guide preview */}
              {r.quick_start && (
                <div className="bg-white border border-slate-200 rounded-2xl p-6">
                  <h2 className="font-semibold text-slate-900 mb-3">Quick Start</h2>
                  <div className="guide-prose text-sm">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.quick_start}</ReactMarkdown>
                  </div>
                </div>
              )}

              {/* Badge */}
              <div className="bg-slate-100 border border-slate-200 rounded-2xl p-6">
                <h2 className="font-semibold text-slate-900 mb-2">Add a badge to your README</h2>
                <div className="flex items-center gap-3 mb-3">
                  <img src={badgeUrl} alt={`Hootly ${analysis.health_score?.grade || ""}`} />
                </div>
                <code className="block bg-white border border-slate-200 rounded-lg p-3 text-xs text-slate-700 break-all">
                  {badgeMarkdown}
                </code>
              </div>
            </div>
          )}

          {tab === "health" && analysis.health_score && (
            <HealthScoreCard healthScore={analysis.health_score} />
          )}
        </main>
      </div>
    </>
  );
}
