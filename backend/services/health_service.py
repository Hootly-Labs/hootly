"""Architecture health score — computed from existing analysis data, no Claude calls."""
import math
import os
from collections import Counter


def compute_health_score(analysis_result: dict, walked_files: dict) -> dict:
    """Compute a health report from analysis data + walked files.

    Returns dict with overall grade, score (0-100), and per-dimension scores.
    All computation is local — no Claude API calls.
    """
    arch = analysis_result.get("architecture", {})
    key_files = analysis_result.get("key_files", [])
    dep_graph = analysis_result.get("dependency_graph", {})
    file_tree = analysis_result.get("file_tree", [])
    test_files = analysis_result.get("test_files", [])
    reading_order = analysis_result.get("reading_order", [])
    patterns = analysis_result.get("patterns", [])

    scores = {}

    # 1. Modularity (0-100)
    scores["modularity"] = _score_modularity(file_tree, dep_graph)

    # 2. Documentation (0-100)
    scores["documentation"] = _score_documentation(walked_files, file_tree, key_files)

    # 3. Test Coverage (0-100)
    scores["test_coverage"] = _score_test_coverage(file_tree, test_files)

    # 4. Dependency Health (0-100)
    scores["dependency_health"] = _score_dependency_health(walked_files)

    # 5. Code Organization (0-100)
    scores["code_organization"] = _score_code_organization(
        arch, file_tree, key_files, reading_order, patterns
    )

    # 6. Complexity (0-100)
    scores["complexity"] = _score_complexity(walked_files, file_tree)

    # Weighted average
    weights = {
        "modularity": 0.20,
        "documentation": 0.15,
        "test_coverage": 0.15,
        "dependency_health": 0.15,
        "code_organization": 0.20,
        "complexity": 0.15,
    }
    overall = sum(scores[k] * weights[k] for k in scores)
    grade = _to_grade(overall)

    return {
        "overall_score": round(overall),
        "grade": grade,
        "dimensions": {
            k: {"score": round(v), "label": _dimension_label(k, v)}
            for k, v in scores.items()
        },
    }


def _score_modularity(file_tree: list, dep_graph: dict) -> float:
    """Score based on directory structure and import fan-in/fan-out."""
    if not file_tree:
        return 50

    # Directory distribution — how evenly are files spread?
    dirs = Counter()
    max_depth = 0
    for f in file_tree:
        parts = f.replace("\\", "/").split("/")
        max_depth = max(max_depth, len(parts))
        if len(parts) > 1:
            dirs[parts[0]] += 1
        else:
            dirs["."] += 1

    # Penalize flat repos (everything in root) and overly deep ones
    depth_score = 80
    if max_depth <= 1:
        depth_score = 40  # no directory structure
    elif max_depth > 8:
        depth_score = 60  # too deeply nested

    # Penalize single directory with >80% of files
    dir_evenness = 80
    if dirs:
        most_common_pct = dirs.most_common(1)[0][1] / max(len(file_tree), 1)
        if most_common_pct > 0.8:
            dir_evenness = 40
        elif most_common_pct > 0.6:
            dir_evenness = 60

    # Fan-in/fan-out from dep graph
    fan_score = 70
    edges = dep_graph.get("edges", [])
    if edges:
        fan_in = Counter()
        fan_out = Counter()
        for e in edges:
            fan_out[e.get("source", "")] += 1
            fan_in[e.get("target", "")] += 1
        if fan_in:
            max_fan_in = max(fan_in.values())
            # Files imported by >40% of sources = god object
            if max_fan_in > len(file_tree) * 0.4:
                fan_score = 50
            elif max_fan_in > len(file_tree) * 0.2:
                fan_score = 65

    return (depth_score * 0.3 + dir_evenness * 0.35 + fan_score * 0.35)


def _score_documentation(walked_files: dict, file_tree: list, key_files: list) -> float:
    """Score based on README presence/length, docstrings in top files."""
    score = 0

    # README
    readme_content = ""
    for path, content in walked_files.items():
        if path.lower().replace("\\", "/").split("/")[-1].startswith("readme"):
            readme_content = content
            break

    if readme_content:
        if len(readme_content) > 2000:
            score += 40
        elif len(readme_content) > 500:
            score += 30
        else:
            score += 15
    else:
        score += 0

    # CONTRIBUTING.md
    has_contributing = any(
        f.lower().replace("\\", "/").endswith("contributing.md") for f in file_tree
    )
    if has_contributing:
        score += 15

    # Docstrings/comments in top files
    top_files = [f["path"] for f in key_files[:10]]
    comment_ratio = 0
    checked = 0
    for path in top_files:
        content = walked_files.get(path, "")
        if not content:
            continue
        lines = content.split("\n")
        comment_lines = sum(
            1 for l in lines
            if l.strip().startswith(("#", "//", "/*", "*", "'''", '"""'))
        )
        if lines:
            comment_ratio += comment_lines / len(lines)
            checked += 1

    if checked > 0:
        avg_comment_ratio = comment_ratio / checked
        if avg_comment_ratio > 0.15:
            score += 45
        elif avg_comment_ratio > 0.08:
            score += 30
        elif avg_comment_ratio > 0.03:
            score += 20
        else:
            score += 10
    else:
        score += 20  # neutral if can't check

    return min(100, score)


