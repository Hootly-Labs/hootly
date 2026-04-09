import { useEffect } from "react";
import { useRouter } from "next/router";

/**
 * Landing page for the GitHub connect (repo-access) OAuth callback.
 * The backend redirects here after storing the access token on the user.
 * We pick up any pending URL and redirect home (or to settings).
 */
export default function ConnectCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    const pendingUrl = localStorage.getItem("hl_pending_url");
    localStorage.removeItem("hl_pending_url");
    // Only allow GitHub HTTPS URLs to prevent open redirect via poisoned localStorage
    const isValidGithubUrl = (u: string) => {
      try { return new URL(u).hostname === "github.com"; } catch { return false; }
    };
    if (pendingUrl && isValidGithubUrl(pendingUrl)) {
      router.replace(`/dashboard?url=${encodeURIComponent(pendingUrl)}`);
    } else {
      // Full reload so AuthProvider re-fetches /me and picks up github_connected: true
      window.location.href = "/settings?connected=github";
    }
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="text-4xl mb-3">🔗</div>
        <p className="text-slate-500 text-sm">Connecting GitHub…</p>
      </div>
    </div>
  );
}
