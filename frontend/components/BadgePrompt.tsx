import { useState, useEffect } from "react";

interface BadgePromptProps {
  analysisId: string;
  owner: string;
  repo: string;
  healthGrade?: string;
}

export default function BadgePrompt({ analysisId, owner, repo, healthGrade }: BadgePromptProps) {
  const [dismissed, setDismissed] = useState(true); // default hidden until check
  const [copied, setCopied] = useState(false);

  const storageKey = `badge-dismissed-${analysisId}`;
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const badgeUrl = `${apiUrl}/api/badge/${owner}/${repo}`;
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "https://www.hootlylabs.com";
  const badgeMarkdown = `[![Hootly](${badgeUrl})](${siteUrl}/repo/${owner}/${repo})`;

  useEffect(() => {
    const wasDismissed = localStorage.getItem(storageKey);
    setDismissed(!!wasDismissed);
  }, [storageKey]);

  if (dismissed) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(badgeMarkdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  const handleDismiss = () => {
    localStorage.setItem(storageKey, "1");
    setDismissed(true);
  };

  return (
    <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-xl p-4 mb-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <img src={badgeUrl} alt={`Hootly ${healthGrade || ""}`} className="h-5" />
            <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
              Add a health badge to your README
            </p>
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-1.5 text-xs text-slate-600 dark:text-slate-400 truncate">
              {badgeMarkdown}
            </code>
            <button
              onClick={handleCopy}
              className="shrink-0 text-xs font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 px-2 py-1.5 rounded-lg border border-blue-200 dark:border-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
        </div>
        <button
          onClick={handleDismiss}
          className="shrink-0 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors p-1"
          title="Dismiss"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
