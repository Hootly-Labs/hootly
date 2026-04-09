import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import { createCheckoutSession, createPortalSession } from "../lib/api";
import { useAuth } from "../lib/auth";
import OwlLogo from "../components/OwlLogo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Layers,
  FileText,
  Network,
  BookOpen,
  Map,
  BarChart3,
  Download,
  ShieldCheck,
  Users,
  Rocket,
  Search,
  GitPullRequest,
  Briefcase,
  Check,
  ArrowRight,
  Zap,
  Mail,
  MessageSquare,
} from "lucide-react";

const FEATURES = [
  {
    icon: Layers,
    title: "Architecture Overview",
    body: "Paste any repo URL and get the full architecture — tech stack, entry points, key directories, and how everything connects.",
    color: "text-blue-600 bg-blue-50",
  },
  {
    icon: FileText,
    title: "Key Files Ranked",
    body: "Every source file is read and ranked by importance, weighted by how many other files import it. Know exactly where to start.",
    color: "text-cyan-600 bg-cyan-50",
  },
  {
    icon: Network,
    title: "Interactive Dependency Graph",
    body: "D3 force graph of real import connections. Color by language or directory. Click any node to highlight its links.",
    color: "text-violet-600 bg-violet-50",
  },
  {
    icon: BookOpen,
    title: "Suggested Reading Order",
    body: "A step-by-step path through the codebase — tailored to the framework, architecture, and key files. Skip the guesswork.",
    color: "text-emerald-600 bg-emerald-50",
  },
  {
    icon: Map,
    title: "AI Onboarding Guide",
    body: "A full markdown guide covering project purpose, key workflows, how auth / routing / DB work, and where to start coding.",
    color: "text-amber-600 bg-amber-50",
  },
  {
    icon: BarChart3,
    title: "Codebase Health Report",
    body: "Get an A-F health grade with scores for modularity, test coverage, documentation, and more. Share professional assessment reports.",
    color: "text-rose-600 bg-rose-50",
  },
  {
    icon: Download,
    title: "Export & Share",
    body: "Download the full analysis as Markdown, print to PDF, or share a public link in one click.",
    color: "text-blue-600 bg-blue-50",
  },
  {
    icon: ShieldCheck,
    title: "README Health Badge",
    body: "Add a live health-grade badge to your README. Shows at a glance that the codebase is well-maintained.",
    color: "text-cyan-600 bg-cyan-50",
  },
  {
    icon: Users,
    title: "Team Dashboard",
    body: "Share analyses across your team. Everyone sees the same onboarding guides, health scores, and dependency graphs.",
    color: "text-violet-600 bg-violet-50",
  },
];

const USE_CASES = [
  {
    icon: Rocket,
    title: "Onboard new engineers",
    body: "New hire starts Monday. Paste the repo URL, share the onboarding guide. They're reading code by lunch, not hunting for the entry point.",
    color: "text-blue-600 bg-blue-50",
  },
  {
    icon: BarChart3,
    title: "Audit code health",
    body: "Get an architecture health score across your repos. Spot structural debt, missing tests, and documentation gaps before they become problems.",
    color: "text-emerald-600 bg-emerald-50",
  },
  {
    icon: Search,
    title: "Technical due diligence",
    body: "Evaluating an acquisition or investment? Get the full architecture breakdown, health grade, and risk areas in minutes — not weeks.",
    color: "text-violet-600 bg-violet-50",
  },
  {
    icon: GitPullRequest,
    title: "Help contributors onboard",
    body: "Add a health badge and onboarding guide to your open source project. New contributors understand the architecture before writing their first PR.",
    color: "text-amber-600 bg-amber-50",
  },
  {
    icon: Briefcase,
    title: "Ramp up on client codebases",
    body: "Freelancers and consultants: paste the repo URL, read the guide, start billing for real work — not orientation.",
    color: "text-rose-600 bg-rose-50",
  },
];

