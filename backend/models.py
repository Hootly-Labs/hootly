import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Index, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from database import Base, _is_sqlite

# Conditional pgvector import — only available with PostgreSQL
try:
    from pgvector.sqlalchemy import Vector as _Vector
    _has_pgvector = not _is_sqlite
except ImportError:
    _Vector = None
    _has_pgvector = False

# Valid non-failed analysis statuses used for monthly usage counting.
# "running" was an old placeholder that never existed as a real status.
ACTIVE_ANALYSIS_STATUSES = ("pending", "cloning", "analyzing", "completed")


def _utcnow() -> datetime:
    """Return current UTC time as a naive datetime (for consistent DB storage).

    Replaces the deprecated datetime.utcnow() — stores naive UTC so all
    comparisons against DB timestamps remain timezone-free and consistent.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, default="free")  # "free" | "pro"
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)
    github_id: Mapped[str | None] = mapped_column(String, nullable=True)
    github_access_token: Mapped[str | None] = mapped_column(String, nullable=True)
    github_username: Mapped[str | None] = mapped_column(String, nullable=True)
    notify_on_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_code: Mapped[str | None] = mapped_column(String, nullable=True)
    verification_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    signup_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    token_invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_country: Mapped[str | None] = mapped_column(String, nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String, nullable=True)


class PasswordHistory(Base):
    __tablename__ = "password_history"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class WatchedRepo(Base):
    __tablename__ = "watched_repos"
    __table_args__ = (UniqueConstraint("user_id", "repo_url", name="uq_watched_repos_user_repo"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    repo_url: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    last_commit_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_user_created", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    repo_url: Mapped[str] = mapped_column(String, nullable=False, index=True)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | cloning | analyzing | completed | failed
    stage: Mapped[str] = mapped_column(String, default="")  # human-readable progress message
    commit_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # HEAD commit hash at analysis time
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string, set when auto-triggered by watch
    health_score: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    team_id: Mapped[str | None] = mapped_column(String, ForeignKey("teams.id"), nullable=True, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String, ForeignKey("analyses.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class GitHubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    installation_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    account_login: Mapped[str] = mapped_column(String, nullable=False)
    account_type: Mapped[str] = mapped_column(String, nullable=False)  # "User" | "Organization"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String, nullable=False)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)
    plan: Mapped[str] = mapped_column(String, default="team")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String, default="member")  # "owner" | "member"
    invited_email: Mapped[str | None] = mapped_column(String, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    prefix: Mapped[str] = mapped_column(String(8), nullable=False)  # first 8 chars for identification
    name: Mapped[str] = mapped_column(String, nullable=False)  # user-given label
    last_used: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String, ForeignKey("analyses.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String, nullable=False)  # "basic" | "full"
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | processing | completed | failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── Feature 1: Continuous Repo Intelligence ──────────────────────────────────

class RepoSnapshot(Base):
    __tablename__ = "repo_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String, ForeignKey("analyses.id"), nullable=False, index=True)
    repo_url: Mapped[str] = mapped_column(String, nullable=False, index=True)
    commit_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    architecture_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    tech_stack: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    entry_points: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    key_files: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON


class DriftAlert(Base):
    __tablename__ = "drift_alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    repo_url: Mapped[str] = mapped_column(String, nullable=False)
    alert_type: Mapped[str] = mapped_column(String, nullable=False)  # new_dependency | removed_entry_point | health_drop | architecture_change | tech_stack_change
    severity: Mapped[str] = mapped_column(String, default="info")  # info | warning | critical
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)


# ── Feature 3: Benchmarking ──────────────────────────────────────────────────

class RepoBenchmark(Base):
    __tablename__ = "repo_benchmarks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    language: Mapped[str] = mapped_column(String, nullable=False)
    framework: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)  # e.g. "python-web", "react-spa"
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    avg_health_score: Mapped[float | None] = mapped_column(Integer, nullable=True)  # stored as int 0-100
    median_health_score: Mapped[float | None] = mapped_column(Integer, nullable=True)
    percentiles: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: {p10, p25, p50, p75, p90} per dimension
    avg_file_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_test_ratio: Mapped[float | None] = mapped_column(Integer, nullable=True)  # stored as int percentage 0-100
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── Feature 4: Tribal Knowledge ──────────────────────────────────────────────

class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String, ForeignKey("analyses.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    annotation_type: Mapped[str] = mapped_column(String, default="note")  # note | warning | todo | decision
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ArchitectureDecisionRecord(Base):
    __tablename__ = "architecture_decision_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str | None] = mapped_column(String, ForeignKey("teams.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    repo_url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="proposed")  # proposed | accepted | deprecated | superseded
    context: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    consequences: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    superseded_by: Mapped[str | None] = mapped_column(String, ForeignKey("architecture_decision_records.id"), nullable=True)


class ExpertiseMap(Base):
    __tablename__ = "expertise_maps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    repo_url: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    expertise_level: Mapped[str] = mapped_column(String, default="familiar")  # author | reviewer | familiar | none
    last_touched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_detected: Mapped[bool] = mapped_column(Boolean, default=False)


# ── Feature 5: Multi-Repo Intelligence ───────────────────────────────────────

class CrossRepoDependency(Base):
    __tablename__ = "cross_repo_dependencies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_repo_url: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_repo_url: Mapped[str] = mapped_column(String, nullable=False, index=True)
    dependency_type: Mapped[str] = mapped_column(String, nullable=False)  # npm_package | pip_package | shared_proto | api_call
    dependency_name: Mapped[str] = mapped_column(String, nullable=False)
    source_version: Mapped[str | None] = mapped_column(String, nullable=True)
    target_version: Mapped[str | None] = mapped_column(String, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── Feature 6: Workflow Integration ──────────────────────────────────────────

class SlackInstallation(Base):
    __tablename__ = "slack_installations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False, index=True)
    slack_team_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    slack_bot_token: Mapped[str] = mapped_column(String, nullable=False)  # encrypted
    slack_channel_id: Mapped[str | None] = mapped_column(String, nullable=True)
    installed_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ── Vector RAG for Chat ──────────────────────────────────────────────────────

class FileChunk(Base):
    __tablename__ = "file_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String, ForeignKey("analyses.id"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    directory: Mapped[str | None] = mapped_column(String, nullable=True)

# Add vector column dynamically — pgvector Vector(384) for PostgreSQL only.
# On SQLite (local dev) the column is omitted; embedding is skipped entirely.
if _has_pgvector and _Vector is not None:
    FileChunk.embedding = Column(_Vector(384), nullable=True)
