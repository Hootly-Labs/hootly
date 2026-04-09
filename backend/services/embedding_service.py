"""Vector RAG embedding service — chunking, embedding, hybrid search, and multi-hop retrieval.

Uses fastembed (ONNX-based, local) for embeddings and pgvector for storage/search.
BM25 keyword search works on both SQLite and PostgreSQL.
Hybrid search fuses vector + BM25 via Reciprocal Rank Fusion.
Multi-hop retrieval follows cross-file connections for complex questions.
"""
import logging
import math
import re
import time
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from database import _is_sqlite

logger = logging.getLogger(__name__)

# ── BM25 chunk cache (avoids re-loading + re-tokenizing on every query) ──────
# Keyed by analysis_id → {"data": [...], "ts": timestamp}
# Evicted after 5 minutes or when a different analysis is queried.
_bm25_cache: dict[str, dict] = {}
_BM25_CACHE_TTL = 300  # seconds
_BM25_CACHE_MAX = 5    # max analyses cached

# ── Configuration ─────────────────────────────────────────────────────────────

CHUNK_LINES = 60        # lines per chunk
CHUNK_OVERLAP = 10      # overlap between consecutive chunks
MAX_CHUNKS_PER_ANALYSIS = 5000
MAX_FILE_SIZE = 100_000  # 100KB — skip files larger than this
MAX_AVG_LINE_LENGTH = 200  # skip minified files
EMBED_BATCH_SIZE = 64
EMBEDDING_DIM = 384      # all-MiniLM-L6-v2 dimension
MAX_CONTEXT_CHARS = 12_000  # cap injected context for Claude

# ── Lazy singleton embedder ───────────────────────────────────────────────────

_embedder = None
_embedder_checked = False


def _get_embedder():
    """Return fastembed TextEmbedding instance, or None if unavailable."""
    global _embedder, _embedder_checked
    if _embedder_checked:
        return _embedder
    _embedder_checked = True
    if _is_sqlite:
        logger.info("SQLite detected — skipping embedding (no pgvector)")
        return None
    try:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")
        logger.info("fastembed model loaded (all-MiniLM-L6-v2, %d-dim)", EMBEDDING_DIM)
        return _embedder
    except Exception as exc:
        logger.warning("Failed to load fastembed: %s", exc)
        return None


# ── BM25 stop words ──────────────────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from",
    "has", "have", "he", "her", "his", "how", "if", "in", "is", "it", "its",
    "my", "no", "not", "of", "on", "or", "so", "that", "the", "this", "to",
    "up", "was", "we", "what", "when", "where", "which", "who", "why", "will",
    "with", "you", "your", "does", "did", "can", "could", "would", "should",
})


# ── Structure-aware chunking ──────────────────────────────────────────────────

# Patterns that indicate good split points (blank lines, class/function defs)
_SPLIT_PREFIXES = ("class ", "def ", "function ", "export ", "async ", "const ", "import ")


def _is_binary_or_minified(content: str) -> bool:
    """Return True for binary/minified files that shouldn't be chunked."""
    if "\x00" in content[:1024]:
        return True
    lines = content.split("\n")
    if not lines:
        return True
    avg_len = sum(len(l) for l in lines[:50]) / min(len(lines), 50)
    return avg_len > MAX_AVG_LINE_LENGTH


