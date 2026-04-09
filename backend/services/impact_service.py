"""Feature 2: Interactive Code Understanding — impact analysis and data flow."""
import json
import logging

logger = logging.getLogger(__name__)


def analyze_impact(analysis_result: dict, file_path: str) -> dict:
    """Find all files that import/depend on the given file, and all it imports.

    Returns the impact radius with categorized dependencies.
    """
    dep_graph = analysis_result.get("dependency_graph", {})
    edges = dep_graph.get("edges", [])

    imports = []  # files this file imports
    imported_by = []  # files that import this file

    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src == file_path:
            imports.append(tgt)
        if tgt == file_path:
            imported_by.append(src)

    # Find transitive dependents (2 levels deep)
    transitive_dependents = set()
    for dep in imported_by:
        for edge in edges:
            if edge.get("target", "") == dep:
                transitive_dependents.add(edge.get("source", ""))
    transitive_dependents -= set(imported_by)
    transitive_dependents.discard(file_path)

    # Get file info from key_files
    key_files = {f["path"]: f for f in analysis_result.get("key_files", [])}
    file_info = key_files.get(file_path, {})

    return {
        "file_path": file_path,
        "explanation": file_info.get("explanation", ""),
        "score": file_info.get("score", 0),
        "imports": sorted(imports),
        "imported_by": sorted(imported_by),
        "transitive_dependents": sorted(transitive_dependents),
        "total_impact_radius": len(imported_by) + len(transitive_dependents),
    }


def explain_data_flow(analysis_result: dict, from_file: str, to_file: str) -> dict:
    """Use dep graph + file contents to explain how data flows between two files."""
    dep_graph = analysis_result.get("dependency_graph", {})
    edges = dep_graph.get("edges", [])
    key_file_contents = analysis_result.get("key_file_contents", {})

    # Find path from from_file to to_file via BFS
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        adjacency.setdefault(src, []).append(tgt)
        adjacency.setdefault(tgt, []).append(src)

    path = _bfs_path(adjacency, from_file, to_file)

    # Get relevant file info
    key_files = {f["path"]: f for f in analysis_result.get("key_files", [])}
    path_info = []
    for p in (path or []):
        info = key_files.get(p, {})
        path_info.append({
            "path": p,
            "explanation": info.get("explanation", ""),
            "key_exports": info.get("key_exports", []),
            "has_content": p in key_file_contents,
        })

    return {
        "from_file": from_file,
        "to_file": to_file,
        "connected": path is not None,
        "path": path or [],
        "path_details": path_info,
        "hop_count": len(path) - 1 if path else -1,
    }


def find_relevant_files(question: str, analysis_result: dict) -> list[str]:
    """Keyword match + file explanation relevance to select files for chat context."""
    key_files = analysis_result.get("key_files", [])
    key_file_contents = analysis_result.get("key_file_contents", {})

    words = set(question.lower().split())
    scored: list[tuple[float, str]] = []

    for f in key_files:
        path = f.get("path", "")
        if path not in key_file_contents:
            continue

        score = 0.0
        path_lower = path.lower()
        explanation = f.get("explanation", "").lower()

        # Path keyword match
        for word in words:
            if len(word) < 3:
                continue
            if word in path_lower:
                score += 3.0
            if word in explanation:
                score += 1.0

        # Boost high-importance files
        score += f.get("score", 0) * 0.1

        if score > 0:
            scored.append((score, path))

    scored.sort(reverse=True)
    return [path for _, path in scored[:5]]


def _bfs_path(adjacency: dict, start: str, end: str) -> list[str] | None:
    """BFS shortest path between two nodes."""
    if start == end:
        return [start]
    visited = {start}
    queue = [(start, [start])]
    while queue:
        node, path = queue.pop(0)
        for neighbor in adjacency.get(node, []):
            if neighbor == end:
                return path + [neighbor]
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    return None
