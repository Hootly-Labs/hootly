import Head from "next/head";
import Link from "next/link";
import OwlLogo from "../components/OwlLogo";

export default function GitHubAppPage() {
  const installUrl = process.env.NEXT_PUBLIC_GITHUB_APP_INSTALL_URL || "#";

  return (
    <>
      <Head>
        <title>GitHub App — Hootly</title>
        <meta name="description" content="Install the Hootly GitHub App for automatic codebase analysis and onboarding guides." />
      </Head>

      <div className="min-h-screen bg-slate-50">
        {/* Nav */}
        <nav className="bg-white border-b border-slate-200">
          <div className="max-w-4xl mx-auto px-4 py-3 flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2">
              <OwlLogo size={32} />
              <span className="font-bold text-slate-900">Hootly</span>
            </Link>
          </div>
        </nav>

        <main className="max-w-3xl mx-auto px-4 py-16">
          {/* Hero */}
          <div className="text-center mb-16">
            <h1 className="text-4xl font-bold text-slate-900 mb-4">
              Hootly for GitHub
            </h1>
            <p className="text-lg text-slate-600 max-w-xl mx-auto mb-8">
              Install once, get automatic architecture analysis for every repo.
              New contributors get onboarding context right in their PR.
            </p>
            <a
              href={installUrl}
              className="inline-flex items-center gap-2 bg-slate-900 text-white font-semibold px-8 py-4 rounded-xl hover:bg-slate-800 transition-colors text-lg"
            >
              <svg className="h-6 w-6" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
              </svg>
              Install GitHub App
            </a>
          </div>

          {/* Features */}
          <div className="grid md:grid-cols-3 gap-6 mb-16">
            <div className="bg-white border border-slate-200 rounded-2xl p-6">
              <div className="text-2xl mb-3">🔄</div>
              <h3 className="font-semibold text-slate-900 mb-2">Auto-Analysis</h3>
              <p className="text-sm text-slate-600">
                Automatically analyzes your repos on install. Re-analyzes when you push significant changes (5+ files) to the default branch.
              </p>
            </div>
            <div className="bg-white border border-slate-200 rounded-2xl p-6">
              <div className="text-2xl mb-3">💬</div>
              <h3 className="font-semibold text-slate-900 mb-2">PR Context</h3>
              <p className="text-sm text-slate-600">
                When a new contributor opens a PR, Hootly auto-comments with relevant architecture context, key files, and patterns.
              </p>
            </div>
            <div className="bg-white border border-slate-200 rounded-2xl p-6">
              <div className="text-2xl mb-3">📊</div>
              <h3 className="font-semibold text-slate-900 mb-2">Health Badge</h3>
              <p className="text-sm text-slate-600">
                Get a README badge showing your architecture health grade (A-F). Updates automatically when your code changes.
              </p>
            </div>
          </div>

          {/* How it works */}
          <div className="bg-white border border-slate-200 rounded-2xl p-8 mb-16">
            <h2 className="text-xl font-bold text-slate-900 mb-6 text-center">How it works</h2>
            <div className="space-y-4">
              {[
                { step: 1, title: "Install", desc: "Click the button above and select which repos to include." },
                { step: 2, title: "Analyze", desc: "Hootly automatically analyzes your selected repos. Takes 30-90 seconds per repo." },
                { step: 3, title: "Onboard", desc: "View interactive onboarding guides, health scores, and share with your team." },
                { step: 4, title: "Stay updated", desc: "Push changes and Hootly re-analyzes. New PRs get architecture context." },
              ].map(({ step, title, desc }) => (
                <div key={step} className="flex gap-4 items-start">
                  <div className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center text-sm font-bold shrink-0">
                    {step}
                  </div>
                  <div>
                    <p className="font-semibold text-slate-900">{title}</p>
                    <p className="text-sm text-slate-600">{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Permissions */}
          <div className="bg-slate-100 rounded-2xl p-8 text-center">
            <h2 className="font-semibold text-slate-900 mb-3">Minimal Permissions</h2>
            <p className="text-sm text-slate-600 mb-4">
              Hootly only requests what it needs:
            </p>
            <div className="inline-flex flex-col gap-2 text-left text-sm">
              <div className="flex items-center gap-2">
                <span className="text-green-600">✓</span>
                <span className="text-slate-700">Contents: <strong>read-only</strong></span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-green-600">✓</span>
                <span className="text-slate-700">Pull requests: <strong>write</strong> (for comments)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-green-600">✓</span>
                <span className="text-slate-700">Metadata: <strong>read-only</strong></span>
              </div>
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