const PRICING = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    limit: "1 analysis / month",
    features: [
      "Architecture overview + AI onboarding guide",
      "Key files ranked by import usage",
      "Interactive dependency graph",
      "Suggested reading order",
      "Export to Markdown & PDF",
      "Shareable public links",
      "Analysis history & starred bookmarks",
      "Repo watching & change alerts",
      "GitHub OAuth — analyze private repos",
      "Up to 2,000 files per repo",
      "60 file reads per analysis",
    ],
    cta: "Start for free",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "$15",
    period: "per month",
    limit: "Unlimited analyses",
    features: [
      "Everything in Free",
      "Unlimited analyses across all repos",
      "Chat Q&A — ask questions about any codebase",
      "Professional assessment reports",
      "API access for programmatic use",
      "Up to 10,000 files per repo (5x)",
      "100 file reads per analysis (deeper)",
      "Priority support",
    ],
    cta: "Get Pro",
    highlighted: true,
  },
  {
    name: "Team",
    price: "$15",
    period: "per seat / month",
    limit: "Shared team workspace",
    features: [
      "Everything in Pro",
      "Shared analyses across your team",
      "Team dashboard with member management",
      "Invite teammates by email",
      "All Pro features for every seat",
    ],
    cta: "Start with your team",
    highlighted: false,
  },
];