def _score_test_coverage(file_tree: list, test_files: list) -> float:
    """Score based on test file count vs source file count."""
    if not file_tree:
        return 50

    source_count = len(file_tree) - len(test_files)
    if source_count <= 0:
        return 50

    test_count = len(test_files)
    ratio = test_count / source_count

    if ratio >= 0.3:
        return 95
    elif ratio >= 0.2:
        return 80
    elif ratio >= 0.1:
        return 65
    elif ratio >= 0.05:
        return 50
    elif test_count > 0:
        return 35
    else:
        return 15


def _score_dependency_health(walked_files: dict) -> float:
    """Score based on dependency count from config files."""
    dep_count = 0

    for path, content in walked_files.items():
        basename = path.replace("\\", "/").split("/")[-1].lower()
        if basename == "package.json":
            try:
                import json
                pkg = json.loads(content)
                dep_count += len(pkg.get("dependencies", {}))
                dep_count += len(pkg.get("devDependencies", {}))
            except Exception:
                pass
        elif basename == "requirements.txt":
            dep_count += sum(
                1 for l in content.split("\n")
                if l.strip() and not l.strip().startswith("#")
            )
        elif basename == "pyproject.toml":
            # Rough count of dependencies lines
            dep_count += content.count("==") + content.count(">=") + content.count("^")

    # Fewer deps = healthier (less attack surface, less maintenance)
    if dep_count == 0:
        return 70  # can't tell
    elif dep_count <= 10:
        return 95
    elif dep_count <= 30:
        return 80
    elif dep_count <= 60:
        return 65
    elif dep_count <= 100:
        return 50
    else:
        return 35


def _score_code_organization(
    arch: dict, file_tree: list, key_files: list, reading_order: list, patterns: list
) -> float:
    """Score based on naming consistency, entry point clarity, separation of concerns."""
    score = 50  # baseline

    # Entry points clearly identified
    entry_points = arch.get("entry_points", [])
    if entry_points:
        score += 15

    # Key directories with clear purposes
    key_dirs = arch.get("key_directories", [])
    if len(key_dirs) >= 3:
        score += 15
    elif len(key_dirs) >= 1:
        score += 8

    # Patterns identified = good separation of concerns
    if len(patterns) >= 3:
        score += 10
    elif len(patterns) >= 1:
        score += 5

    # Consistent naming — check if files follow common patterns
    naming_patterns = Counter()
    for f in file_tree:
        parts = f.replace("\\", "/").split("/")
        filename = parts[-1].lower()
        if "_" in filename:
            naming_patterns["snake_case"] += 1
        elif filename[0].isupper() and any(c.isupper() for c in filename[1:]):
            naming_patterns["PascalCase"] += 1
        elif any(c.isupper() for c in filename):
            naming_patterns["camelCase"] += 1

    if naming_patterns:
        dominant_pct = naming_patterns.most_common(1)[0][1] / max(sum(naming_patterns.values()), 1)
        if dominant_pct > 0.7:
            score += 10  # consistent naming

    return min(100, score)


def _score_complexity(walked_files: dict, file_tree: list) -> float:
    """Score based on file sizes and nesting depth. Higher = less complex (better)."""
    if not walked_files:
        return 60

    sizes = []
    for path, content in walked_files.items():
        sizes.append(len(content))

    if not sizes:
        return 60

    avg_size = sum(sizes) / len(sizes)
    max_size = max(sizes)

    # Penalize large average file size
    size_score = 80
    if avg_size > 10000:
        size_score = 40
    elif avg_size > 5000:
        size_score = 55
    elif avg_size > 2000:
        size_score = 70

    # Penalize very large individual files
    max_score = 80
    if max_size > 50000:
        max_score = 40
    elif max_size > 20000:
        max_score = 55
    elif max_size > 10000:
        max_score = 70

    # Penalize deeply nested directories
    max_depth = 0
    for f in file_tree:
        depth = len(f.replace("\\", "/").split("/"))
        max_depth = max(max_depth, depth)

    depth_score = 80
    if max_depth > 10:
        depth_score = 50
    elif max_depth > 7:
        depth_score = 65

    return size_score * 0.4 + max_score * 0.35 + depth_score * 0.25


def _to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"


def _dimension_label(dimension: str, score: float) -> str:
    labels = {
        "modularity": "Modularity",
        "documentation": "Documentation",
        "test_coverage": "Test Coverage",
        "dependency_health": "Dependency Health",
        "code_organization": "Code Organization",
        "complexity": "Complexity",
    }
    return labels.get(dimension, dimension.replace("_", " ").title())
