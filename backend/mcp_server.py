"""Hootly MCP Server — exposes analysis tools for Claude Code, Cursor, etc.

Run standalone: python mcp_server.py
Communicates over stdin/stdout using the MCP protocol (JSON-RPC).
"""
import json
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

# MCP protocol version
MCP_VERSION = "2024-11-05"

# API key for authenticating requests (set via HOOTLY_API_KEY env var)
HOOTLY_API_KEY = os.getenv("HOOTLY_API_KEY", "")


def _read_message() -> dict | None:
    """Read a JSON-RPC message from stdin."""
    # MCP uses Content-Length headers like LSP
    headers = {}
    while True:
        line = sys.stdin.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    content_length = int(headers.get("Content-Length", "0"))
    if content_length == 0:
        return None

    body = sys.stdin.read(content_length)
    return json.loads(body)


def _send_message(msg: dict):
    """Send a JSON-RPC message to stdout."""
    body = json.dumps(msg)
    sys.stdout.write(f"Content-Length: {len(body)}\r\n\r\n{body}")
    sys.stdout.flush()


def _send_result(id: int | str, result: dict):
    _send_message({"jsonrpc": "2.0", "id": id, "result": result})


def _send_error(id: int | str, code: int, message: str):
    _send_message({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


# ── Tool implementations ──────────────────────────────────────────────────────

def _check_auth() -> str | None:
    """Verify HOOTLY_API_KEY is set and valid. Returns user_id or None.

    Returns None if no key is configured (unauthenticated local use).
    Returns user_id if key is valid.
    Raises ValueError if key is configured but invalid.
    """
    if not HOOTLY_API_KEY:
        return None  # no auth configured, allow unauthenticated
    from database import SessionLocal
    from services.auth_service import get_user_by_api_key
    db = SessionLocal()
    try:
        user = get_user_by_api_key(HOOTLY_API_KEY, db)
        if user:
            return user.id
        raise ValueError("Invalid HOOTLY_API_KEY. Check your API key in settings.")
    finally:
        db.close()


def _tool_analyze_repo(url: str) -> dict:
    """Trigger analysis of a GitHub repo and return the analysis ID."""
    from database import SessionLocal
    from models import Analysis
    from api.routes import _do_analysis
    import threading

    try:
        user_id = _check_auth()
    except ValueError as e:
        return {"error": str(e)}

    db = SessionLocal()
    try:
        from services.git_service import parse_github_url
        owner, repo = parse_github_url(url)
        repo_name = f"{owner}/{repo}"
        canonical_url = f"https://github.com/{owner}/{repo}"

        analysis = Analysis(
            repo_url=canonical_url,
            repo_name=repo_name,
            status="pending",
            stage="Queued (MCP)",
            user_id=user_id,
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)

        t = threading.Thread(target=_do_analysis, args=(analysis.id,), daemon=True)
        t.start()

        return {
            "analysis_id": analysis.id,
            "status": "pending",
            "message": f"Analysis queued for {repo_name}. Check status with analysis_id.",
        }
    except ValueError as e:
        return {"error": str(e)}
    finally:
        db.close()


def _tool_get_analysis(analysis_id: str) -> dict:
    """Get the status and result of an analysis."""
    try:
        _check_auth()
    except ValueError as e:
        return {"error": str(e)}

    from database import SessionLocal
    from models import Analysis

    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis:
            return {"error": "Analysis not found"}

        result = {
            "id": analysis.id,
            "repo_name": analysis.repo_name,
            "status": analysis.status,
            "stage": analysis.stage,
        }

        if analysis.status == "completed" and analysis.result:
            parsed = json.loads(analysis.result)
            arch = parsed.get("architecture", {})
            result["architecture"] = {
                "type": arch.get("architecture_type", ""),
                "summary": arch.get("architecture_summary", ""),
                "stack": arch.get("tech_stack", []),
            }
            result["key_files"] = [
                {"path": f["path"], "score": f.get("score", 0), "reason": f.get("reason", "")}
                for f in parsed.get("key_files", [])[:10]
            ]
            result["quick_start"] = parsed.get("quick_start", "")

        if analysis.health_score:
            try:
                result["health_score"] = json.loads(analysis.health_score)
            except Exception:
                pass

        if analysis.error_message:
            result["error_message"] = analysis.error_message

        return result
    finally:
        db.close()


def _tool_query_analysis(analysis_id: str, question: str) -> dict:
    """Ask a question about an analyzed repo using the chat service."""
    try:
        _check_auth()
    except ValueError as e:
        return {"error": str(e)}

    from database import SessionLocal
    from models import Analysis
    from services.chat_service import build_system_prompt

    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis or analysis.status != "completed" or not analysis.result:
            return {"error": "Analysis not found or not completed"}

        result = json.loads(analysis.result)
        system_prompt = build_system_prompt(result)

        from anthropic import Anthropic
        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

        msg = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": question}],
        )

        return {"answer": msg.content[0].text}
    finally:
        db.close()


def _tool_get_health_score(url: str) -> dict:
    """Get the health score for a repo (must be previously analyzed)."""
    try:
        _check_auth()
    except ValueError as e:
        return {"error": str(e)}

    from database import SessionLocal
    from models import Analysis
    from services.git_service import parse_github_url

    db = SessionLocal()
    try:
        owner, repo = parse_github_url(url)
        canonical_url = f"https://github.com/{owner}/{repo}"

        analysis = (
            db.query(Analysis)
            .filter(Analysis.repo_url == canonical_url, Analysis.status == "completed")
            .order_by(Analysis.created_at.desc())
            .first()
        )

        if not analysis:
            return {"error": "No completed analysis found. Run analyze_repo first."}

        if analysis.health_score:
            return json.loads(analysis.health_score)

        return {"error": "Health score not available for this analysis."}
    except ValueError as e:
        return {"error": str(e)}
    finally:
        db.close()


# ── MCP Protocol handler ─────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "analyze_repo",
        "description": "Analyze a GitHub repository and generate an onboarding guide with architecture overview, key files, and dependency graph. Requires HOOTLY_API_KEY environment variable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "GitHub repository URL (e.g. https://github.com/owner/repo)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_analysis",
        "description": "Get the status and result of a previously started analysis. Requires HOOTLY_API_KEY environment variable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "analysis_id": {"type": "string", "description": "The analysis ID returned by analyze_repo"},
            },
            "required": ["analysis_id"],
        },
    },
    {
        "name": "query_analysis",
        "description": "Ask a question about an analyzed codebase. The analysis must be completed first. Requires HOOTLY_API_KEY environment variable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "analysis_id": {"type": "string", "description": "The analysis ID"},
                "question": {"type": "string", "description": "Question about the codebase"},
            },
            "required": ["analysis_id", "question"],
        },
    },
    {
        "name": "get_health_score",
        "description": "Get the architecture health score (A-F grade) for a previously analyzed repo. Requires HOOTLY_API_KEY environment variable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "GitHub repository URL"},
            },
            "required": ["url"],
        },
    },
]


