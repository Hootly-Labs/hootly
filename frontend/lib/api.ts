const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Extract a human-readable message from an unknown caught value. */
export function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === "string") return err;
  return "Something went wrong";
}

export interface KeyFile {
  path: string;
  score: number;
  reason: string;
  explanation: string;
  key_exports: string[];
}

export interface ReadingStep {
  step: number;
  path: string;
  reason: string;
}

export interface Dependencies {
  runtime: string[];
  dev: string[];
}

export interface Architecture {
  project_name: string;
  description: string;
  tech_stack: string[];
  architecture_type: string;
  architecture_summary: string;
  entry_points: string[];
  key_directories: { path: string; purpose: string }[];
  languages: string[];
  runtime: string;
  license: string;
}

export interface GraphNode {
  id: string;
  label: string;
  language: string;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Pattern {
  name: string;
  explanation: string;
}

export interface AnalysisResult {
  repo_name: string;
  architecture: Architecture;
  key_files: KeyFile[];
  reading_order: ReadingStep[];
  dependencies: Dependencies;
  quick_start: string;
  onboarding_guide: string;
  key_concepts: string[];
  patterns?: Pattern[];
  test_files?: string[];
  file_tree: string[];
  dependency_graph?: GraphData;
}

export interface Changelog {
  summary: string;
  new_files: string[];
  removed_files: string[];
  architecture_changes: string[];
  dependency_changes: { added: string[]; removed: string[] };
  highlights: string[];
}

export interface HealthDimension {
  score: number;
  label: string;
}

export interface HealthScore {
  overall_score: number;
  grade: string;
  dimensions: Record<string, HealthDimension>;
}

export interface Analysis {
  id: string;
  repo_url: string;
  repo_name: string;
  status: "pending" | "cloning" | "analyzing" | "completed" | "failed";
  stage: string;
  created_at: string;
  commit_hash?: string;
  from_cache?: boolean;
  is_starred?: boolean;
  is_public?: boolean;
  error_message?: string;
  result?: AnalysisResult;
  changelog?: Changelog;
  health_score?: HealthScore;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface AuthUser {
  id: string;
  email: string;
  plan: "free" | "pro";
  is_admin: boolean;
  is_verified: boolean;
  github_connected: boolean;
  github_username: string | null;
}

export interface AdminStats {
  total_users: number;
  free_users: number;
  pro_users: number;
  total_analyses: number;
  completed_analyses: number;
  recent_signups_30d: number;
  analyses_today: number;
}

export interface AdminUser {
  id: string;
  email: string;
  plan: "free" | "pro";
  is_admin: boolean;
  is_verified: boolean;
  created_at: string;
  last_login: string | null;
  analysis_count: number;
  analyses_this_month: number;
}

export interface DailyAnalysisStat { date: string; total: number; completed: number; failed: number; }
export interface DailySignupStat { date: string; signups: number; }
export interface AdminCharts { daily_analyses: DailyAnalysisStat[]; daily_signups: DailySignupStat[]; }

// ── Centralized fetch wrapper — injects auth token + auto-refresh ──────────────
let _refreshPromise: Promise<string | null> | null = null;

async function _tryRefresh(): Promise<string | null> {
  try {
    const res = await fetch(`${API}/api/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) return null;
    const data = await res.json();
    if (data.token) {
      localStorage.setItem("hl_token", data.token);
      return data.token;
    }
    return null;
  } catch {
    return null;
  }
}

async function apiFetch(path: string, options?: RequestInit): Promise<Response> {
  const token = typeof window !== "undefined" ? localStorage.getItem("hl_token") : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API}${path}`, { ...options, headers, credentials: "include" });

  // Auto-refresh on 401
  if (res.status === 401 && typeof window !== "undefined") {
    // Deduplicate concurrent refresh attempts
    if (!_refreshPromise) {
      _refreshPromise = _tryRefresh().finally(() => { _refreshPromise = null; });
    }
    const newToken = await _refreshPromise;
    if (newToken) {
      const retryHeaders: Record<string, string> = {
        "Content-Type": "application/json",
        Authorization: `Bearer ${newToken}`,
      };
      return fetch(`${API}${path}`, { ...options, headers: retryHeaders, credentials: "include" });
    }
  }

  return res;
}

// ── Analysis endpoints ────────────────────────────────────────────────────────
export async function getAnalysis(id: string): Promise<Analysis> {
  const res = await apiFetch(`/api/analysis/${id}`);
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error("Analysis not found");
  return res.json();
}

export async function startAnalysis(repoUrl: string, force = false): Promise<Analysis> {
  const res = await apiFetch("/api/analyze", {
    method: "POST",
    body: JSON.stringify({ repo_url: repoUrl, force }),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(err.detail || "Failed to start analysis");
  }
  return res.json();
}

export async function getRecentAnalyses(): Promise<Analysis[]> {
  const res = await apiFetch("/api/analyses");
  if (!res.ok) return [];
  return res.json();
}

// ── Auth endpoints ────────────────────────────────────────────────────────────
export async function register(email: string, password: string, turnstile_token?: string): Promise<{ token: string; user: AuthUser }> {
  const res = await fetch(`${API}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password, turnstile_token }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Registration failed" }));
    throw new Error(err.detail || "Registration failed");
  }
  return res.json();
}

export async function login(email: string, password: string): Promise<{ token: string; user: AuthUser }> {
  const res = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(err.detail || "Login failed");
  }
  return res.json();
}

export async function getMe(): Promise<AuthUser> {
  const res = await apiFetch("/api/auth/me");
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
}

// ── Admin endpoints ───────────────────────────────────────────────────────────
export async function getAdminStats(): Promise<AdminStats> {
  const res = await apiFetch("/api/admin/stats");
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || "Failed to fetch stats");
  }
  return res.json();
}

export async function getAdminUsers(): Promise<AdminUser[]> {
  const res = await apiFetch("/api/admin/users");
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || "Failed to fetch users");
  }
  return res.json();
}

export async function patchUserPlan(userId: string, plan: "free" | "pro"): Promise<void> {
  const res = await apiFetch(`/api/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ plan }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || "Failed to update user");
  }
}

export async function getAdminCharts(): Promise<AdminCharts> {
  const res = await apiFetch("/api/admin/charts");
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || "Failed to fetch chart data");
  }
  return res.json();
}

