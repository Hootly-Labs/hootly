"""Feature 3: Benchmarking — compare repos against similar projects."""
import json
import logging
import statistics

from sqlalchemy.orm import Session

from models import _utcnow, Analysis, RepoBenchmark

logger = logging.getLogger(__name__)

# Framework-to-category mapping
_FRAMEWORK_CATEGORIES: dict[str, str] = {
    "fastapi": "python-web",
    "flask": "python-web",
    "django": "python-web",
    "express": "node-web",
    "next.js": "react-spa",
    "nextjs": "react-spa",
    "react": "react-spa",
    "vue": "vue-spa",
    "nuxt": "vue-spa",
    "angular": "angular-spa",
    "spring": "java-web",
    "rails": "ruby-web",
    "gin": "go-web",
    "echo": "go-web",
    "fiber": "go-web",
    "actix": "rust-web",
    "rocket": "rust-web",
}

_LANGUAGE_CATEGORIES: dict[str, str] = {
    "python": "python-general",
    "javascript": "node-general",
    "typescript": "node-general",
    "go": "go-general",
    "rust": "rust-general",
    "java": "java-general",
    "ruby": "ruby-general",
}


def categorize_repo(analysis_result: dict) -> str:
    """Determine category from tech stack (e.g., Python + FastAPI → 'python-web')."""
    arch = analysis_result.get("architecture", {})
    tech_stack = [t.lower() for t in arch.get("tech_stack", [])]
    languages = [l.lower() for l in arch.get("languages", [])]

    # Try framework match first (more specific)
    for tech in tech_stack:
        for framework, category in _FRAMEWORK_CATEGORIES.items():
            if framework in tech:
                return category

    # Fall back to language match
    for lang in languages:
        for language, category in _LANGUAGE_CATEGORIES.items():
            if language in lang:
                return category

    return "general"


def get_benchmark(category: str, db: Session) -> RepoBenchmark | None:
    """Fetch benchmark for a category."""
    return db.query(RepoBenchmark).filter(RepoBenchmark.category == category).first()


def compute_percentile(score: float, benchmark: RepoBenchmark, dimension: str = "overall") -> int:
    """Where does this repo rank (0-100 percentile)?"""
    if not benchmark or not benchmark.percentiles:
        return 50  # default when no data

    try:
        percentiles = json.loads(benchmark.percentiles)
    except Exception:
        return 50

    dim_pcts = percentiles.get(dimension, {})
    if not dim_pcts:
        return 50

    # Interpolate between known percentile boundaries
    boundaries = [(10, dim_pcts.get("p10", 0)), (25, dim_pcts.get("p25", 0)),
                  (50, dim_pcts.get("p50", 0)), (75, dim_pcts.get("p75", 0)),
                  (90, dim_pcts.get("p90", 0))]

    if score <= boundaries[0][1]:
        return boundaries[0][0]
    if score >= boundaries[-1][1]:
        return boundaries[-1][0]

    for i in range(len(boundaries) - 1):
        p1, s1 = boundaries[i]
        p2, s2 = boundaries[i + 1]
        if s1 <= score <= s2 and s2 > s1:
            frac = (score - s1) / (s2 - s1)
            return int(p1 + frac * (p2 - p1))

    return 50


def generate_benchmark_report(analysis_id: str, db: Session) -> dict | None:
    """Generate a full benchmark comparison for an analysis."""
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
    if not analysis or not analysis.result or not analysis.health_score:
        return None

    try:
        result = json.loads(analysis.result)
        health = json.loads(analysis.health_score)
    except Exception:
        return None

    category = categorize_repo(result)
    benchmark = get_benchmark(category, db)

    if not benchmark or benchmark.sample_size < 10:
        return {
            "category": category,
            "has_benchmark": False,
            "message": f"Not enough data for '{category}' category yet. Be one of the first!",
        }

    overall_pct = compute_percentile(health.get("overall_score", 0), benchmark, "overall")

    dimension_comparisons = {}
    dimensions = health.get("dimensions", {})
    for dim_name, dim_data in dimensions.items():
        dim_score = dim_data.get("score", 0)
        dim_pct = compute_percentile(dim_score, benchmark, dim_name)
        dimension_comparisons[dim_name] = {
            "score": dim_score,
            "percentile": dim_pct,
            "label": dim_data.get("label", dim_name),
        }

    # Generate text callouts
    callouts = []
    for dim_name, comp in dimension_comparisons.items():
        if comp["percentile"] >= 75:
            callouts.append(f"Your {comp['label']} score is in the top 25% of {_format_category(category)} projects")
        elif comp["percentile"] <= 25:
            callouts.append(f"Your {comp['label']} score is in the bottom 25% of {_format_category(category)} projects")

    return {
        "category": category,
        "category_label": _format_category(category),
        "has_benchmark": True,
        "sample_size": benchmark.sample_size,
        "overall_percentile": overall_pct,
        "overall_score": health.get("overall_score", 0),
        "median_score": benchmark.median_health_score,
        "dimensions": dimension_comparisons,
        "callouts": callouts,
    }