// ── Animated demo mockup ──────────────────────────────────────────────────────
function AnimatedDemo() {
  const FRAMES = [
    { stage: "Cloning repository...", pct: 10 },
    { stage: "Pass 1/4 — Analyzing architecture", pct: 30 },
    { stage: "Pass 2/4 — Ranking key files", pct: 55 },
    { stage: "Pass 3/4 — Explaining files", pct: 75 },
    { stage: "Pass 4/4 — Writing onboarding guide", pct: 90 },
    { stage: "Analysis complete", pct: 100 },
  ];
  const [frame, setFrame] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (done) return;
    const t = setTimeout(() => {
      if (frame < FRAMES.length - 1) {
        setFrame((f) => f + 1);
      } else {
        setDone(true);
        setTimeout(() => { setFrame(0); setDone(false); }, 3000);
      }
    }, 900);
    return () => clearTimeout(t);
  }, [frame, done]);

  const current = FRAMES[frame];

  return (
    <Card className="bg-[#0d1117] border-slate-700/50 shadow-2xl shadow-black/40 overflow-hidden">
      {/* window chrome */}
      <div className="bg-[#161b22] flex items-center gap-1.5 px-4 py-3 border-b border-slate-700/60">
        <span className="w-3 h-3 rounded-full bg-red-500/80" />
        <span className="w-3 h-3 rounded-full bg-yellow-500/80" />
        <span className="w-3 h-3 rounded-full bg-green-500/80" />
        <span className="ml-3 text-xs text-slate-500 tracking-wide font-mono">hootly — analysis</span>
        <div className="ml-auto flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-xs text-slate-500">live</span>
        </div>
      </div>

      <CardContent className="p-5 space-y-4">
        {/* Stages */}
        <div className="space-y-2.5">
          {FRAMES.map((f, i) => (
            <div key={i} className={`flex items-center gap-3 transition-opacity duration-300 ${i > frame ? "opacity-20" : "opacity-100"}`}>
              {i < frame || done ? (
                <Check className="w-3 h-3 text-emerald-400 shrink-0" />
              ) : i === frame ? (
                <span className="inline-block w-2 h-2 rounded-full bg-blue-400 animate-pulse shrink-0" />
              ) : (
                <span className="w-2 h-2 rounded-full border border-slate-600 shrink-0" />
              )}
              <span className={`text-xs font-mono ${i <= frame ? "text-slate-300" : "text-slate-600"}`}>{f.stage}</span>
              {i === frame && !done && (
                <span className="ml-auto text-xs text-blue-500/70 font-mono">{f.pct}%</span>
              )}
            </div>
          ))}
        </div>

        {/* Progress bar */}
        <div className="bg-slate-800 rounded-full h-1.5 overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700 ease-in-out bg-gradient-to-r from-blue-600 to-cyan-500"
            style={{ width: `${current.pct}%` }}
          />
        </div>

        {/* "Result" preview when done */}
        {done && (
          <div className="border border-slate-700/60 rounded-lg p-4 space-y-2.5 bg-slate-800/30">
            <div className="flex items-center gap-2">
              <span className="text-emerald-400 text-xs font-semibold tracking-widest uppercase">Architecture</span>
              <Badge variant="outline" className="ml-auto border-emerald-500/30 text-emerald-400 text-[10px]">
                completed
              </Badge>
            </div>
            <div className="text-slate-400 text-xs">Full-stack web app &middot; Next.js + FastAPI &middot; Python + TypeScript</div>
            <div className="flex gap-2 mt-1 flex-wrap">
              {["backend/", "frontend/", "api/", "models/"].map((d) => (
                <span key={d} className="text-xs bg-slate-800 text-blue-400 border border-slate-700/60 px-2 py-0.5 rounded-md font-mono">{d}</span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Home() {
  const router = useRouter();
  const { user, logout } = useAuth();

  // Redirect authenticated users to dashboard
  useEffect(() => {
    if (user) router.replace("/dashboard");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  async function handleUpgradeClick() {
    try {
      const { url: checkoutUrl } = await createCheckoutSession();
      window.location.href = checkoutUrl;
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Could not start checkout. Please try again.");
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

  return (
    <>
      <Head>
        <title>Hootly — Instant codebase onboarding with AI</title>
        <meta name="description" content="Understand any GitHub repo in minutes. Hootly gives you architecture maps, key files, dependency graphs, health scores, and AI-generated onboarding guides — powered by Claude AI." />
      </Head>

      <div className="min-h-screen bg-slate-50">
        {/* ── Nav ── */}
        <nav className="border-b border-slate-200 bg-white/90 backdrop-blur-md sticky top-0 z-20">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <OwlLogo size={72} />
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                <a href="#features">Features</a>
              </Button>
              <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                <a href="#use-cases">Use Cases</a>
              </Button>
              <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                <a href="#pricing">Pricing</a>
              </Button>

              <Separator orientation="vertical" className="h-6 mx-2 hidden sm:block" />

              {user ? (
                <div className="flex items-center gap-2">
                  {user.is_admin && (
                    <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                      <Link href="/admin">Admin</Link>
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                    <Link href="/analyses">History</Link>
                  </Button>
                  <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
                    <Link href="/settings">Settings</Link>
                  </Button>
                  {user.plan === "free" ? (
                    <Button variant="outline" size="sm" onClick={handleUpgradeClick} className="hidden sm:inline-flex text-amber-700 border-amber-200 bg-amber-50 hover:bg-amber-100 hover:text-amber-800">
                      <Zap className="w-3.5 h-3.5" />
                      Upgrade to Pro
                    </Button>
                  ) : user.plan === "pro" ? (
                    <Button variant="outline" size="sm" onClick={handleManageBilling} className="hidden sm:inline-flex text-blue-700 border-blue-200 bg-blue-50 hover:bg-blue-100 hover:text-blue-800">
                      Manage billing
                    </Button>
                  ) : null}
                  <Button variant="ghost" size="sm" onClick={logout}>
                    Log out
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" asChild>
                    <Link href="/login">Log in</Link>
                  </Button>
                  <Button size="sm" asChild>
                    <Link href="/signup">Sign up free</Link>
                  </Button>
                </div>
              )}
            </div>
          </div>
        </nav>

        {/* ── Hero ── */}
        <section className="relative overflow-hidden">
          <div className="absolute inset-0 hero-grid-bg opacity-60 pointer-events-none" />
          <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-slate-50 to-transparent pointer-events-none" />

          <div className="relative max-w-6xl mx-auto px-4 sm:px-6 pt-20 pb-24">
            <div className="grid lg:grid-cols-2 gap-12 items-center">
              <div>
                <Badge variant="outline" className="mb-6 gap-2 border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-50">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                  Powered by Claude AI
                </Badge>

                <h1 className="text-5xl sm:text-6xl font-bold tracking-tight text-slate-900 leading-[1.1] mb-6">
                  Understand any{" "}
                  <span className="gradient-text">codebase</span>{" "}
                  in minutes
                </h1>

                <p className="text-lg text-slate-600 leading-relaxed mb-8 max-w-lg">
                  Paste a GitHub URL. Get the full architecture, key files, dependency graph,
                  and a step-by-step onboarding guide — generated by AI in under two minutes.
                </p>

                <div className="flex flex-wrap gap-2 mb-10">
                  {[
                    { label: "Architecture map",  color: "bg-blue-500" },
                    { label: "Key files ranked",  color: "bg-cyan-500" },
                    { label: "Dep graph",         color: "bg-violet-500" },
                    { label: "Health score",      color: "bg-emerald-500" },
                    { label: "Assessment reports", color: "bg-amber-500" },
                    { label: "Team sharing",       color: "bg-rose-500" },
                  ].map((f) => (
                    <Badge key={f.label} variant="secondary" className="gap-1.5 font-mono text-xs font-normal bg-white border border-slate-200 text-slate-700 shadow-sm hover:bg-white">
                      <span className={`w-1.5 h-1.5 rounded-full ${f.color}`} />
                      {f.label}
                    </Badge>
                  ))}
                </div>

                <div className="flex flex-wrap gap-3">
                  {user ? (
                    <Button size="lg" asChild className="shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30">
                      <Link href="/dashboard">
                        Go to Dashboard
                        <ArrowRight className="w-4 h-4" />
                      </Link>
                    </Button>
                  ) : (
                    <>
                      <Button size="lg" asChild className="shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30">
                        <Link href="/signup">
                          Get started free
                          <ArrowRight className="w-4 h-4" />
                        </Link>
                      </Button>
                      <Button size="lg" variant="outline" asChild>
                        <a href="#features">See how it works</a>
                      </Button>
                    </>
                  )}
                </div>
              </div>

              {/* Animated demo */}
              <div className="w-full max-w-md mx-auto lg:mx-0">
                <AnimatedDemo />
              </div>
            </div>
          </div>
        </section>

        {/* ── Features ── */}
        <section id="features" className="bg-white border-y border-slate-200 py-20">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-14">
              <Badge variant="secondary" className="mb-4 font-mono text-xs tracking-widest uppercase">
                All plans
              </Badge>
              <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
                From repo URL to productive in minutes
              </h2>
              <p className="text-slate-500 max-w-xl mx-auto text-lg">
                Hootly reads the repo like a senior engineer — architecture first, then files, then the full picture.
              </p>
            </div>

            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {FEATURES.map((f) => {
                const Icon = f.icon;
                return (
                  <Card key={f.title} className="group border-slate-100 bg-slate-50/50 hover:bg-white hover:border-blue-200 hover:shadow-lg transition-all duration-200">
                    <CardHeader className="pb-3">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-1 ${f.color}`}>
                        <Icon className="w-5 h-5" />
                      </div>
                      <CardTitle className="text-base">{f.title}</CardTitle>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <CardDescription className="leading-relaxed">{f.body}</CardDescription>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
        </section>

        {/* ── Use Cases ── */}
        <section id="use-cases" className="py-20">
          <div className="max-w-6xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-14">
              <Badge variant="secondary" className="mb-4 font-mono text-xs tracking-widest uppercase">
                Use cases
              </Badge>
              <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">
                Who uses Hootly
              </h2>
              <p className="text-slate-500 max-w-xl mx-auto text-lg">
                Teams, managers, investors, maintainers, and freelancers — anyone who needs to understand a codebase fast.
              </p>
            </div>

            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {USE_CASES.map((uc) => {
                const Icon = uc.icon;
                return (
                  <Card key={uc.title} className="bg-white hover:shadow-lg transition-all duration-200">
                    <CardHeader className="pb-3">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-1 ${uc.color}`}>
                        <Icon className="w-5 h-5" />
                      </div>
                      <CardTitle className="text-base">{uc.title}</CardTitle>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <CardDescription className="leading-relaxed">{uc.body}</CardDescription>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
        </section>

        {/* ── Pricing ── */}
        <section id="pricing" className="bg-white border-y border-slate-200 py-20">
          <div className="max-w-5xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-14">
              <Badge variant="secondary" className="mb-4 font-mono text-xs tracking-widest uppercase">
                Pricing
              </Badge>
              <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">Simple, transparent pricing</h2>
              <p className="text-slate-500 text-lg">Start free. Upgrade when you need more.</p>
            </div>

            <div className="grid sm:grid-cols-3 gap-6">
              {PRICING.map((plan) => (
                <Card
                  key={plan.name}
                  className={`relative flex flex-col ${
                    plan.highlighted
                      ? "bg-slate-900 border-slate-900 text-white shadow-2xl shadow-slate-900/20 scale-[1.02]"
                      : "bg-white"
                  }`}
                >
                  {plan.highlighted && (
                    <Badge className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-600 hover:bg-blue-600">
                      Most popular
                    </Badge>
                  )}
                  <CardHeader>
                    <CardTitle className={`text-lg ${plan.highlighted ? "text-white" : ""}`}>
                      {plan.name}
                    </CardTitle>
                    <div className="flex items-baseline gap-1 mt-2">
                      <span className={`text-4xl font-bold tracking-tight ${plan.highlighted ? "text-white" : "text-slate-900"}`}>
                        {plan.price}
                      </span>
                      <span className={`text-sm ${plan.highlighted ? "text-slate-400" : "text-slate-500"}`}>
                        / {plan.period}
                      </span>
                    </div>
                    <p className={`text-sm mt-1 ${plan.highlighted ? "text-slate-400" : "text-slate-500"}`}>
                      {plan.limit}
                    </p>
                  </CardHeader>

                  <CardContent className="flex-1">
                    <ul className="space-y-3">
                      {plan.features.map((f) => (
                        <li key={f} className="flex items-start gap-2.5 text-sm">
                          <Check className={`h-4 w-4 shrink-0 mt-0.5 ${plan.highlighted ? "text-blue-400" : "text-emerald-500"}`} />
                          <span className={plan.highlighted ? "text-slate-300" : "text-slate-700"}>{f}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>

                  <CardFooter>
                    <Button
                      className={`w-full ${
                        plan.highlighted
                          ? "bg-white text-slate-900 hover:bg-slate-100"
                          : ""
                      }`}
                      variant={plan.highlighted ? "secondary" : "default"}
                      size="lg"
                      onClick={() => {
                        if (plan.name === "Pro") {
                          if (!user) {
                            router.push("/signup");
                          } else {
                            handleUpgradeClick();
                          }
                        } else if (plan.name === "Team") {
                          if (!user) {
                            router.push("/signup");
                          } else {
                            router.push("/team");
                          }
                        } else {
                          if (user) {
                            router.push("/dashboard");
                          } else {
                            router.push("/signup");
                          }
                        }
                      }}
                    >
                      {plan.cta}
                    </Button>
                  </CardFooter>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* ── Contact ── */}
        <section className="py-20">
          <div className="max-w-4xl mx-auto px-4 sm:px-6">
            <div className="text-center mb-14">
              <Badge variant="secondary" className="mb-4 font-mono text-xs tracking-widest uppercase">
                Get in touch
              </Badge>
              <h2 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-4">We&rsquo;re here to help</h2>
              <p className="text-slate-500 text-lg">Reach out any time — we typically respond within one business day.</p>
            </div>

            <div className="grid sm:grid-cols-2 gap-6">
              <Card className="bg-slate-50/50">
                <CardHeader>
                  <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center mb-1">
                    <Mail className="w-5 h-5" />
                  </div>
                  <CardTitle className="text-base">Support</CardTitle>
                  <CardDescription>
                    Having trouble with an analysis, billing, or your account? Drop us a line and we&rsquo;ll get you sorted.
                  </CardDescription>
                </CardHeader>
                <CardContent className="pt-0">
                  <Button variant="link" asChild className="p-0 h-auto text-blue-600">
                    <a href="mailto:support@hootlylabs.com">
                      support@hootlylabs.com
                      <ArrowRight className="w-3.5 h-3.5" />
                    </a>
                  </Button>
                </CardContent>
              </Card>

              <Card className="bg-slate-50/50">
                <CardHeader>
                  <div className="w-10 h-10 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center mb-1">
                    <MessageSquare className="w-5 h-5" />
                  </div>
                  <CardTitle className="text-base">General questions</CardTitle>
                  <CardDescription>
                    Curious about Hootly, partnerships, or have a feature idea? We&rsquo;d love to hear from you.
                  </CardDescription>
                </CardHeader>
                <CardContent className="pt-0">
                  <Button variant="link" asChild className="p-0 h-auto text-emerald-600">
                    <a href="mailto:hello@hootlylabs.com">
                      hello@hootlylabs.com
                      <ArrowRight className="w-3.5 h-3.5" />
                    </a>
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>
        </section>

        {/* ── Footer ── */}
        <footer className="border-t border-slate-200 py-8">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 flex items-center justify-between flex-wrap gap-4">
            <div className="flex items-center gap-2">
              <OwlLogo size={32} />
            </div>
            <div className="flex items-center gap-4 text-xs text-slate-400">
              <a href="mailto:support@hootlylabs.com" className="hover:text-slate-600 transition-colors">support@hootlylabs.com</a>
              <Separator orientation="vertical" className="h-3" />
              <a href="mailto:hello@hootlylabs.com" className="hover:text-slate-600 transition-colors">hello@hootlylabs.com</a>
              <Separator orientation="vertical" className="h-3" />
              <span className="font-mono">Powered by Claude AI</span>
            </div>
          </div>
        </footer>
      </div>
    </>
  );
}