export interface UserStats {
  total_analyses: number;
  completed_analyses: number;
  starred_count: number;
  analyses_this_month: number;
  monthly_limit: number | null;
  daily_analyses: DailyAnalysisStat[];
  top_repos: { repo_name: string; count: number; last_analyzed_at: string }[];
}

export async function getUserStats(): Promise<UserStats> {
  const res = await apiFetch("/api/user/stats");
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
    throw new Error(err.detail || "Failed to fetch stats");
  }
  return res.json();
}

export async function deleteAdminUser(userId: string): Promise<void> {
  const res = await apiFetch(`/api/admin/users/${userId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to delete user" }));
    throw new Error(err.detail || "Failed to delete user");
  }
}

export async function patchUserAdmin(userId: string, is_admin: boolean): Promise<void> {
  const res = await apiFetch(`/api/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ is_admin }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to update user" }));
    throw new Error(err.detail || "Failed to update user");
  }
}

// ── Password reset ────────────────────────────────────────────────────────────
export async function verifyEmail(code: string): Promise<void> {
  const res = await apiFetch("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Verification failed" }));
    throw new Error(err.detail || "Verification failed");
  }
}

export async function resendVerification(): Promise<void> {
  const res = await apiFetch("/api/auth/resend-verification", { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to resend" }));
    throw new Error(err.detail || "Failed to resend");
  }
}

export async function forgotPassword(email: string): Promise<void> {
  await apiFetch("/api/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const res = await apiFetch("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Reset failed" }));
    throw new Error(err.detail || "Reset failed");
  }
}

// ── Billing endpoints ─────────────────────────────────────────────────────────
export async function getBillingUsage(): Promise<{ analyses_this_month: number; limit: number | null; plan: string }> {
  const res = await apiFetch("/api/billing/usage");
  if (!res.ok) throw new Error("Failed to fetch usage");
  return res.json();
}

export async function createCheckoutSession(): Promise<{ url: string }> {
  const res = await apiFetch("/api/billing/checkout", { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Checkout failed" }));
    throw new Error(err.detail || "Checkout failed");
  }
  return res.json();
}

// ── Settings endpoints ────────────────────────────────────────────────────────
export async function getSettings(): Promise<{ notify_on_complete: boolean }> {
  const res = await apiFetch("/api/auth/settings");
  if (!res.ok) throw new Error("Failed to fetch settings");
  return res.json();
}

export async function updateSettings(notify_on_complete: boolean): Promise<void> {
  const res = await apiFetch("/api/auth/settings", {
    method: "PATCH",
    body: JSON.stringify({ notify_on_complete }),
  });
  if (!res.ok) throw new Error("Failed to update settings");
}

export async function changePassword(old_password: string, new_password: string): Promise<void> {
  const res = await apiFetch("/api/auth/change-password", {
    method: "PATCH",
    body: JSON.stringify({ old_password, new_password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to change password" }));
    throw new Error(err.detail || "Failed to change password");
  }
}

export async function deleteAccount(): Promise<void> {
  const res = await apiFetch("/api/auth/account", { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete account");
}

// ── Analysis actions ──────────────────────────────────────────────────────────
export async function toggleStar(id: string): Promise<{ is_starred: boolean }> {
  const res = await apiFetch(`/api/analysis/${id}/star`, { method: "PATCH" });
  if (!res.ok) throw new Error("Failed to toggle star");
  return res.json();
}

export async function toggleVisibility(id: string): Promise<{ is_public: boolean }> {
  const res = await apiFetch(`/api/analysis/${id}/visibility`, { method: "PATCH" });
  if (!res.ok) throw new Error("Failed to toggle visibility");
  return res.json();
}

// ── Watch endpoints ───────────────────────────────────────────────────────────
export interface WatchedRepo {
  id: string;
  repo_url: string;
  repo_name: string;
  last_commit_hash?: string;
  last_checked_at?: string;
  last_changed_at?: string;
  created_at: string;
}

export async function getWatches(): Promise<WatchedRepo[]> {
  const res = await apiFetch("/api/watches");
  if (!res.ok) return [];
  return res.json();
}

export async function watchRepo(repo_url: string): Promise<WatchedRepo> {
  const res = await apiFetch("/api/watch", {
    method: "POST",
    body: JSON.stringify({ repo_url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to watch repo" }));
    throw new Error(err.detail || "Failed to watch repo");
  }
  return res.json();
}

export async function unwatchRepo(id: string): Promise<void> {
  const res = await apiFetch(`/api/watch/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to unwatch repo");
}

export async function getPublicAnalysis(id: string): Promise<Analysis> {
  const res = await fetch(`${API}/api/public/analysis/${id}`);
  if (!res.ok) throw new Error("Analysis not found or not public");
  return res.json();
}

export function getGithubAuthUrl(): string {
  return `${API}/api/auth/github`;
}

export async function startGithubConnect(): Promise<string> {
  const res = await apiFetch("/api/auth/github/connect", { method: "POST" });
  if (!res.ok) throw new Error("Failed to start GitHub connect");
  const data = await res.json();
  return data.url;
}

export async function disconnectGithub(): Promise<void> {
  const res = await apiFetch("/api/auth/github/token", { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to disconnect GitHub");
}

export async function exchangeOAuthCode(code: string): Promise<{ token: string; user: AuthUser }> {
  const res = await fetch(`${API}/api/auth/github/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error("OAuth code exchange failed");
  return res.json();
}

export async function createPortalSession(): Promise<{ url: string }> {
  const res = await apiFetch("/api/billing/portal", { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Portal failed" }));
    throw new Error(err.detail || "Portal failed");
  }
  return res.json();
}

export interface GithubRepo {
  name: string;
  full_name: string;
  private: boolean;
  description: string;
  updated_at: string;
  html_url: string;
  language: string;
  github_starred: boolean;
}

export async function getGithubRepos(page = 1): Promise<GithubRepo[]> {
  const res = await apiFetch(`/api/github/repos?page=${page}`);
  if (!res.ok) return [];
  return res.json();
}

// ── API Key endpoints ────────────────────────────────────────────────────────
export interface ApiKeyInfo {
  id: string;
  prefix: string;
  name: string;
  last_used: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKeyInfo {
  key: string; // only returned once
}

export async function createApiKey(name: string): Promise<ApiKeyCreated> {
  const res = await apiFetch("/api/auth/api-keys", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create API key" }));
    throw new Error(err.detail || "Failed to create API key");
  }
  return res.json();
}

export async function listApiKeys(): Promise<ApiKeyInfo[]> {
  const res = await apiFetch("/api/auth/api-keys");
  if (!res.ok) return [];
  return res.json();
}

export async function revokeApiKey(keyId: string): Promise<void> {
  const res = await apiFetch(`/api/auth/api-keys/${keyId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to revoke API key" }));
    throw new Error(err.detail || "Failed to revoke API key");
  }
}

// ── Chat endpoints ───────────────────────────────────────────────────────────
export async function getChatHistory(analysisId: string): Promise<ChatMessage[]> {
  const res = await apiFetch(`/api/analysis/${analysisId}/chat`);
  if (!res.ok) return [];
  return res.json();
}

export async function sendChatMessage(
  analysisId: string,
  message: string,
  onDelta: (text: string) => void,
  onDone: (fullText: string) => void,
  onError: (error: string) => void,
): Promise<void> {
  const token = typeof window !== "undefined" ? localStorage.getItem("hl_token") : null;
  const res = await fetch(`${API}/api/analysis/${analysisId}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    credentials: "include",
    body: JSON.stringify({ message }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Chat failed" }));
    onError(err.detail || "Chat failed");
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    onError("No response stream");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const data = JSON.parse(line.slice(6));
        if (data.type === "delta") {
          onDelta(data.text);
        } else if (data.type === "done") {
          onDone(data.full_text);
        }
      } catch {}
    }
  }
}

// ── Assessment endpoints ─────────────────────────────────────────────────────
export interface AssessmentResult {
  id: string;
  status: string;
  tier: string;
  result?: {
    executive_summary: string;
    health_assessment: {
      executive_summary: string;
      strengths: string[];
      risks: string[];
      overall_assessment: string;
    };
    tech_debt: {
      debt_items: {
        category: string;
        severity: string;
        description: string;
        recommendation: string;
        effort: string;
      }[];
      debt_score: number;
      summary: string;
    };
    security_analysis?: {
      risk_level: string;
      attack_surface: {
        area: string;
        risk: string;
        description: string;
        mitigation: string;
      }[];
      dependency_risks: string[];
      summary: string;
    };
    recommendations: {
      priority: string;
      source: string;
      recommendation: string;
    }[];
    health_score: Record<string, unknown>;
  };
  created_at?: string;
}

export async function getAssessment(analysisId: string): Promise<AssessmentResult> {
  const res = await apiFetch(`/api/assessment/${analysisId}`);
  if (!res.ok) throw new Error("Failed to fetch assessment");
  return res.json();
}

export async function createAssessment(analysisId: string, tier: string = "basic"): Promise<AssessmentResult> {
  const res = await apiFetch(`/api/assessment/${analysisId}`, {
    method: "POST",
    body: JSON.stringify({ tier }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Assessment failed" }));
    throw new Error(err.detail || "Assessment failed");
  }
  return res.json();
}

export async function createAssessmentCheckout(analysisId: string, tier: string = "basic"): Promise<{ url: string }> {
  const res = await apiFetch(`/api/assessment/${analysisId}/checkout`, {
    method: "POST",
    body: JSON.stringify({ tier }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Checkout failed" }));
    throw new Error(err.detail || "Checkout failed");
  }
  return res.json();
}

// ── Repo lookup (public) ─────────────────────────────────────────────────────
export async function getRepoAnalysis(owner: string, repo: string): Promise<Analysis | null> {
  const res = await fetch(`${API}/api/repo/${owner}/${repo}`);
  if (!res.ok) return null;
  return res.json();
}

// ── Team endpoints ──────────────────────────────────────────────────────────
export interface TeamMember {
  id: string;
  user_id: string | null;
  email: string;
  role: "owner" | "member";
  accepted: boolean;
}

export interface Team {
  id: string;
  name: string;
  owner_id: string;
  plan: string;
  members: TeamMember[];
  analysis_count: number;
  created_at: string;
}

export async function createTeam(name: string): Promise<Team> {
  const res = await apiFetch("/api/teams", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create team" }));
    throw new Error(err.detail || "Failed to create team");
  }
  return res.json();
}

export async function listTeams(): Promise<Team[]> {
  const res = await apiFetch("/api/teams");
  if (!res.ok) return [];
  return res.json();
}

export async function getTeam(teamId: string): Promise<Team> {
  const res = await apiFetch(`/api/teams/${teamId}`);
  if (!res.ok) throw new Error("Team not found");
  return res.json();
}

export async function inviteTeamMember(teamId: string, email: string): Promise<void> {
  const res = await apiFetch(`/api/teams/${teamId}/invite`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to invite" }));
    throw new Error(err.detail || "Failed to invite");
  }
}

export async function acceptTeamInvite(teamId: string): Promise<void> {
  const res = await apiFetch(`/api/teams/${teamId}/accept`, { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to accept invite" }));
    throw new Error(err.detail || "Failed to accept invite");
  }
}

export async function removeTeamMember(teamId: string, userId: string): Promise<void> {
  const res = await apiFetch(`/api/teams/${teamId}/members/${userId}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to remove member" }));
    throw new Error(err.detail || "Failed to remove member");
  }
}

export async function createTeamCheckout(teamId: string): Promise<{ url: string }> {
  const res = await apiFetch("/api/billing/team-checkout", {
    method: "POST",
    body: JSON.stringify({ team_id: teamId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Checkout failed" }));
    throw new Error(err.detail || "Checkout failed");
  }
  return res.json();
}

export async function getTeamAnalyses(teamId: string): Promise<Analysis[]> {
  const res = await apiFetch(`/api/teams/${teamId}/analyses`);
  if (!res.ok) return [];
  return res.json();
}

// ── Feature 1: Drift Alerts ────────────────────────────────────────────────

export interface DriftAlert {
  id: string;
  repo_url: string;
  alert_type: string;
  severity: "info" | "warning" | "critical";
  message: string;
  details: Record<string, unknown>;
  created_at: string;
  read: boolean;
  dismissed: boolean;
}

export interface RepoSnapshotSummary {
  id: string;
  analysis_id: string;
  commit_hash: string | null;
  snapshot_date: string;
  file_count: number;
  health_score: HealthScore | null;
  tech_stack: string[];
}

export async function getAlerts(read?: boolean, dismissed?: boolean, limit?: number, offset?: number): Promise<DriftAlert[]> {
  const params = new URLSearchParams();
  if (read !== undefined) params.set("read", String(read));
  if (dismissed !== undefined) params.set("dismissed", String(dismissed));
  if (limit !== undefined) params.set("limit", String(limit));
  if (offset !== undefined) params.set("offset", String(offset));
  const res = await apiFetch(`/api/alerts?${params}`);
  if (!res.ok) return [];
  return res.json();
}

export async function markAlertRead(alertId: string): Promise<void> {
  await apiFetch(`/api/alerts/${alertId}`, { method: "PATCH", body: JSON.stringify({ read: true }) });
}

export async function dismissAlert(alertId: string): Promise<void> {
  await apiFetch(`/api/alerts/${alertId}`, { method: "PATCH", body: JSON.stringify({ dismissed: true }) });
}

export async function getAnalysisHistory(analysisId: string): Promise<RepoSnapshotSummary[]> {
  const res = await apiFetch(`/api/analysis/${analysisId}/history`);
  if (!res.ok) return [];
  return res.json();
}

// ── Feature 2: Impact Analysis ─────────────────────────────────────────────

export interface ImpactResult {
  file_path: string;
  explanation: string;
  score: number;
  imports: string[];
  imported_by: string[];
  transitive_dependents: string[];
  total_impact_radius: number;
}

export interface FlowResult {
  from_file: string;
  to_file: string;
  connected: boolean;
  path: string[];
  path_details: { path: string; explanation: string; key_exports: string[]; has_content: boolean }[];
  hop_count: number;
}

export async function getImpact(analysisId: string, filePath: string): Promise<ImpactResult> {
  const res = await apiFetch(`/api/analysis/${analysisId}/impact`, {
    method: "POST",
    body: JSON.stringify({ file_path: filePath }),
  });
  return res.json();
}

export async function explainFlow(analysisId: string, fromFile: string, toFile: string): Promise<FlowResult> {
  const res = await apiFetch(`/api/analysis/${analysisId}/explain-flow`, {
    method: "POST",
    body: JSON.stringify({ from_file: fromFile, to_file: toFile }),
  });
  return res.json();
}

// ── Feature 3: Benchmarking ────────────────────────────────────────────────

export interface BenchmarkDimensionComparison {
  score: number;
  percentile: number;
  label: string;
}

export interface BenchmarkReport {
  category: string;
  category_label?: string;
  has_benchmark: boolean;
  message?: string;
  sample_size?: number;
  overall_percentile?: number;
  overall_score?: number;
  median_score?: number;
  dimensions?: Record<string, BenchmarkDimensionComparison>;
  callouts?: string[];
}

export async function getBenchmark(analysisId: string): Promise<BenchmarkReport> {
  const res = await apiFetch(`/api/analysis/${analysisId}/benchmark`);
  return res.json();
}

// ── Feature 4: Tribal Knowledge ────────────────────────────────────────────

export interface AnnotationData {
  id: string;
  analysis_id: string;
  user_id: string;
  file_path: string;
  content: string;
  annotation_type: string;
  line_start: number | null;
  line_end: number | null;
  created_at: string;
  updated_at: string | null;
}

export interface ADR {
  id: string;
  user_id: string;
  repo_url: string;
  title: string;
  status: string;
  context: string;
  decision: string;
  consequences: string;
  team_id: string | null;
  created_at: string;
  updated_at: string | null;
  superseded_by: string | null;
}

export interface ExpertiseEntry {
  id: string;
  user_id: string;
  repo_url: string;
  file_path: string;
  expertise_level: string;
  auto_detected: boolean;
  last_touched_at: string | null;
}

export async function getAnnotations(analysisId: string, filePath?: string): Promise<AnnotationData[]> {
  const params = filePath ? `?file_path=${encodeURIComponent(filePath)}` : "";
  const res = await apiFetch(`/api/analysis/${analysisId}/annotations${params}`);
  if (!res.ok) return [];
  return res.json();
}

export async function createAnnotation(analysisId: string, data: {
  file_path: string; content: string; annotation_type?: string;
  line_start?: number; line_end?: number;
}): Promise<AnnotationData> {
  const res = await apiFetch(`/api/analysis/${analysisId}/annotations`, {
    method: "POST",
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function deleteAnnotation(annotationId: string): Promise<void> {
  await apiFetch(`/api/annotations/${annotationId}`, { method: "DELETE" });
}

export async function getADRs(repoUrl?: string, teamId?: string): Promise<ADR[]> {
  const params = new URLSearchParams();
  if (repoUrl) params.set("repo_url", repoUrl);
  if (teamId) params.set("team_id", teamId);
  const res = await apiFetch(`/api/adrs?${params}`);
  if (!res.ok) return [];
  return res.json();
}

export async function createADR(data: {
  repo_url: string; title: string; context: string;
  decision: string; consequences: string; team_id?: string;
}): Promise<ADR> {
  const res = await apiFetch("/api/adrs", {
    method: "POST",
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function deleteADR(adrId: string): Promise<void> {
  await apiFetch(`/api/adrs/${adrId}`, { method: "DELETE" });
}

export async function getExpertise(analysisId: string): Promise<ExpertiseEntry[]> {
  const res = await apiFetch(`/api/analysis/${analysisId}/expertise`);
  if (!res.ok) return [];
  return res.json();
}

export async function setExpertise(analysisId: string, filePath: string, level: string): Promise<ExpertiseEntry> {
  const res = await apiFetch(`/api/analysis/${analysisId}/expertise`, {
    method: "POST",
    body: JSON.stringify({ file_path: filePath, expertise_level: level }),
  });
  return res.json();
}

// ── Feature 5: Multi-Repo Intelligence ─────────────────────────────────────

export interface OrgHealthRepo {
  repo_url: string;
  repo_name: string;
  overall_score: number;
  grade: string;
  dimensions: Record<string, HealthDimension>;
  last_analyzed: string;
}

export interface OrgHealthDashboard {
  repos: OrgHealthRepo[];
  summary: { total_repos: number; avg_score: number; at_risk_count: number };
}

export interface CrossRepoDep {
  id: string;
  source_repo_url: string;
  target_repo_url: string;
  dependency_type: string;
  dependency_name: string;
  source_version: string | null;
  target_version: string | null;
}

export interface SharedPatterns {
  tech_stack: Record<string, number>;
  languages: Record<string, number>;
  patterns: { name: string; count: number }[];
  total_repos: number;
}

export async function getOrgHealth(teamId: string): Promise<OrgHealthDashboard> {
  const res = await apiFetch(`/api/teams/${teamId}/org-health`);
  return res.json();
}

export async function getCrossRepoDeps(teamId: string): Promise<CrossRepoDep[]> {
  const res = await apiFetch(`/api/teams/${teamId}/cross-deps`);
  if (!res.ok) return [];
  return res.json();
}

export async function getSharedPatterns(teamId: string): Promise<SharedPatterns> {
  const res = await apiFetch(`/api/teams/${teamId}/patterns`);
  return res.json();
}

// ── Feature 6: Slack ───────────────────────────────────────────────────────

export async function getSlackStatus(teamId: string): Promise<{ connected: boolean; channel_id: string | null }> {
  const res = await apiFetch(`/api/slack/status?team_id=${teamId}`);
  return res.json();
}

export function getSlackInstallUrl(teamId: string): string {
  return `${API}/api/slack/install?team_id=${teamId}`;
}
