import { useState, useEffect, FormEvent } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRequireAuth } from "../../lib/auth";
import {
  listTeams,
  createTeam,
  getTeam,
  inviteTeamMember,
  removeTeamMember,
  getTeamAnalyses,
  createTeamCheckout,
  createPortalSession,
  type Team,
  type Analysis,
} from "../../lib/api";
import OwlLogo from "../../components/OwlLogo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Users,
  Plus,
  UserPlus,
  Crown,
  Clock,
  Trash2,
  CreditCard,
  ArrowRight,
  CheckCircle,
  XCircle,
  Loader2,
  BarChart3,
} from "lucide-react";

export default function TeamPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);
  const [analyses, setAnalyses] = useState<Analysis[]>([]);
  const [loading, setLoading] = useState(true);

  // Create team
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState("");

  // Invite
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteLoading, setInviteLoading] = useState(false);
  const [inviteError, setInviteError] = useState("");
  const [inviteSuccess, setInviteSuccess] = useState(false);

  useEffect(() => {
    if (user) {
      listTeams()
        .then((t) => {
          setTeams(t);
          if (t.length > 0) setSelectedTeam(t[0]);
          setLoading(false);
        })
        .catch(() => setLoading(false));
    }
  }, [user]);

  useEffect(() => {
    if (selectedTeam) {
      getTeamAnalyses(selectedTeam.id).then(setAnalyses).catch(() => {});
    }
  }, [selectedTeam?.id]);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setCreateLoading(true);
    setCreateError("");
    try {
      const team = await createTeam(name);
      setTeams((prev) => [...prev, team]);
      setSelectedTeam(team);
      setShowCreate(false);
      setNewName("");
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "Failed to create team");
    }
    setCreateLoading(false);
  }

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    if (!selectedTeam || !inviteEmail.trim()) return;
    setInviteLoading(true);
    setInviteError("");
    setInviteSuccess(false);
    try {
      await inviteTeamMember(selectedTeam.id, inviteEmail.trim());
      setInviteSuccess(true);
      setInviteEmail("");
      // Refresh team to show new member
      const updated = await getTeam(selectedTeam.id);
      setSelectedTeam(updated);
      setTeams((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    } catch (err: unknown) {
      setInviteError(err instanceof Error ? err.message : "Failed to invite member");
    }
    setInviteLoading(false);
  }

  async function handleRemove(userId: string) {
    if (!selectedTeam || !confirm("Remove this member from the team?")) return;
    try {
      await removeTeamMember(selectedTeam.id, userId);
      const updated = await getTeam(selectedTeam.id);
      setSelectedTeam(updated);
      setTeams((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    } catch {
      alert("Failed to remove team member.");
    }
  }

  if (authLoading || loading) return null;

  const isOwner = selectedTeam?.owner_id === user?.id;

  return (
    <>
      <Head>
        <title>Teams — Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50">
        <header className="bg-white border-b border-slate-200">
          <div className="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/dashboard" className="flex items-center gap-2">
                <OwlLogo size={72} />
              </Link>
              <span className="text-xl text-slate-300">/</span>
              <span className="text-lg font-semibold text-slate-700">Teams</span>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild>
                <Link href="/analyses">History</Link>
              </Button>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/analytics">Analytics</Link>
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

        <main className="max-w-5xl mx-auto px-4 sm:px-6 py-10">
          <div className="flex flex-col sm:flex-row gap-8">
            {/* Sidebar — team list */}
            <nav className="sm:w-52 shrink-0">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-slate-700">Your Teams</h2>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowCreate(true)}
                  className="h-7 px-2"
                >
                  <Plus className="w-3.5 h-3.5 mr-1" />
                  New
                </Button>
              </div>
              {teams.length === 0 && !showCreate ? (
                <p className="text-sm text-muted-foreground">No teams yet.</p>
              ) : (
                <ul className="space-y-0.5">
                  {teams.map((t) => (
                    <li key={t.id}>
                      <button
                        onClick={() => setSelectedTeam(t)}
                        className={`w-full text-left px-3 py-2.5 rounded-xl text-sm font-medium transition-colors flex items-center gap-2 ${
                          selectedTeam?.id === t.id
                            ? "bg-blue-50 text-blue-700"
                            : "text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        <Users className="w-3.5 h-3.5" />
                        {t.name}
                        <span className="text-xs text-muted-foreground ml-auto">({t.members.length})</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {showCreate && (
                <form onSubmit={handleCreate} className="mt-3 space-y-2">
                  <Input
                    type="text"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="Team name"
                    autoFocus
                  />
                  {createError && <p className="text-xs text-red-600">{createError}</p>}
                  <div className="flex gap-2">
                    <Button
                      type="submit"
                      size="sm"
                      disabled={createLoading}
                    >
                      {createLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Create"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => { setShowCreate(false); setNewName(""); setCreateError(""); }}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              )}
            </nav>

            {/* Content */}
            <div className="flex-1 space-y-5">
              {selectedTeam ? (
                <>
                  {/* Team info */}
                  <Card>
                    <CardContent className="pt-6">
                      <h2 className="text-lg font-bold text-slate-900 mb-1">{selectedTeam.name}</h2>
                      <p className="text-sm text-muted-foreground">
                        {selectedTeam.members.length} member{selectedTeam.members.length !== 1 ? "s" : ""} · {selectedTeam.analysis_count} analyses
                      </p>
                    </CardContent>
                  </Card>

                  {/* Members */}
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base flex items-center gap-2">
                        <Users className="w-4 h-4 text-muted-foreground" />
                        Members
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {selectedTeam.members.map((m) => (
                          <div key={m.id} className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm text-slate-800">{m.email}</span>
                              {m.role === "owner" && (
                                <Badge variant="secondary" className="bg-blue-100 text-blue-700 hover:bg-blue-100">
                                  <Crown className="w-3 h-3 mr-1" />
                                  Owner
                                </Badge>
                              )}
                              {!m.accepted && (
                                <Badge variant="secondary" className="bg-amber-100 text-amber-700 hover:bg-amber-100">
                                  <Clock className="w-3 h-3 mr-1" />
                                  Pending
                                </Badge>
                              )}
                            </div>
                            {isOwner && m.role !== "owner" && m.user_id && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleRemove(m.user_id!)}
                                className="text-red-500 hover:text-red-700 hover:bg-red-50 h-7"
                              >
                                <Trash2 className="w-3 h-3 mr-1" />
                                Remove
                              </Button>
                            )}
                          </div>
                        ))}
                      </div>

                      {/* Invite form */}
                      {isOwner && (
                        <form onSubmit={handleInvite} className="mt-4 flex gap-2">
                          <Input
                            type="email"
                            value={inviteEmail}
                            onChange={(e) => setInviteEmail(e.target.value)}
                            placeholder="teammate@company.com"
                            className="flex-1"
                          />
                          <Button
                            type="submit"
                            disabled={inviteLoading}
                            className="shrink-0"
                          >
                            {inviteLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <>
                                <UserPlus className="w-4 h-4 mr-1" />
                                Invite
                              </>
                            )}
                          </Button>
                        </form>
                      )}
                      {inviteError && <p className="text-xs text-red-600 mt-2">{inviteError}</p>}
                      {inviteSuccess && (
                        <p className="text-xs text-emerald-600 mt-2 flex items-center gap-1">
                          <CheckCircle className="w-3 h-3" />
                          Invitation sent!
                        </p>
                      )}
                    </CardContent>
                  </Card>

                  {/* Billing */}
                  {isOwner && (
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-base flex items-center gap-2">
                          <CreditCard className="w-4 h-4 text-muted-foreground" />
                          Team Billing
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        {selectedTeam.plan === "team" && (
                          <p className="text-sm text-muted-foreground mb-3">
                            $15/seat/month · {selectedTeam.members.filter((m) => m.accepted).length} active seat{selectedTeam.members.filter((m) => m.accepted).length !== 1 ? "s" : ""}
                          </p>
                        )}
                        <Button
                          onClick={async () => {
                            try {
                              const { url } = await createTeamCheckout(selectedTeam.id);
                              window.location.href = url;
                            } catch (err: unknown) {
                              if (err instanceof Error && err.message?.includes("already has an active subscription")) {
                                try {
                                  const { url } = await createPortalSession();
                                  window.location.href = url;
                                } catch {
                                  alert("Could not open billing portal.");
                                }
                              } else {
                                alert(err instanceof Error ? err.message : "Could not start checkout.");
                              }
                            }
                          }}
                        >
                          <CreditCard className="w-4 h-4 mr-1" />
                          Manage Billing
                        </Button>
                      </CardContent>
                    </Card>
                  )}

                  {/* Team analyses */}
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base flex items-center gap-2">
                        <BarChart3 className="w-4 h-4 text-muted-foreground" />
                        Team Analyses
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {analyses.length === 0 ? (
                        <p className="text-sm text-muted-foreground text-center py-4">
                          No team analyses yet. Analyze a repo and assign it to this team.
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {analyses.map((a) => (
                            <Link
                              key={a.id}
                              href={`/analysis/${a.id}`}
                              className="flex items-center justify-between p-3 border border-slate-100 rounded-xl hover:bg-slate-50 transition-colors"
                            >
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-slate-800">{a.repo_name}</span>
                                <Badge
                                  variant="secondary"
                                  className={
                                    a.status === "completed" ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-100" :
                                    a.status === "failed" ? "bg-red-100 text-red-700 hover:bg-red-100" :
                                    "bg-blue-100 text-blue-700 hover:bg-blue-100"
                                  }
                                >
                                  {a.status === "completed" && <CheckCircle className="w-3 h-3 mr-1" />}
                                  {a.status === "failed" && <XCircle className="w-3 h-3 mr-1" />}
                                  {a.status}
                                </Badge>
                              </div>
                              <span className="text-xs text-muted-foreground">
                                {new Date(a.created_at).toLocaleDateString()}
                              </span>
                            </Link>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </>
              ) : (
                <Card>
                  <CardContent className="py-10 text-center">
                    <Users className="w-10 h-10 mx-auto text-muted-foreground mb-3" />
                    <p className="text-lg font-semibold text-slate-900 mb-2">Create your first team</p>
                    <p className="text-sm text-muted-foreground mb-4">
                      Share analyses with your team. Everyone sees the same onboarding guides and health scores.
                    </p>
                    <Button onClick={() => setShowCreate(true)}>
                      <Plus className="w-4 h-4 mr-1" />
                      Create a team
                    </Button>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        </main>
      </div>
    </>
  );
}
