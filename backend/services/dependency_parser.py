"""
Regex-based import parser. Builds a file dependency graph from source files.
Supports: Python, JavaScript, TypeScript, Go.
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".cs": "csharp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".c": "c",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
}

# Python stdlib modules to skip for absolute import matching
_PY_STDLIB = {
    "os", "sys", "re", "io", "abc", "ast", "csv", "json", "math", "time",
    "uuid", "copy", "enum", "glob", "gzip", "hmac", "http", "logging",
    "random", "shlex", "shutil", "socket", "struct", "typing", "string",
    "hashlib", "pathlib", "urllib", "asyncio", "decimal", "datetime",
    "functools", "operator", "textwrap", "tempfile", "traceback",
    "threading", "multiprocessing", "subprocess", "collections", "itertools",
    "contextlib", "dataclasses", "importlib", "inspect", "warnings", "weakref",
    "unittest", "argparse", "configparser", "base64", "binascii", "codecs",
    "concurrent", "email", "html", "xml", "zipfile", "tarfile", "sqlite3",
}


def detect_language(path: str) -> str:
    return LANG_MAP.get(Path(path).suffix.lower(), "other")


# ── Python ────────────────────────────────────────────────────────────────────

def _parse_python(path: str, content: str, all_files: set[str]) -> list[str]:
    targets: list[str] = []
    importer_dir = str(Path(path).parent).replace("\\", "/")
    if importer_dir == ".":
        importer_dir = ""

    # Relative imports: `from .x import y` / `from ..x import y`
    for m in re.finditer(r"^from\s+(\.+)([\w.]*)\s+import", content, re.MULTILINE):
        dots = len(m.group(1))
        module_tail = m.group(2)

        parts = importer_dir.split("/") if importer_dir else []
        # Navigate up (dots-1) levels
        base_parts = parts[: max(0, len(parts) - (dots - 1))]
        candidate_parts = base_parts + module_tail.split(".") if module_tail else base_parts

        base = "/".join(candidate_parts)
        for c in [f"{base}.py", f"{base}/__init__.py"]:
            if c in all_files:
                targets.append(c)
                break

    # Absolute imports: try to match against file tree
    for m in re.finditer(r"^(?:from|import)\s+([\w.]+)", content, re.MULTILINE):
        module = m.group(1)
        root = module.split(".")[0]
        if root in _PY_STDLIB:
            continue
        parts = module.split(".")
        for c in ["/".join(parts) + ".py", "/".join(parts) + "/__init__.py"]:
            if c in all_files:
                targets.append(c)
                break

    return targets


# ── JavaScript / TypeScript ───────────────────────────────────────────────────

def _detect_aliases(files: dict[str, str]) -> dict[str, list[str]]:
    """Read tsconfig/jsconfig paths to resolve non-relative aliases."""
    aliases: dict[str, list[str]] = {
        "@/": ["src/", ""],
        "~/": ["src/", ""],
        "@components/": ["components/", "src/components/"],
        "@lib/": ["lib/", "src/lib/"],
        "@utils/": ["utils/", "src/utils/"],
    }
    for fname in ("tsconfig.json", "jsconfig.json"):
        if fname in files:
            try:
                cfg = json.loads(files[fname])
                paths = cfg.get("compilerOptions", {}).get("paths", {})
                for alias_pat, targets in paths.items():
                    clean = alias_pat.rstrip("/*")
                    if clean:
                        resolved = [t.lstrip("./").rstrip("/*") + "/" for t in targets]
                        aliases[clean + "/"] = resolved
            except Exception:
                pass
    return aliases


_JS_EXTENSIONS = ["", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js", "/index.jsx"]


def _parse_js(path: str, content: str, all_files: set[str], aliases: dict[str, list[str]]) -> list[str]:
    targets: list[str] = []
    importer_dir = str(Path(path).parent).replace("\\", "/")
    if importer_dir == ".":
        importer_dir = ""

    raw: list[str] = []
    # import ... from '...' or "..."
    raw += re.findall(r"""import\s+(?:type\s+)?(?:[\s\S]*?\s+from\s+)?['"]([^'"]+)['"]""", content)
    # export ... from '...'
    raw += re.findall(r"""export\s+(?:[\s\S]*?\s+from\s+)?['"]([^'"]+)['"]""", content)
    # require('...')
    raw += re.findall(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", content)

    for imp in raw:
        if imp.startswith("."):
            # Relative
            if importer_dir:
                base = os.path.normpath(os.path.join(importer_dir, imp)).replace("\\", "/")
            else:
                base = imp.lstrip("./")
            for ext in _JS_EXTENSIONS:
                c = base + ext
                if c in all_files:
                    targets.append(c)
                    break
        else:
            # Try known aliases
            for prefix, replacements in aliases.items():
                if imp.startswith(prefix):
                    rest = imp[len(prefix):]
                    for rep in replacements:
                        base = (rep + rest).lstrip("/")
                        for ext in _JS_EXTENSIONS:
                            c = base + ext
                            if c in all_files:
                                targets.append(c)
                                break
                        else:
                            continue
                        break
                    break

    return targets


# ── Go ────────────────────────────────────────────────────────────────────────

def _detect_go_module(files: dict[str, str]) -> str:
    content = files.get("go.mod", "")
    m = re.search(r"^module\s+(\S+)", content, re.MULTILINE)
    return m.group(1) if m else ""


def _parse_go(path: str, content: str, all_files: set[str], module_name: str) -> list[str]:
    if not module_name:
        return []
    targets: list[str] = []
    imports: list[str] = []

    imports += re.findall(r'import\s+"([^"]+)"', content)
    block = re.search(r"import\s*\(([\s\S]*?)\)", content)
    if block:
        imports += re.findall(r'"([^"]+)"', block.group(1))

    for imp in imports:
        if imp.startswith(module_name + "/"):
            pkg = imp[len(module_name) + 1:]  # e.g. "internal/handler"
            # A Go package maps to a directory — find any .go file in that dir
            for f in all_files:
                if f.startswith(pkg + "/") and f.endswith(".go"):
                    targets.append(f)
                    break

    return targets


# ── Public API ────────────────────────────────────────────────────────────────

def parse_dependencies(files: dict[str, str], tree: list[str]) -> dict:
    """
    Parse import statements across all readable files and build a
    directed dependency graph.

    Returns:
        {
          "nodes": [{"id": path, "label": filename, "language": lang}, ...],
          "edges": [{"source": path, "target": path}, ...],
        }
    """
    all_files: set[str] = set(tree)
    aliases = _detect_aliases(files)
    go_module = _detect_go_module(files)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_set: set[tuple[str, str]] = set()

    def ensure_node(p: str) -> None:
        if p not in nodes:
            nodes[p] = {
                "id": p,
                "label": Path(p).name,
                "language": detect_language(p),
            }

    for path, content in files.items():
        lang = detect_language(path)
        if lang == "other":
            continue

        ensure_node(path)

        if lang == "python":
            raw_targets = _parse_python(path, content, all_files)
        elif lang in ("javascript", "typescript"):
            raw_targets = _parse_js(path, content, all_files, aliases)
        elif lang == "go":
            raw_targets = _parse_go(path, content, all_files, go_module)
        else:
            raw_targets = []

        for target in raw_targets:
            if target == path:
                continue
            ensure_node(target)
            key = (path, target)
            if key not in edge_set:
                edge_set.add(key)
                edges.append({"source": path, "target": target})

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
    }
