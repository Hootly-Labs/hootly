import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hootly.db")

# Railway and some other hosts still emit the legacy "postgres://" scheme;
# SQLAlchemy 1.4+ requires "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    # check_same_thread is SQLite-only
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import (  # noqa: F401
        Analysis, Annotation, ApiKey, ArchitectureDecisionRecord, Assessment,
        ChatMessage, CrossRepoDependency, DriftAlert, ExpertiseMap,
        FileChunk, GitHubInstallation, PasswordHistory, RepoBenchmark,
        RepoSnapshot, SlackInstallation, Team, TeamMember, User, WatchedRepo,
    )
    from sqlalchemy import text
    Base.metadata.create_all(bind=engine)

    # Lightweight migrations: add columns that may not exist in older DBs.
    # Postgres supports IF NOT EXISTS; SQLite ignores duplicates via try/except.
    _if_not_exists = "" if _is_sqlite else " IF NOT EXISTS"
    with engine.connect() as conn:
        for column_def in [
            "ALTER TABLE analyses ADD COLUMN{} commit_hash VARCHAR",
            "ALTER TABLE analyses ADD COLUMN{} user_id VARCHAR",
            "ALTER TABLE users ADD COLUMN{} stripe_customer_id VARCHAR",
            "ALTER TABLE users ADD COLUMN{} stripe_subscription_id VARCHAR",
            "ALTER TABLE users ADD COLUMN{} github_id VARCHAR",
            "ALTER TABLE users ADD COLUMN{} notify_on_complete BOOLEAN DEFAULT false",
            "ALTER TABLE analyses ADD COLUMN{} is_starred BOOLEAN DEFAULT false",
            "ALTER TABLE analyses ADD COLUMN{} is_public BOOLEAN DEFAULT false",
            "ALTER TABLE users ADD COLUMN{} is_verified BOOLEAN DEFAULT false",
            "ALTER TABLE users ADD COLUMN{} verification_code VARCHAR",
            "ALTER TABLE users ADD COLUMN{} verification_expires TIMESTAMP",
            "ALTER TABLE users ADD COLUMN{} github_access_token VARCHAR",
            "ALTER TABLE users ADD COLUMN{} github_username VARCHAR",
            "ALTER TABLE analyses ADD COLUMN{} changelog TEXT",
            "ALTER TABLE users ADD COLUMN{} signup_ip VARCHAR",
            "ALTER TABLE users ADD COLUMN{} is_banned BOOLEAN DEFAULT false",
            "ALTER TABLE users ADD COLUMN{} token_invalidated_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN{} failed_login_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN{} locked_until TIMESTAMP",
            "ALTER TABLE users ADD COLUMN{} last_login_country VARCHAR",
            "ALTER TABLE users ADD COLUMN{} last_login_ip VARCHAR",
            "ALTER TABLE analyses ADD COLUMN{} health_score TEXT",
            "ALTER TABLE analyses ADD COLUMN{} team_id VARCHAR",
            "ALTER TABLE file_chunks ADD COLUMN{} language VARCHAR",
            "ALTER TABLE file_chunks ADD COLUMN{} directory VARCHAR",
        ]:
            try:
                conn.execute(text(column_def.format(_if_not_exists)))
                conn.commit()
            except Exception:
                pass  # Column already exists (SQLite fallback)

        # Indexes — IF NOT EXISTS is supported by both SQLite and PostgreSQL.
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS ix_analyses_repo_url ON analyses (repo_url)",
            "CREATE INDEX IF NOT EXISTS ix_analyses_user_id ON analyses (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_analyses_created_at ON analyses (created_at)",
            "CREATE INDEX IF NOT EXISTS ix_analyses_user_created ON analyses (user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_watched_repos_user_id ON watched_repos (user_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_watched_repos_user_repo ON watched_repos (user_id, repo_url)",
            "CREATE INDEX IF NOT EXISTS ix_file_chunks_analysis_lang ON file_chunks (analysis_id, language)",
        ]:
            try:
                conn.execute(text(idx_sql))
                conn.commit()
            except Exception:
                pass

        # Clean up duplicate repo snapshots (keep earliest per repo_url + commit_hash)
        try:
            if _is_sqlite:
                conn.execute(text(
                    "DELETE FROM repo_snapshots WHERE id NOT IN ("
                    "  SELECT MIN(id) FROM repo_snapshots"
                    "  GROUP BY repo_url, commit_hash"
                    ")"
                ))
            else:
                conn.execute(text(
                    "DELETE FROM repo_snapshots WHERE id NOT IN ("
                    "  SELECT DISTINCT ON (repo_url, commit_hash) id"
                    "  FROM repo_snapshots ORDER BY repo_url, commit_hash, snapshot_date ASC"
                    ")"
                ))
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # pgvector extension + embedding column + HNSW index (PostgreSQL only)
        if not _is_sqlite:
            import logging as _log
            _db_logger = _log.getLogger("database")
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
                _db_logger.info("pgvector extension ready")
            except Exception as _e:
                _db_logger.warning("pgvector extension failed: %s", _e)
                try:
                    conn.rollback()
                except Exception:
                    pass
            try:
                conn.execute(text(
                    "ALTER TABLE file_chunks ADD COLUMN IF NOT EXISTS embedding vector(384)"
                ))
                conn.commit()
                _db_logger.info("embedding column ready")
            except Exception as _e:
                _db_logger.warning("embedding column migration failed: %s", _e)
                try:
                    conn.rollback()
                except Exception:
                    pass
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_file_chunks_embedding "
                    "ON file_chunks USING hnsw (embedding vector_cosine_ops)"
                ))
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
