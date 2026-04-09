import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import { useRequireAuth } from "../../../lib/auth";
import {
  getOrgHealth, getCrossRepoDeps, getSharedPatterns, getTeam,
  type OrgHealthDashboard, type CrossRepoDep, type SharedPatterns, type Team,
} from "../../../lib/api";
import OwlLogo from "../../../components/OwlLogo";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ArrowLeft, Heart, GitBranch, Layers, AlertTriangle, Loader2,
} from "lucide-react";

export default function TeamOverviewPage() {
  const router = useRouter();
  const { id } = router.query as { id: string };
  const { user, loading: authLoading } = useRequireAuth();

  const [team, setTeam] = useState<Team | null>(null);
  const [health, setHealth] = useState<OrgHealthDashboard | null>(null);
  const [crossDeps, setCrossDeps] = useState<CrossRepoDep[]>([]);
  const [patterns, setPatterns] = useState<SharedPatterns | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      getTeam(id).then(setTeam).catch(() => {}),
      getOrgHealth(id).then(setHealth).catch(() => {}),
      getCrossRepoDeps(id).then(setCrossDeps).catch(() => {}),
      getSharedPatterns(id).then(setPatterns).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, [id]);

  if (authLoading || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <>
      <Head>
        <title>{team?.name || "Team"} Overview - Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
        <header className="sticky top-0 z-20 bg-white/80 dark:bg-slate-900/80 backdrop-blur border-b border-slate-200 dark:border-slate-800 px-4 py-3">
          <div className="max-w-6xl mx-auto flex items-center gap-3">
            <Button variant="ghost" size="sm" asChild>
              <Link href="/team"><ArrowLeft className="w-4 h-4" /></Link>
            </Button>
            <OwlLogo size={28} />
            <h1 className="font-semibold">{team?.name || "Team"} Overview</h1>
          </div>
        </header>

        <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-8">
          {/* Summary Cards */}
          {health && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm text-muted-foreground">Repos Analyzed</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold">{health.summary.total_repos}</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm text-muted-foreground">Avg Health Score</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold">{health.summary.avg_score}/100</div>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm text-muted-foreground flex items-center gap-1">
                    <AlertTriangle className="w-4 h-4 text-amber-500" /> At Risk
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-amber-600">{health.summary.at_risk_count}</div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Health Scores per Repo */}
          {health && health.repos.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Heart className="w-5 h-5" /> Repo Health Scores
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {health.repos.map((repo) => (
                    <div key={repo.repo_url} className="flex items-center gap-3">
                      <span className="text-sm font-mono flex-1 truncate">{repo.repo_name}</span>
                      <div className="w-32">
                        <div className="h-2 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              repo.overall_score >= 80 ? "bg-emerald-500" :
                              repo.overall_score >= 60 ? "bg-blue-500" :
                              repo.overall_score >= 40 ? "bg-amber-500" : "bg-red-500"
                            }`}
                            style={{ width: `${repo.overall_score}%` }}
                          />
                        </div>
                      </div>
                      <Badge variant={repo.grade <= "B" ? "default" : "secondary"}>
                        {repo.grade} ({repo.overall_score})
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Cross-Repo Dependencies */}
          {crossDeps.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <GitBranch className="w-5 h-5" /> Shared Dependencies ({crossDeps.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left p-2 font-medium">Package</th>
                        <th className="text-left p-2 font-medium">Type</th>
                        <th className="text-left p-2 font-medium">Repos</th>
                      </tr>
                    </thead>
                    <tbody>
                      {crossDeps.slice(0, 20).map((dep) => (
                        <tr key={dep.id} className="border-b border-slate-100 dark:border-slate-800">
                          <td className="p-2 font-mono text-xs">{dep.dependency_name}</td>
                          <td className="p-2">
                            <Badge variant="outline" className="text-xs">{dep.dependency_type}</Badge>
                          </td>
                          <td className="p-2 text-xs text-slate-500">
                            {dep.source_repo_url.replace("https://github.com/", "")} &harr;{" "}
                            {dep.target_repo_url.replace("https://github.com/", "")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Shared Patterns */}
          {patterns && patterns.total_repos > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Layers className="w-5 h-5" /> Shared Patterns
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid sm:grid-cols-2 gap-6">
                  <div>
                    <h4 className="text-sm font-medium mb-2">Tech Stack</h4>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(patterns.tech_stack).map(([tech, count]) => (
                        <Badge key={tech} variant="outline">
                          {tech} ({count})
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h4 className="text-sm font-medium mb-2">Languages</h4>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(patterns.languages).map(([lang, count]) => (
                        <Badge key={lang} variant="outline">
                          {lang} ({count})
                        </Badge>
                      ))}
                    </div>
                  </div>
                </div>

                {patterns.patterns.length > 0 && (
                  <div className="mt-4">
                    <h4 className="text-sm font-medium mb-2">Common Patterns</h4>
                    <div className="space-y-1">
                      {patterns.patterns.map((p) => (
                        <div key={p.name} className="flex items-center gap-2 text-sm">
                          <span>{p.name}</span>
                          <Badge variant="secondary" className="text-xs">{p.count} repos</Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {(!health || health.repos.length === 0) && (
            <div className="text-center py-12 text-slate-500">
              <Layers className="w-12 h-12 mx-auto mb-4 text-slate-300" />
              <p className="text-lg font-medium">No analyses yet</p>
              <p className="text-sm mt-1">
                Analyze repos as team members to see org-wide intelligence here.
              </p>
            </div>
          )}
        </main>
      </div>
    </>
  );
}