def handle_request(msg: dict):
    method = msg.get("method", "")
    id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        _send_result(id, {
            "protocolVersion": MCP_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "hootly", "version": "1.0.0"},
        })
    elif method == "notifications/initialized":
        pass  # no response needed
    elif method == "tools/list":
        _send_result(id, {"tools": TOOLS})
    elif method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        try:
            if tool_name == "analyze_repo":
                result = _tool_analyze_repo(args["url"])
            elif tool_name == "get_analysis":
                result = _tool_get_analysis(args["analysis_id"])
            elif tool_name == "query_analysis":
                result = _tool_query_analysis(args["analysis_id"], args["question"])
            elif tool_name == "get_health_score":
                result = _tool_get_health_score(args["url"])
            else:
                _send_error(id, -32601, f"Unknown tool: {tool_name}")
                return

            _send_result(id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            })
        except Exception as exc:
            _send_result(id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                "isError": True,
            })
    else:
        if id is not None:
            _send_error(id, -32601, f"Unknown method: {method}")


def main():
    """Main loop — read JSON-RPC messages from stdin, handle them."""
    logger.info("Hootly MCP server starting...")

    # Initialize database
    from database import init_db
    init_db()

    while True:
        msg = _read_message()
        if msg is None:
            break
        handle_request(msg)


if __name__ == "__main__":
    main()