def rebuild_benchmarks(db: Session) -> int:
    """Aggregate all completed analyses by category, compute percentiles. Returns count updated."""
    analyses = (
        db.query(Analysis)
        .filter(Analysis.status == "completed", Analysis.result.isnot(None), Analysis.health_score.isnot(None))
        .order_by(Analysis.created_at.desc())
        .all()
    )

    # Deduplicate: keep only the latest analysis per repo URL
    seen_repos: set[str] = set()
    unique_analyses: list[Analysis] = []
    for a in analyses:
        if a.repo_url and a.repo_url not in seen_repos:
            seen_repos.add(a.repo_url)
            unique_analyses.append(a)

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for a in unique_analyses:
        try:
            result = json.loads(a.result)
            health = json.loads(a.health_score)
        except Exception:
            continue

        cat = categorize_repo(result)
        by_category.setdefault(cat, []).append(health)

    count = 0
    for category, health_list in by_category.items():
        if len(health_list) < 3:
            continue  # need at least 3 samples

        overall_scores = [h.get("overall_score", 0) for h in health_list]
        file_counts = []  # would need file_tree but health doesn't store it

        # Compute percentiles for overall and each dimension
        percentiles_data: dict[str, dict] = {}
        percentiles_data["overall"] = _compute_percentiles(overall_scores)

        # Collect dimension scores
        dim_scores: dict[str, list[float]] = {}
        for h in health_list:
            for dim_name, dim_data in h.get("dimensions", {}).items():
                dim_scores.setdefault(dim_name, []).append(dim_data.get("score", 0))

        for dim_name, scores in dim_scores.items():
            if len(scores) >= 3:
                percentiles_data[dim_name] = _compute_percentiles(scores)

        # Test ratio
        test_ratios = []
        for h in health_list:
            tc = h.get("dimensions", {}).get("test_coverage", {}).get("score", 0)
            test_ratios.append(tc)

        # Determine primary language/framework
        language = category.split("-")[0] if "-" in category else category
        framework = None
        for fw, cat in _FRAMEWORK_CATEGORIES.items():
            if cat == category:
                framework = fw
                break

        # Upsert benchmark
        existing = db.query(RepoBenchmark).filter(RepoBenchmark.category == category).first()
        if existing:
            bm = existing
        else:
            bm = RepoBenchmark(category=category)
            db.add(bm)

        bm.language = language
        bm.framework = framework
        bm.sample_size = len(health_list)
        bm.avg_health_score = int(statistics.mean(overall_scores))
        bm.median_health_score = int(statistics.median(overall_scores))
        bm.percentiles = json.dumps(percentiles_data)
        bm.avg_test_ratio = int(statistics.mean(test_ratios)) if test_ratios else None
        bm.updated_at = _utcnow()
        count += 1

    if count > 0:
        db.commit()
    logger.info("Rebuilt benchmarks for %d categories", count)
    return count


def _compute_percentiles(values: list[float]) -> dict:
    """Compute p10, p25, p50, p75, p90 for a list of values."""
    if not values:
        return {}
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def _pct(p: float) -> float:
        idx = (p / 100) * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    return {
        "p10": round(_pct(10), 1),
        "p25": round(_pct(25), 1),
        "p50": round(_pct(50), 1),
        "p75": round(_pct(75), 1),
        "p90": round(_pct(90), 1),
    }


def _format_category(category: str) -> str:
    """Human-readable category name."""
    labels = {
        "python-web": "Python web",
        "python-general": "Python",
        "react-spa": "React",
        "vue-spa": "Vue",
        "angular-spa": "Angular",
        "node-web": "Node.js web",
        "node-general": "Node.js",
        "go-web": "Go web",
        "go-general": "Go",
        "rust-web": "Rust web",
        "rust-general": "Rust",
        "java-web": "Java web",
        "java-general": "Java",
        "ruby-web": "Ruby web",
        "ruby-general": "Ruby",
        "general": "general",
    }
    return labels.get(category, category.replace("-", " ").title())
