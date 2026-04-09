import { startGithubConnect } from "../lib/api";

interface Props {
  repoUrl: string;
  onDismiss: () => void;
}

export default function ConnectGitHubModal({ repoUrl, onDismiss }: Props) {
  async function handleConnect() {
    localStorage.setItem("hl_pending_url", repoUrl);
    const url = await startGithubConnect();
    window.location.href = url;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onDismiss(); }}
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <div className="text-4xl mb-3">🔒</div>
          <h2 className="text-xl font-bold text-slate-900 mb-2">
            Private repository
          </h2>
          <p className="text-sm text-slate-500 leading-relaxed">
            This looks like a private repo. Connect your GitHub account to give
            Hootly read-only access and analyze it.
          </p>
        </div>

        <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 mb-6">
          <p className="text-xs text-slate-400 mb-1">Repository</p>
          <p className="text-sm font-mono text-slate-700 break-all">{repoUrl}</p>
        </div>

        <button
          onClick={handleConnect}
          className="w-full flex items-center justify-center gap-2.5 bg-[#24292f] hover:bg-[#1b1f24] text-white font-semibold py-3 rounded-xl text-sm transition-colors mb-3"
        >
          <GitHubIcon />
          Connect GitHub
        </button>

        <button
          onClick={onDismiss}
          className="w-full text-sm text-slate-500 hover:text-slate-700 py-2 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function GitHubIcon() {
  return (
    <svg height="18" width="18" viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}
