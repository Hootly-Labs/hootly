import { useEffect } from "react";
import type { AppProps } from "next/app";
import Head from "next/head";
import "../styles/globals.css";
import { AuthProvider } from "../lib/AuthProvider";

export default function App({ Component, pageProps }: AppProps) {
  // Apply saved appearance preferences on every page load
  useEffect(() => {
    // Theme — default to light; respect explicit user preference if set
    const saved = localStorage.getItem("theme");
    const isDark = saved === "dark";
    document.documentElement.classList.toggle("dark", isDark);

    // Compact mode
    const compact = localStorage.getItem("hl_compact") === "1";
    document.documentElement.dataset.compact = compact ? "1" : "0";

    // Code font
    const codeFont = localStorage.getItem("hl_code_font") || "mono";
    document.documentElement.dataset.codeFont = codeFont;
  }, []);

  return (
    <AuthProvider>
      <Head>
        <link rel="icon" type="image/png" href="/favicon.png" />
        <link rel="apple-touch-icon" href="/favicon.png" />
        <meta name="description" content="Hootly — instant codebase onboarding. Paste a GitHub repo and get an interactive architecture overview, key files, dependency graph, and reading order." />
        <meta property="og:site_name" content="Hootly" />
        <meta property="og:description" content="Instant codebase onboarding. Paste a GitHub repo and get an interactive architecture overview, key files, and onboarding guide." />
        <meta property="og:image" content="https://www.hootlylabs.com/favicon.png" />
        <meta name="twitter:card" content="summary" />
        <meta name="twitter:image" content="https://www.hootlylabs.com/favicon.png" />
      </Head>
      <Component {...pageProps} />
    </AuthProvider>
  );
}
