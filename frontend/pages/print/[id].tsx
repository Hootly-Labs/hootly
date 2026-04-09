import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getAnalysis, type AnalysisResult } from "../../lib/api";
import OwlLogo from "../../components/OwlLogo";

export default function PrintPage() {
  const router = useRouter();
  const { id } = router.query as { id: string };
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [repoUrl, setRepoUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) return;
    getAnalysis(id)
      .then((a) => {
        if (a.status !== "completed" || !a.result) {
          setError("Analysis not complete yet.");
          return;
        }
        setResult(a.result);
        setRepoUrl(a.repo_url);
      })
      .catch(() => setError("Could not load analysis."));
  }, [id]);

  // Auto-print once content is ready
  useEffect(() => {
    if (!result) return;
    const t = setTimeout(() => window.print(), 600);
    return () => clearTimeout(t);
  }, [result]);

  if (error) {
    return <div className="p-8 text-red-600">{error}</div>;
  }
  if (!result) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-500">
        Preparing PDF…
      </div>
    );
  }

  const r = result;
  const generatedAt = new Date().toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric",
  });

  return (
    <>
      <Head>
        <title>{r.repo_name} — Hootly Onboarding Guide</title>
        <style>{`
          @media print {
            .no-print { display: none !important; }
            @page { margin: 1.5cm 2cm; }
            body { font-size: 11pt; }
          }
          body { background: white; }
        `}</style>
      </Head>

      {/* Print controls — hidden when printing */}
      <div className="no-print flex items-center gap-3 bg-slate-800 text-white px-6 py-3 sticky top-0 z-10">
        <span className="text-sm text-slate-300 flex-1">
          Print preview for <span className="font-mono text-white">{r.repo_name}</span>
        </span>
        <button
          onClick={() => window.print()}
          className="bg-blue-500 hover:bg-blue-400 text-white text-sm font-semibold px-4 py-1.5 rounded-lg transition-colors flex items-center gap-1.5"
        >
          <PrintIcon /> Save as PDF
        </button>
        <button
          onClick={() => window.close()}
          className="text-slate-400 hover:text-white text-sm px-3 py-1.5 rounded-lg transition-colors"
        >
          Close
        </button>
      </div>

      {/* Report */}
      <div className="max-w-4xl mx-auto px-8 py-10 print:px-0 print:py-0 print:max-w-none">

        {/* Cover */}
        <div className="mb-10 pb-8 border-b-2 border-slate-200">
          <div className="flex items-center gap-2 mb-3">
            <OwlLogo size={40} />
            <span className="text-sm font-semibold text-slate-500 uppercase tracking-widest">Hootly</span>
          </div>
          <h1 className="text-4xl font-bold text-slate-900 mb-2 font-mono">{r.repo_name}</h1>
          <p className="text-slate-500 text-sm">
            Generated {generatedAt} · <span className="font-mono">{repoUrl}</span>
          </p>
          {r.architecture?.description && (
            <p className="mt-4 text-lg text-slate-700 leading-relaxed">{r.architecture.description}</p>
          )}
        </div>

        {/* Architecture */}
        <Section title="Architecture Overview">
          <div className="grid grid-cols-2 gap-6 mb-4">
            <div>
              <Label>Type</Label>
              <p className="text-slate-800">{r.architecture.architecture_type}</p>
            </div>
            <div>
              <Label>Runtime</Label>
              <p className="text-slate-800 font-mono">{r.architecture.runtime || "—"}</p>
            </div>
            <div>
              <Label>Languages</Label>
              <p className="text-slate-800">{r.architecture.languages.join(", ")}</p>
            </div>
            <div>
              <Label>License</Label>
              <p className="text-slate-800">{r.architecture.license || "Unknown"}</p>
            </div>
          </div>

          <p className="text-slate-700 leading-relaxed mb-4">{r.architecture.architecture_summary}</p>

          {r.architecture.tech_stack.length > 0 && (
            <div className="mb-4">
              <Label>Tech Stack</Label>
              <p className="text-slate-800">{r.architecture.tech_stack.join(" · ")}</p>
            </div>
          )}

          {r.architecture.entry_points.length > 0 && (
            <div className="mb-4">
              <Label>Entry Points</Label>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {r.architecture.entry_points.map((ep) => (
                  <code key={ep} className="bg-amber-50 text-amber-800 border border-amber-200 rounded px-2 py-0.5 text-sm">{ep}</code>
                ))}
              </div>
            </div>
          )}

          {r.architecture.key_directories.length > 0 && (
            <div>
              <Label>Key Directories</Label>
              <div className="mt-1 space-y-1">
                {r.architecture.key_directories.map((d) => (
                  <div key={d.path} className="flex gap-3 text-sm">
                    <code className="text-blue-700 font-mono w-32 shrink-0">{d.path}</code>
                    <span className="text-slate-600">{d.purpose}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Section>

        {/* Quick Start */}
        {r.quick_start && (
          <Section title="Quick Start">
            <p className="text-slate-700 leading-relaxed">{r.quick_start}</p>
          </Section>
        )}

        {/* Key Concepts */}
        {r.key_concepts?.length > 0 && (
          <Section title="Key Concepts">
            <ul className="space-y-1.5">
              {r.key_concepts.map((c, i) => (
                <li key={i} className="flex gap-2 text-slate-700 text-sm">
                  <span className="text-blue-500 shrink-0">▸</span>{c}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Onboarding Guide */}
        {r.onboarding_guide && (
          <Section title="Onboarding Guide">
            <div className="guide-prose print-prose">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {r.onboarding_guide}
              </ReactMarkdown>
            </div>
          </Section>
        )}

        {/* Reading Order */}
        {r.reading_order?.length > 0 && (
          <Section title="Suggested Reading Order">
            <div className="space-y-2">
              {r.reading_order.map((step, i) => (
                <div key={i} className="flex gap-3 items-start">
                  <span className="shrink-0 w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center">
                    {step.step ?? i + 1}
                  </span>
                  <div>
                    <code className="text-blue-700 font-mono text-sm">{step.path}</code>
                    {step.reason && <p className="text-slate-600 text-sm">{step.reason}</p>}
                  </div>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Key Files */}
        {r.key_files?.length > 0 && (
          <Section title="Key Files">
            <div className="space-y-5">
              {r.key_files.filter((f) => f.explanation).map((file, i) => (
                <div key={file.path} className="break-inside-avoid">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-slate-400 text-xs w-5 text-right">#{i + 1}</span>
                    <code className="font-mono text-blue-700 font-medium text-sm">{file.path}</code>
                    <ScorePill score={file.score} />
                  </div>
                  {file.reason && (
                    <p className="text-slate-500 italic text-sm ml-7 mb-1">{file.reason}</p>
                  )}
                  {file.explanation && (
                    <p className="text-slate-700 text-sm leading-relaxed ml-7">{file.explanation}</p>
                  )}
                  {file.key_exports?.length > 0 && (
                    <div className="ml-7 mt-1 flex flex-wrap gap-1">
                      {file.key_exports.map((exp) => (
                        <code key={exp} className="text-xs bg-slate-100 text-slate-600 rounded px-1.5 py-0.5">{exp}</code>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Dependencies */}
        {(r.dependencies?.runtime?.length > 0 || r.dependencies?.dev?.length > 0) && (
          <Section title="Dependencies">
            {r.dependencies.runtime?.length > 0 && (
              <div className="mb-4">
                <Label>Runtime ({r.dependencies.runtime.length})</Label>
                <p className="text-slate-700 text-sm mt-1">{r.dependencies.runtime.join(" · ")}</p>
              </div>
            )}
            {r.dependencies.dev?.length > 0 && (
              <div>
                <Label>Dev / Build ({r.dependencies.dev.length})</Label>
                <p className="text-slate-700 text-sm mt-1">{r.dependencies.dev.join(" · ")}</p>
              </div>
            )}
          </Section>
        )}

        {/* Footer */}
        <div className="mt-12 pt-6 border-t border-slate-200 text-xs text-slate-400 text-center">
          Generated by Hootly · {generatedAt}
        </div>
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8 break-inside-avoid">
      <h2 className="text-xl font-bold text-slate-900 mb-4 pb-2 border-b border-slate-200">{title}</h2>
      {children}
    </section>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <p className="text-xs uppercase font-semibold text-slate-400 tracking-wider mb-1">{children}</p>;
}

function ScorePill({ score }: { score: number }) {
  const color =
    score >= 9 ? "bg-red-100 text-red-700" :
    score >= 7 ? "bg-orange-100 text-orange-700" :
    score >= 5 ? "bg-yellow-100 text-yellow-700" :
                 "bg-slate-100 text-slate-500";
  return (
    <span className={`text-xs font-semibold rounded-full px-2 py-0.5 ${color}`}>
      {score}/10
    </span>
  );
}

function PrintIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
      <path fillRule="evenodd" d="M5 4v3H4a2 2 0 00-2 2v3a2 2 0 002 2h1v2a1 1 0 001 1h8a1 1 0 001-1v-2h1a2 2 0 002-2V9a2 2 0 00-2-2h-1V4a1 1 0 00-1-1H6a1 1 0 00-1 1zm2 0h6v3H7V4zm-1 9v-1h8v1H6zm-2-4a1 1 0 110-2 1 1 0 010 2z" clipRule="evenodd" />
    </svg>
  );
}