def chunk_file(file_path: str, content: str) -> list[dict]:
    """Split a source file into overlapping chunks with metadata.

    Returns list of {file_path, chunk_index, content, start_line, end_line}.
    """
    if len(content) > MAX_FILE_SIZE:
        return []
    if _is_binary_or_minified(content):
        return []

    lines = content.split("\n")
    if len(lines) <= 3:
        return []

    chunks = []
    i = 0
    chunk_idx = 0

    while i < len(lines):
        end = min(i + CHUNK_LINES, len(lines))

        # Try to find a better split point near the end of the window
        if end < len(lines):
            best_split = end
            # Search backwards from end for a blank line or structure boundary
            for j in range(end, max(end - 15, i + CHUNK_LINES // 2), -1):
                if j < len(lines):
                    line = lines[j].strip()
                    if line == "" or any(line.startswith(p) for p in _SPLIT_PREFIXES):
                        best_split = j
                        break
            end = best_split

        chunk_lines = lines[i:end]
        chunk_content = f"# File: {file_path} (lines {i + 1}-{end})\n" + "\n".join(chunk_lines)

        chunks.append({
            "file_path": file_path,
            "chunk_index": chunk_idx,
            "content": chunk_content,
            "start_line": i + 1,
            "end_line": end,
        })

        chunk_idx += 1
        # Advance by window minus overlap
        i = end - CHUNK_OVERLAP if end < len(lines) else len(lines)

    return chunks


# ── Chunk metadata detection ─────────────────────────────────────────────────

def _detect_chunk_metadata(file_path: str) -> dict:
    """Detect language and directory from a file path.

    Returns {"language": str|None, "directory": str|None}.
    """
    from services.dependency_parser import detect_language

    lang = detect_language(file_path)
    if lang == "other":
        lang = None

    # Directory: first 2 path segments (e.g. "backend/services")
    parts = file_path.replace("\\", "/").split("/")
    if len(parts) >= 2:
        directory = "/".join(parts[:2])
    elif len(parts) == 1:
        directory = parts[0]
    else:
        directory = None

    return {"language": lang, "directory": directory}


# ── Batch embedding ───────────────────────────────────────────────────────────

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-encode texts using fastembed. Returns list of 384-dim vectors."""
    embedder = _get_embedder()
    if not embedder:
        return []

    all_vectors = []
    for batch_start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[batch_start:batch_start + EMBED_BATCH_SIZE]
        vectors = list(embedder.embed(batch))
        all_vectors.extend([v.tolist() for v in vectors])

    return all_vectors


# ── Analysis integration ──────────────────────────────────────────────────────

def embed_analysis_files(analysis_id: str, files: dict[str, str], db: Session) -> int:
    """Chunk and embed all source files for an analysis.

    Always creates FileChunk rows (for BM25 search on any DB).
    Embeddings are set only when fastembed + pgvector are available.

    Args:
        analysis_id: The analysis ID to associate chunks with.
        files: Dict of file_path → content from file_service walk.
        db: SQLAlchemy session.

    Returns:
        Number of chunks created.
    """
    from models import FileChunk

    embedder = _get_embedder()

    # Delete existing chunks for idempotency
    db.query(FileChunk).filter(FileChunk.analysis_id == analysis_id).delete()
    db.flush()

    # Chunk all files
    all_chunks = []
    for path, content in files.items():
        if len(all_chunks) >= MAX_CHUNKS_PER_ANALYSIS:
            break
        file_chunks = chunk_file(path, content)
        remaining = MAX_CHUNKS_PER_ANALYSIS - len(all_chunks)
        all_chunks.extend(file_chunks[:remaining])

    if not all_chunks:
        return 0

    # Batch embed (empty list on SQLite / no fastembed)
    texts = [c["content"] for c in all_chunks]
    vectors = embed_texts(texts) if embedder else []

    has_vectors = len(vectors) == len(all_chunks)
    if embedder and not has_vectors:
        logger.warning("Vector count mismatch: %d chunks, %d vectors — saving chunks without embeddings",
                        len(all_chunks), len(vectors))

    # Bulk insert
    chunk_rows = []
    for idx, chunk in enumerate(all_chunks):
        meta = _detect_chunk_metadata(chunk["file_path"])
        row = FileChunk(
            id=str(uuid.uuid4()),
            analysis_id=analysis_id,
            file_path=chunk["file_path"],
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
            start_line=chunk["start_line"],
            end_line=chunk["end_line"],
            language=meta["language"],
            directory=meta["directory"],
        )
        # Set embedding via attribute (column exists only on PostgreSQL)
        if has_vectors and hasattr(FileChunk, "embedding"):
            row.embedding = vectors[idx]
        chunk_rows.append(row)

    try:
        db.bulk_save_objects(chunk_rows)
        db.commit()
        return len(chunk_rows)
    except Exception as exc:
        # Likely: pgvector extension not installed, "embedding" column doesn't exist.
        # Retry without embeddings so chunks are still created for BM25 search.
        logger.warning("Chunk insert failed (retrying without embeddings): %s", exc)
        db.rollback()

        # Delete any partial inserts
        db.query(FileChunk).filter(FileChunk.analysis_id == analysis_id).delete()
        db.flush()

        # Rebuild rows without embedding
        chunk_rows_no_embed = []
        for idx, chunk in enumerate(all_chunks):
            meta = _detect_chunk_metadata(chunk["file_path"])
            row = FileChunk(
                id=str(uuid.uuid4()),
                analysis_id=analysis_id,
                file_path=chunk["file_path"],
                chunk_index=chunk["chunk_index"],
                content=chunk["content"],
                start_line=chunk["start_line"],
                end_line=chunk["end_line"],
                language=meta["language"],
                directory=meta["directory"],
            )
            chunk_rows_no_embed.append(row)

        db.bulk_save_objects(chunk_rows_no_embed)
        db.commit()
        logger.info("Saved %d chunks without embeddings (BM25 only)", len(chunk_rows_no_embed))
        return len(chunk_rows_no_embed)


# ── BM25 tokenization ────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Tokenize text for BM25: lowercase, split on non-alphanumeric, remove stop words."""
    tokens = re.split(r"[^a-zA-Z0-9_]+", text.lower())
    return [t for t in tokens if len(t) >= 2 and t not in _STOP_WORDS]


# ── BM25 search ──────────────────────────────────────────────────────────────

def _get_bm25_chunk_data(analysis_id: str, db: Session) -> list[dict]:
    """Load and tokenize all chunks for an analysis, with caching."""
    now = time.time()

    # Check cache
    cached = _bm25_cache.get(analysis_id)
    if cached and (now - cached["ts"]) < _BM25_CACHE_TTL:
        return cached["data"]

    from models import FileChunk

    chunks = db.query(FileChunk).filter(FileChunk.analysis_id == analysis_id).all()
    if not chunks:
        return []

    chunk_data = []
    for c in chunks:
        tokens = _tokenize(c.content)
        chunk_data.append({
            "file_path": c.file_path,
            "content": c.content,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "language": c.language,
            "directory": c.directory,
            "tokens": tokens,
        })

    # Evict oldest if cache is full
    if len(_bm25_cache) >= _BM25_CACHE_MAX:
        oldest_key = min(_bm25_cache, key=lambda k: _bm25_cache[k]["ts"])
        del _bm25_cache[oldest_key]

    _bm25_cache[analysis_id] = {"data": chunk_data, "ts": now}
    return chunk_data


def bm25_search_chunks(
    question: str,
    analysis_id: str,
    db: Session,
    limit: int = 8,
    language: str | None = None,
    directory: str | None = None,
) -> list[dict]:
    """BM25 keyword search over FileChunk rows. Works on SQLite and PostgreSQL.

    Returns list of {file_path, content, start_line, end_line, score}.
    """
    query_tokens = _tokenize(question)
    if not query_tokens:
        return []

    # Load from cache (avoids re-querying + re-tokenizing)
    all_chunk_data = _get_bm25_chunk_data(analysis_id, db)
    if not all_chunk_data:
        return []

    # Apply metadata filters in Python (chunks are cached unfiltered)
    chunk_data = all_chunk_data
    if language:
        chunk_data = [cd for cd in chunk_data if cd.get("language") == language]
    if directory:
        chunk_data = [cd for cd in chunk_data if cd.get("directory", "").startswith(directory)]

    if not chunk_data:
        return []

    # BM25 parameters
    k1 = 1.5
    b = 0.75
    N = len(chunk_data)
    avg_dl = sum(len(cd["tokens"]) for cd in chunk_data) / N if N else 1

    # Document frequency for each query token
    df = {}
    for qt in query_tokens:
        df[qt] = sum(1 for cd in chunk_data if qt in cd["tokens"])

    # Score each chunk
    scored = []
    for cd in chunk_data:
        doc_tokens = cd["tokens"]
        dl = len(doc_tokens)
        score = 0.0

        # Count term frequencies
        tf_map = {}
        for t in doc_tokens:
            if t in df:
                tf_map[t] = tf_map.get(t, 0) + 1

        for qt in query_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            doc_freq = df[qt]
            # IDF: log((N - df + 0.5) / (df + 0.5) + 1) — add 1 to avoid negative IDF
            idf = math.log((N - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
            # TF saturation with length normalization
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
            score += idf * tf_norm

        if score > 0:
            scored.append({
                "file_path": cd["file_path"],
                "content": cd["content"],
                "start_line": cd["start_line"],
                "end_line": cd["end_line"],
                "score": score,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


# ── Metadata filter detection ─────────────────────────────────────────────────

_LANGUAGE_KEYWORDS = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "react": "typescript",
    "jsx": "javascript",
    "tsx": "typescript",
    "golang": "go",
    "rust": "rust",
    "java": "java",
    "ruby": "ruby",
    "css": "css",
    "html": "html",
}

_DIRECTORY_KEYWORDS = {
    "backend": "backend",
    "server": "backend",
    "api": "backend/api",
    "frontend": "frontend",
    "client": "frontend",
    "components": "frontend/components",
    "services": "backend/services",
    "models": "backend",
    "pages": "frontend/pages",
}


def detect_filters_from_question(question: str) -> dict:
    """Detect language and directory filters from a natural-language question.

    Uses word-boundary matching to avoid false positives (e.g. "got" matching "go").
    Returns {"language": str|None, "directory": str|None}.
    """
    q_lower = question.lower()
    language = None
    directory = None

    # Language detection — word-boundary match
    for keyword, lang in _LANGUAGE_KEYWORDS.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", q_lower):
            language = lang
            break

    # Special case: "go" needs careful word-boundary matching
    if not language and re.search(r"\bgo\b", q_lower):
        # Only match if it looks like a language reference, not the verb
        # "go code", "go files", "go handler" → match. "go to", "go ahead" → skip
        if re.search(r"\bgo\s+(code|files?|handler|module|package|func|struct|interface|service|router)", q_lower):
            language = "go"

    # Directory detection — word-boundary match
    for keyword, dir_path in _DIRECTORY_KEYWORDS.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", q_lower):
            directory = dir_path
            break

    return {"language": language, "directory": directory}


# ── Vector search ─────────────────────────────────────────────────────────────

# ── Question embedding cache (avoids re-embedding same question in multi-hop) ─
_embed_cache: dict[str, list[float]] = {}
_EMBED_CACHE_MAX = 20


def _embed_question(question: str) -> list[float] | None:
    """Embed a question string, with short-lived cache for multi-hop reuse."""
    if question in _embed_cache:
        return _embed_cache[question]

    embedder = _get_embedder()
    if not embedder:
        return None

    vectors = list(embedder.embed([question]))
    if not vectors:
        return None

    vec = vectors[0].tolist()

    if len(_embed_cache) >= _EMBED_CACHE_MAX:
        _embed_cache.pop(next(iter(_embed_cache)))
    _embed_cache[question] = vec

    return vec


def search_similar_chunks(
    question: str,
    analysis_id: str,
    db: Session,
    limit: int = 8,
    language: str | None = None,
    directory: str | None = None,
) -> list[dict]:
    """Find the most relevant code chunks for a question using cosine similarity.

    Returns list of {file_path, content, start_line, end_line, score}.
    Falls back to empty list if pgvector is unavailable.
    """
    from models import FileChunk
    if not hasattr(FileChunk, "embedding"):
        return []

    query_vector = _embed_question(question)
    if not query_vector:
        return []

    # Build WHERE clause with optional metadata filters
    where_clauses = ["analysis_id = :aid", "embedding IS NOT NULL"]
    params = {"aid": analysis_id, "vec": str(query_vector), "lim": limit}

    if language:
        where_clauses.append("language = :lang")
        params["lang"] = language
    if directory:
        where_clauses.append("directory LIKE :dir")
        params["dir"] = f"{directory}%"

    where_sql = " AND ".join(where_clauses)

    # pgvector cosine distance search
    try:
        from sqlalchemy import text as sa_text
        results = db.execute(
            sa_text(
                f"SELECT file_path, content, start_line, end_line, "
                f"1 - (embedding <=> :vec::vector) as score "
                f"FROM file_chunks "
                f"WHERE {where_sql} "
                f"ORDER BY embedding <=> :vec::vector "
                f"LIMIT :lim"
            ),
            params,
        ).fetchall()

        return [
            {
                "file_path": r.file_path,
                "content": r.content,
                "start_line": r.start_line,
                "end_line": r.end_line,
                "score": float(r.score),
            }
            for r in results
        ]
    except Exception as exc:
        logger.warning("Vector search failed: %s", exc)
        return []


# ── Hybrid search (Vector + BM25 with RRF fusion) ────────────────────────────

_BM25_GOOD_SCORE = 3.0  # BM25 score threshold — above this, skip slow vector search


def hybrid_search_chunks(
    question: str,
    analysis_id: str,
    db: Session,
    limit: int = 8,
    language: str | None = None,
    directory: str | None = None,
) -> list[dict]:
    """Hybrid search: BM25 first (fast), vector only if BM25 results are weak.

    BM25 runs in milliseconds. Vector search requires fastembed inference (seconds
    on CPU). Only invoke vector search when BM25 can't find strong matches.
    On SQLite: always BM25-only.
    """
    # Auto-detect filters if not provided
    if language is None and directory is None:
        detected = detect_filters_from_question(question)
        language = detected["language"]
        directory = detected["directory"]

    # BM25 first — always fast
    bm25_results = bm25_search_chunks(question, analysis_id, db, limit=limit, language=language, directory=directory)

    # If filtered results are sparse, retry unfiltered
    if len(bm25_results) < limit and (language or directory):
        unfiltered = bm25_search_chunks(question, analysis_id, db, limit=limit)
        if len(unfiltered) > len(bm25_results):
            bm25_results = unfiltered

    # If BM25 found strong matches, return them directly (skip slow vector search)
    if bm25_results and bm25_results[0]["score"] >= _BM25_GOOD_SCORE:
        return bm25_results

    # BM25 results are weak — supplement with vector search
    vector_results = search_similar_chunks(question, analysis_id, db, limit=limit, language=language, directory=directory)

    if not vector_results:
        return bm25_results

    # RRF fusion
    def _key(r):
        return f"{r['file_path']}:{r['start_line']}"

    vector_ranks = {_key(r): i for i, r in enumerate(vector_results)}
    bm25_ranks = {_key(r): i for i, r in enumerate(bm25_results)}

    all_results = {}
    for r in bm25_results + vector_results:
        k = _key(r)
        if k not in all_results:
            all_results[k] = r

    rrf_k = 60
    scored = []
    for k, r in all_results.items():
        score = 0.0
        if k in vector_ranks:
            score += 0.6 / (rrf_k + vector_ranks[k])
        if k in bm25_ranks:
            score += 0.4 / (rrf_k + bm25_ranks[k])
        scored.append({**r, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


# ── Multi-hop retrieval ───────────────────────────────────────────────────────

# Flow/connection words that suggest cross-file questions
_FLOW_WORDS = frozenset({
    "webhook", "pipeline", "middleware", "triggers", "calls", "invokes",
    "flow", "chain", "process", "handles", "routes", "dispatches",
    "updates", "sends", "receives", "connects", "passes", "forwards",
})

# Component references
_COMPONENT_WORDS = frozenset({
    "api", "service", "model", "controller", "handler", "route", "router",
    "middleware", "database", "schema", "view", "component", "page",
    "endpoint", "client", "server", "worker", "queue", "store",
})

# Import patterns for hop-2 query extraction
_PYTHON_IMPORT_RE = re.compile(r"(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")
_JS_IMPORT_RE = re.compile(r"""(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))""")
_SERVICE_PATTERN_RE = re.compile(r"\b([A-Z][a-z]+(?:Service|Handler|Controller|Manager|Provider|Router|Worker))\b")


def _needs_multi_hop(question: str) -> bool:
    """Heuristic: does this question likely need cross-file retrieval?

    Triggers on:
    - Flow words (webhook, pipeline, middleware, triggers, etc.)
    - "how does X update/call/send Y" patterns
    - 2+ component references (api, service, model, etc.)
    """
    q_lower = question.lower()
    tokens = set(re.split(r"\W+", q_lower))

    # Check for flow words
    if tokens & _FLOW_WORDS:
        return True

    # Check for "how does X verb Y" patterns
    if re.search(r"how\s+does\s+\w+.*?\s+(update|call|send|trigger|invoke|handle|process|create|delete|modify)\s+", q_lower):
        return True

    # Check for 2+ component references
    component_count = len(tokens & _COMPONENT_WORDS)
    if component_count >= 2:
        return True

    return False


def _extract_hop2_queries(first_hop_chunks: list[dict], question: str) -> list[str]:
    """Generate follow-up search queries from first-hop results.

    Parses import statements and notable identifiers from first-hop chunks
    to find connected files. Returns up to 3 synthetic queries.
    """
    referenced_modules = set()
    notable_identifiers = set()
    hop1_files = set()

    for chunk in first_hop_chunks:
        content = chunk["content"]
        hop1_files.add(chunk["file_path"])

        # Extract Python imports
        for m in _PYTHON_IMPORT_RE.finditer(content):
            module = m.group(1) or m.group(2)
            if module:
                # Take the last segment (e.g. "services.auth_service" → "auth_service")
                referenced_modules.add(module.split(".")[-1])

        # Extract JS/TS imports
        for m in _JS_IMPORT_RE.finditer(content):
            path = m.group(1) or m.group(2)
            if path and not path.startswith("."):
                continue  # skip node_modules
            if path:
                # Take filename from path (e.g. "./services/auth" → "auth")
                referenced_modules.add(path.split("/")[-1].replace(".ts", "").replace(".js", ""))

        # Extract Service/Handler/etc. class names
        for m in _SERVICE_PATTERN_RE.finditer(content):
            notable_identifiers.add(m.group(1))

    # Build synthetic queries
    queries = []

    # Query from referenced modules not in hop-1 files
    hop1_basenames = {f.split("/")[-1].rsplit(".", 1)[0] for f in hop1_files}
    new_modules = referenced_modules - hop1_basenames
    if new_modules:
        # Take top 3 most relevant modules
        mod_list = sorted(new_modules)[:3]
        queries.append(" ".join(mod_list))

    # Query from notable identifiers
    if notable_identifiers:
        id_list = sorted(notable_identifiers)[:3]
        queries.append(" ".join(id_list))

    # Query combining key terms from original question + hop-1 file paths
    q_tokens = _tokenize(question)
    if q_tokens and hop1_files:
        path_tokens = set()
        for f in hop1_files:
            parts = f.replace("\\", "/").split("/")
            for p in parts:
                name = p.rsplit(".", 1)[0]
                if len(name) > 2:
                    path_tokens.add(name)
        combined = list(set(q_tokens[:3]) | path_tokens)[:5]
        queries.append(" ".join(combined))

    return queries[:2]


def multi_hop_search(
    question: str,
    analysis_id: str,
    db: Session,
    limit: int = 8,
) -> list[dict]:
    """Multi-hop retrieval: follow cross-file connections for complex questions.

    Hop 1: hybrid search on the original question.
    Hop 2: BM25-only search on 1 follow-up query (fast, no vector inference).
    """
    # Hop 1: get initial results
    hop1 = hybrid_search_chunks(question, analysis_id, db, limit=6)

    if not hop1:
        return []

    # Mark hop-1 results
    for r in hop1:
        r["hop"] = 1

    # Generate hop-2 queries
    hop2_queries = _extract_hop2_queries(hop1, question)
    if not hop2_queries:
        return hop1[:limit]

    # Hop 2: BM25-only for speed (no vector inference overhead)
    seen_keys = {f"{r['file_path']}:{r['start_line']}" for r in hop1}
    hop2_results = []

    # Only run 1 hop-2 query to keep it fast
    results = bm25_search_chunks(hop2_queries[0], analysis_id, db, limit=4)
    for r in results:
        key = f"{r['file_path']}:{r['start_line']}"
        if key not in seen_keys:
            seen_keys.add(key)
            r["hop"] = 2
            hop2_results.append(r)

    # Merge: hop-1 gets a score boost for priority
    all_results = []
    for r in hop1:
        all_results.append({**r, "score": r.get("score", 0) + 0.1})
    all_results.extend(hop2_results)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:limit]


# ── Cache-hit copy ────────────────────────────────────────────────────────────

def copy_embeddings_for_cache_hit(
    source_analysis_id: str,
    target_analysis_id: str,
    db: Session,
) -> int:
    """Copy FileChunk rows from a cached analysis to a new one.

    Avoids re-embedding identical code when the commit hash matches.
    Works on both SQLite (chunks only) and PostgreSQL (chunks + embeddings).
    Returns the number of chunks copied.
    """
    from models import FileChunk
    source_chunks = (
        db.query(FileChunk)
        .filter(FileChunk.analysis_id == source_analysis_id)
        .all()
    )

    if not source_chunks:
        return 0

    new_rows = []
    for sc in source_chunks:
        row = FileChunk(
            id=str(uuid.uuid4()),
            analysis_id=target_analysis_id,
            file_path=sc.file_path,
            chunk_index=sc.chunk_index,
            content=sc.content,
            start_line=sc.start_line,
            end_line=sc.end_line,
            language=sc.language,
            directory=sc.directory,
        )
        if hasattr(FileChunk, "embedding") and hasattr(sc, "embedding") and sc.embedding is not None:
            row.embedding = sc.embedding
        new_rows.append(row)

    db.bulk_save_objects(new_rows)
    db.commit()

    return len(new_rows)
