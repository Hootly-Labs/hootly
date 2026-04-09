"""Assessment report service — premium Claude-powered deep analysis."""
import json
import logging
import os
from typing import Any

from anthropic import Anthropic

logger = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _ask(system: str, user: str, max_tokens: int = 4096) -> str:
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


def _extract_json(text: str) -> Any:
    """Extract JSON from response (reuse pattern from claude_service)."""
    import re
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    for sc, ec in [('{', '}'), ('[', ']')]:
        s = text.find(sc)
        e = text.rfind(ec)
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e+1])
            except json.JSONDecodeError:
                pass
    raise ValueError(f"Could not parse JSON from response:\n{text[:500]}")


def generate_assessment(analysis_result: dict, health_score: dict, tier: str = "basic") -> dict:
    """Generate a premium assessment report using additional Claude passes.

    tier="basic" ($99): health narrative + tech debt
    tier="full" ($499): + security surface + industry comparison
    """
    arch = analysis_result.get("architecture", {})
    key_files = analysis_result.get("key_files", [])[:15]
    dep_graph = analysis_result.get("dependency_graph", {})
    patterns = analysis_result.get("patterns", [])
    test_files = analysis_result.get("test_files", [])

    context = _build_context(arch, key_files, dep_graph, patterns, test_files, health_score)

    # Pass 5: Health narrative
    health_narrative = _pass5_health_narrative(context, health_score)

    # Pass 6: Tech debt analysis
    tech_debt = _pass6_tech_debt(context)

    result = {
        "executive_summary": health_narrative.get("executive_summary", ""),
        "health_assessment": health_narrative,
        "tech_debt": tech_debt,
        "health_score": health_score,
    }

    if tier == "full":
        # Pass 7: Security surface area
        security = _pass7_security_surface(context)
        result["security_analysis"] = security

        # Industry comparison
        result["recommendations"] = _build_recommendations(
            health_narrative, tech_debt, security, health_score
        )
    else:
        result["recommendations"] = _build_recommendations(
            health_narrative, tech_debt, None, health_score
        )

    return result


def _build_context(arch, key_files, dep_graph, patterns, test_files, health_score) -> str:
    arch_str = json.dumps(arch, indent=2)[:2000]
    files_str = "\n".join(
        f"- {f['path']} (score {f.get('score', 0)}): {f.get('explanation', '')[:150]}"
        for f in key_files
    )
    edges_count = len(dep_graph.get("edges", []))
    patterns_str = "\n".join(
        f"- {p['name']}: {p.get('explanation', '')[:100]}" for p in patterns
    )
    health_str = json.dumps(health_score, indent=2)

    return f"""ARCHITECTURE:
{arch_str}

KEY FILES:
{files_str}

DEPENDENCY GRAPH: {edges_count} edges between source files

PATTERNS:
{patterns_str}

TEST FILES: {len(test_files)} test files detected

HEALTH SCORE:
{health_str}"""


def _pass5_health_narrative(context: str, health_score: dict) -> dict:
    system = (
        "You are a senior software architect producing a professional assessment report. "
        "Be specific, actionable, and balanced (mention both strengths and risks)."
    )
    user = f"""Based on this codebase analysis, write a health assessment narrative.

{context}

Return a JSON object:
{{
  "executive_summary": "3-5 sentence overview suitable for a CTO or investor",
  "strengths": ["list of 3-5 specific strengths with evidence"],
  "risks": ["list of 3-5 specific risks or concerns with evidence"],
  "overall_assessment": "2-3 paragraph professional assessment"
}}

Return only valid JSON."""

    text = _ask(system, user)
    return _extract_json(text)


def _pass6_tech_debt(context: str) -> dict:
    system = (
        "You are a tech debt analyst. Identify specific, actionable tech debt patterns "
        "based on the codebase structure and architecture."
    )
    user = f"""Analyze this codebase for tech debt patterns.

{context}

Return a JSON object:
{{
  "debt_items": [
    {{
      "category": "e.g. Architecture, Testing, Dependencies, Code Quality",
      "severity": "high" | "medium" | "low",
      "description": "specific description of the debt",
      "recommendation": "how to address it",
      "effort": "estimated effort: small | medium | large"
    }}
  ],
  "debt_score": 0-100 (100 = no debt, 0 = critical debt),
  "summary": "1-2 sentence summary of overall tech debt posture"
}}

Return 4-8 debt items. Return only valid JSON."""

    text = _ask(system, user)
    return _extract_json(text)


def _pass7_security_surface(context: str) -> dict:
    system = (
        "You are a security analyst assessing a codebase's attack surface. "
        "Focus on framework usage, dependency risks, and common vulnerability patterns."
    )
    user = f"""Analyze the security surface area of this codebase.

{context}

Return a JSON object:
{{
  "risk_level": "low" | "medium" | "high",
  "attack_surface": [
    {{
      "area": "e.g. Authentication, API endpoints, File uploads, Database queries",
      "risk": "low" | "medium" | "high",
      "description": "what the risk is",
      "mitigation": "how to mitigate"
    }}
  ],
  "dependency_risks": ["list of dependency-related security concerns"],
  "summary": "2-3 sentence security posture summary"
}}

Return only valid JSON."""

    text = _ask(system, user)
    return _extract_json(text)


def _build_recommendations(health_narrative, tech_debt, security, health_score) -> list:
    """Build prioritized recommendations from all assessment data."""
    recs = []

    # From health narrative risks
    for risk in health_narrative.get("risks", []):
        recs.append({"priority": "high", "source": "health", "recommendation": risk})

    # From tech debt items (high severity)
    for item in tech_debt.get("debt_items", []):
        if item.get("severity") == "high":
            recs.append({
                "priority": "high",
                "source": "tech_debt",
                "recommendation": f"{item['description']} — {item.get('recommendation', '')}",
            })

    # From security (if available)
    if security:
        for area in security.get("attack_surface", []):
            if area.get("risk") == "high":
                recs.append({
                    "priority": "high",
                    "source": "security",
                    "recommendation": f"{area['area']}: {area['description']} — {area.get('mitigation', '')}",
                })

    # From low health dimensions
    dims = health_score.get("dimensions", {})
    for dim_key, dim_data in dims.items():
        if dim_data.get("score", 100) < 50:
            recs.append({
                "priority": "medium",
                "source": "health_score",
                "recommendation": f"Improve {dim_data.get('label', dim_key)} (score: {dim_data['score']}/100)",
            })

    return recs
