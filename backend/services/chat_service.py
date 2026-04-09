"""Chat Q&A service — streams Claude responses grounded in analysis data."""
import json
import logging
import os
from typing import Generator

from anthropic import Anthropic

logger = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

FREE_CHAT_LIMIT = 10  # max user messages per analysis for free plan


def build_system_prompt(
    analysis_result: dict,
    question: str | None = None,
    annotations: list | None = None,
    analysis_id: str | None = None,
    db=None,
) -> str:
    """Condense analysis into a ~12K char context for the chat assistant.

    If question is provided, uses vector search (pgvector) for relevant code chunks.
    Falls back to keyword search on SQLite or when vector search returns nothing.
    If annotations are provided, includes them as tribal knowledge context.
    """
    arch = analysis_result.get("architecture", {})
    key_files = analysis_result.get("key_files", [])[:15]
    dep_graph = analysis_result.get("dependency_graph", {})
    reading_order = analysis_result.get("reading_order", [])
    patterns = analysis_result.get("patterns", [])
    key_concepts = analysis_result.get("key_concepts", [])
    quick_start = analysis_result.get("quick_start", "")

    # Build concise file summaries
    files_block = ""
    for f in key_files:
        exports = ", ".join(f.get("key_exports", [])[:5])
        files_block += f"\n- {f['path']} (score: {f.get('score', 0)}/10): {f.get('explanation', '')[:200]}"
        if exports:
            files_block += f" [exports: {exports}]"

    # Build dep graph edges (up to 100)
    edges_block = ""
    edges = dep_graph.get("edges", [])[:100]
    if edges:
        edge_lines = [f"  {e['source']} -> {e['target']}" for e in edges]
        edges_block = f"\n\nDEPENDENCY GRAPH ({len(edges)} edges):\n" + "\n".join(edge_lines)

    # Reading order
    reading_block = ""
    if reading_order:
        steps = [f"  {s.get('step', i+1)}. {s['path']} — {s.get('reason', '')}" for i, s in enumerate(reading_order)]
        reading_block = "\n\nREADING ORDER:\n" + "\n".join(steps)

    # Patterns
    patterns_block = ""
    if patterns:
        pats = [f"  - {p['name']}: {p.get('explanation', '')}" for p in patterns]
        patterns_block = "\n\nARCHITECTURE PATTERNS:\n" + "\n".join(pats)

    concepts_str = ", ".join(key_concepts) if key_concepts else ""

    # Include relevant source code if question provided.
    # Uses hybrid search (vector + BM25) with multi-hop for cross-file questions.
    # Falls back to keyword match if no FileChunk rows exist at all.
    file_contents_block = ""
    if question:
        rag_chunks = []
        if analysis_id and db:
            try:
                from services.embedding_service import (
                    _needs_multi_hop, multi_hop_search, hybrid_search_chunks,
                )
                if _needs_multi_hop(question):
                    rag_chunks = multi_hop_search(question, analysis_id, db, limit=8)
                else:
                    rag_chunks = hybrid_search_chunks(question, analysis_id, db, limit=8)
            except Exception as exc:
                logger.debug("Hybrid search unavailable, falling back to keyword: %s", exc)
                try:
                    db.rollback()
                except Exception:
                    pass

        if rag_chunks:
            chunks = []
            total_chars = 0
            for vc in rag_chunks:
                content = vc["content"]
                if total_chars + len(content) > 12_000:
                    break
                hop_label = f" [hop {vc['hop']}]" if "hop" in vc else ""
                chunks.append(f"\n=== {vc['file_path']} (lines {vc['start_line']}-{vc['end_line']}){hop_label} ===\n{content}")
                total_chars += len(content)
            if chunks:
                file_contents_block = "\n\nRELEVANT SOURCE CODE:" + "".join(chunks)
        else:
            # Last resort: keyword-based retrieval (no FileChunk rows at all)
            from services.impact_service import find_relevant_files
            relevant = find_relevant_files(question, analysis_result)
            key_file_contents = analysis_result.get("key_file_contents", {})
            if relevant and key_file_contents:
                chunks = []
                total_chars = 0
                for path in relevant:
                    content = key_file_contents.get(path, "")
                    if content and total_chars + len(content) < 8000:
                        chunks.append(f"\n=== {path} ===\n{content[:2000]}")
                        total_chars += len(content[:2000])
                if chunks:
                    file_contents_block = "\n\nRELEVANT SOURCE CODE:" + "".join(chunks)

    # Include annotations as tribal knowledge (Feature 4)
    annotations_block = ""
    if annotations:
        ann_lines = []
        for ann in annotations[:10]:
            ann_lines.append(f"  - [{ann.get('type', 'note')}] {ann.get('file_path', '')}: {ann.get('content', '')[:150]}")
        if ann_lines:
            annotations_block = "\n\nTEAM ANNOTATIONS:\n" + "\n".join(ann_lines)

    return f"""You are a coding assistant for the repository "{analysis_result.get('repo_name', 'unknown')}". You have deep knowledge of this codebase from a comprehensive analysis. Answer questions grounded in the analysis data below. Be specific, cite file paths, and reference the dependency graph when discussing change impact.

PROJECT: {arch.get('project_name', '')} — {arch.get('description', '')}
TYPE: {arch.get('architecture_type', '')}
STACK: {', '.join(arch.get('tech_stack', []))}
LANGUAGES: {', '.join(arch.get('languages', []))}

ARCHITECTURE SUMMARY:
{arch.get('architecture_summary', '')}

KEY FILES:{files_block}
{edges_block}
{reading_block}
{patterns_block}

KEY CONCEPTS: {concepts_str}

QUICK START: {quick_start}
{file_contents_block}
{annotations_block}

INSTRUCTIONS:
- Answer questions about the codebase grounded in the analysis data above.
- When asked about change impact, trace through the dependency graph edges to identify affected files.
- When asked how a feature works, reference specific files and their roles.
- When asked how to add something new, suggest where to add code based on existing patterns.
- When source code is available, cite specific functions, classes, and line patterns.
- Be concise but thorough. Use markdown formatting for code blocks and file paths.
- If you don't have enough information to answer, say so clearly."""


def stream_chat_response(
    system_prompt: str,
    messages: list[dict],
) -> Generator[str, None, str]:
    """Stream Claude response as SSE lines. Yields SSE data lines, returns full text."""
    full_text = ""
    with client.messages.stream(
        model=MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            full_text += text
            line = json.dumps({"type": "delta", "text": text})
            yield f"data: {line}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'full_text': full_text})}\n\n"
    return full_text
