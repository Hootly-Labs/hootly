import { useEffect } from "react";
import { useRouter } from "next/router";
import { exchangeOAuthCode } from "../../lib/api";
import OwlLogo from "../../components/OwlLogo";

/**
 * Landing page for GitHub OAuth callback.
 * The backend redirects here as: /auth/callback?code=<opaque_code>
 * We exchange the one-time code for a JWT, store it, then redirect home.
 */
export default function AuthCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    if (!router.isReady) return;

    const { error, code } = router.query;

    if (error) {
      router.replace(`/login?error=${error}`);
      return;
    }

    if (!code || typeof code !== "string") return;

    exchangeOAuthCode(code)
      .then(({ token }) => {
        localStorage.setItem("hl_token", token);
        window.location.href = "/";
      })
      .catch(() => {
        router.replace("/login?error=oauth_failed");
      });
  }, [router.isReady, router.query]);

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="mb-3 flex justify-center"><OwlLogo size={48} /></div>
        <p className="text-slate-500 text-sm">Signing you in…</p>
      </div>
    </div>
  );
}
