import { useState, useEffect } from "react";
import { useRouter } from "next/router";
import Head from "next/head";
import Link from "next/link";
import { useRequireAuth } from "../../lib/auth";
import { acceptTeamInvite, getTeam, type Team } from "../../lib/api";
import OwlLogo from "../../components/OwlLogo";

export default function AcceptInvitePage() {
  const router = useRouter();
  const { user, loading: authLoading } = useRequireAuth();
  const { team_id } = router.query;

  const [team, setTeam] = useState<Team | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "accepting" | "accepted" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user || !team_id || typeof team_id !== "string") return;
    getTeam(team_id)
      .then((t) => {
        setTeam(t);
        setStatus("ready");
      })
      .catch(() => {
        setError("Team not found or you don't have access.");
        setStatus("error");
      });
  }, [user, team_id]);

  async function handleAccept() {
    if (!team_id || typeof team_id !== "string") return;
    setStatus("accepting");
    setError("");
    try {
      await acceptTeamInvite(team_id);
      setStatus("accepted");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to accept invitation.");
      setStatus("error");
    }
  }

  if (authLoading) return null;

  return (
    <>
      <Head>
        <title>Team Invitation — Hootly</title>
      </Head>
      <div className="min-h-screen bg-slate-50">
        <header className="bg-white border-b border-slate-200">
          <div className="max-w-5xl mx-auto px-4 sm:px-6 h-24 flex items-center justify-between">
            <Link href="/dashboard" className="flex items-center gap-2">
              <OwlLogo size={90} />
            </Link>
          </div>
        </header>

        <main className="max-w-md mx-auto px-4 py-20">
          {status === "loading" && (
            <div className="bg-white border border-slate-200 rounded-2xl p-10 text-center shadow-sm">
              <p className="text-slate-500">Loading invitation...</p>
            </div>
          )}

          {status === "ready" && team && (
            <div className="bg-white border border-slate-200 rounded-2xl p-10 text-center shadow-sm">
              <div className="w-14 h-14 rounded-2xl bg-blue-50 flex items-center justify-center text-2xl mx-auto mb-4">
                👥
              </div>
              <h1 className="text-xl font-bold text-slate-900 mb-2">
                You're invited to join
              </h1>
              <p className="text-2xl font-bold text-blue-600 mb-2">{team.name}</p>
              <p className="text-sm text-slate-500 mb-6">
                {team.members.length} member{team.members.length !== 1 ? "s" : ""} · {team.analysis_count} analyses
              </p>
              <button
                onClick={handleAccept}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 rounded-xl transition-colors"
              >
                Accept Invitation
              </button>
              <Link
                href="/dashboard"
                className="block mt-3 text-sm text-slate-500 hover:text-slate-700"
              >
                Decline and go to dashboard
              </Link>
            </div>
          )}

          {status === "accepting" && (
            <div className="bg-white border border-slate-200 rounded-2xl p-10 text-center shadow-sm">
              <p className="text-slate-500">Accepting invitation...</p>
            </div>
          )}

          {status === "accepted" && (
            <div className="bg-white border border-slate-200 rounded-2xl p-10 text-center shadow-sm">
              <div className="w-14 h-14 rounded-2xl bg-emerald-50 flex items-center justify-center text-2xl mx-auto mb-4">
                ✓
              </div>
              <h1 className="text-xl font-bold text-slate-900 mb-2">
                You're in!
              </h1>
              <p className="text-sm text-slate-500 mb-6">
                You've joined <strong>{team?.name}</strong>. You can now view shared analyses.
              </p>
              <Link
                href="/team"
                className="inline-block bg-blue-600 hover:bg-blue-700 text-white font-semibold px-6 py-3 rounded-xl transition-colors"
              >
                Go to Team Dashboard
              </Link>
            </div>
          )}

          {status === "error" && (
            <div className="bg-white border border-slate-200 rounded-2xl p-10 text-center shadow-sm">
              <div className="w-14 h-14 rounded-2xl bg-red-50 flex items-center justify-center text-2xl mx-auto mb-4">
                !
              </div>
              <h1 className="text-xl font-bold text-slate-900 mb-2">
                Something went wrong
              </h1>
              <p className="text-sm text-red-600 mb-6">{error}</p>
              <div className="flex gap-3 justify-center">
                {team && (
                  <button
                    onClick={handleAccept}
                    className="bg-blue-600 hover:bg-blue-700 text-white font-semibold px-6 py-3 rounded-xl transition-colors"
                  >
                    Try Again
                  </button>
                )}
                <Link
                  href="/dashboard"
                  className="inline-block border border-slate-300 text-slate-700 font-semibold px-6 py-3 rounded-xl hover:bg-slate-50 transition-colors"
                >
                  Go to Dashboard
                </Link>
              </div>
            </div>
          )}
        </main>
      </div>
    </>
  );
}
