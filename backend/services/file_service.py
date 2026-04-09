import os
import re
from pathlib import Path
from typing import Any

# Patterns that identify test/spec files
_TEST_PATTERNS = [
    re.compile(r"(?:^|/)test_[^/]+\.py$"),
    re.compile(r"(?:^|/)[^/]+_test\.py$"),
    re.compile(r"[^/]+\.(?:test|spec)\.(?:js|jsx|ts|tsx|mjs|cjs)$"),
    re.compile(r"(?:^|/)(?:tests?|__tests__|spec|specs)/"),
    re.compile(r"(?:^|/)conftest\.py$"),
    re.compile(r"(?:^|/)[^/]+_spec\.rb$"),   # Ruby RSpec files anywhere
    re.compile(r"(?:^|/)[^/]+_test\.go$"),   # Go test files
    re.compile(r"(?:^|/)[^/]+Test\.java$"),  # JUnit test classes
    re.compile(r"(?:^|/)[^/]+Tests?\.cs$"),  # C# test classes
]


def is_test_file(path: str) -> bool:
    """Return True if path looks like a test or spec file."""
    p = path.replace("\\", "/")
    return any(pat.search(p) for pat in _TEST_PATTERNS)

# Directories to skip entirely (exact name match, case-sensitive)
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".next", "dist", "build",
    ".venv", "venv", "env", "vendor", "target", ".cache",
    "coverage", ".nyc_output", ".pytest_cache", ".mypy_cache",
    "eggs", ".tox", "htmlcov", ".idea", ".vscode",
    ".DS_Store", "Thumbs.db", ".gradle", ".m2", "bin", "obj",
    "Pods", "DerivedData", "__MACOSX",
    # Note: "*.egg-info" (glob) is intentionally NOT here — it never matched.
    # The endswith(".egg-info") check below handles those directories.
}

# File names that contain secrets and must never be read, regardless of extension.
# .env.example and .env.sample are intentionally excluded (safe template files).
_SECRET_FILE_NAMES = {".env"}


def _is_secret_file(name: str) -> bool:
    """Return True if the file name looks like a secrets/env file that should not be read."""
    n = name.lower()
    # Block .env, .env.local, .env.production, .env.staging, .env.development, etc.
    # Allow .env.example and .env.sample (safe template files).
    if n == ".env" or (n.startswith(".env.") and not n.endswith((".example", ".sample"))):
        return True
    return False

# Binary / media file extensions to skip reading
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".bmp",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    ".whl", ".egg", ".pyc", ".pyo", ".class", ".jar", ".war",
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib", ".o",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm",
    ".ttf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".sqlite3",
    ".lock",  # skip lockfiles from content reads (they are listed in tree)
}

# Config / manifest files we always try to read (by exact name)
PRIORITY_NAMES = {
    "readme.md", "readme.rst", "readme.txt", "readme",
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "requirements.txt", "pipfile", "gemfile",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", ".env.sample",
    "makefile", "justfile",
    "tsconfig.json", "jsconfig.json",
    "next.config.js", "next.config.ts", "next.config.mjs",
    "vite.config.js", "vite.config.ts",
    "webpack.config.js",
    "tailwind.config.js", "tailwind.config.ts",
    "eslint.config.js", ".eslintrc", ".eslintrc.json", ".eslintrc.js",
    "prettier.config.js", ".prettierrc",
    "babel.config.js", ".babelrc",
    "jest.config.js", "jest.config.ts",
    "vitest.config.js", "vitest.config.ts",
    ".github/workflows",
}

MAX_FILE_SIZE = 80_000   # bytes — truncate larger files
MAX_DEP_FILE_READ = 4096 # bytes per file for dep parsing (imports are at the top)

# Per-plan limits
_LIMITS = {
    "free": dict(max_tree=300, max_read=60,  max_dep=500),
    "pro":  dict(max_tree=600, max_read=100, max_dep=1000),
}

# Keep module-level names for backward compat
MAX_TREE_FILES = _LIMITS["free"]["max_tree"]
MAX_READ_FILES = _LIMITS["free"]["max_read"]
MAX_DEP_FILES  = _LIMITS["free"]["max_dep"]

def _safe_path(root: str, rel_path: str) -> str | None:
    """Return the absolute path if it stays inside root, else None."""
    full = os.path.realpath(os.path.join(root, rel_path))
    if not full.startswith(os.path.realpath(root) + os.sep):
        return None
    if os.path.islink(os.path.join(root, rel_path)):
        return None
    return full


# Source file extensions eligible for import parsing
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".mts", ".cts",
    ".go", ".rs", ".rb", ".java", ".cs",
    ".cpp", ".cc", ".cxx", ".c", ".php", ".swift", ".kt",
}


def walk_repo(root: str, plan: str = "free") -> dict[str, Any]:
    """
    Walk the repo and return:
      - tree: list of relative file paths (strings)
      - files: dict of {rel_path: content_str} for readable files

    plan: "free" | "pro" — controls how many files are read/indexed.
    """
    lim = _LIMITS.get(plan, _LIMITS["free"])
    max_tree = lim["max_tree"]
    max_read = lim["max_read"]
    max_dep  = lim["max_dep"]

    root_path = Path(root)
    tree = []
    files: dict[str, str] = {}

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)

        # Prune skip dirs and symlinked dirs in-place so os.walk doesn't descend
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS
            and not d.startswith(".")
            and not d.endswith(".egg-info")
            and not os.path.islink(os.path.join(dirpath, d))
        ]
        dirnames.sort()

        for fname in sorted(filenames):
            full = os.path.join(dirpath, fname)
            # Skip symlinks — a malicious repo could symlink to server files
            if os.path.islink(full):
                continue
            rel_path = os.path.join(rel_dir, fname).replace("\\", "/")
            if rel_path.startswith("./"):
                rel_path = rel_path[2:]

            if len(tree) < max_tree:
                tree.append(rel_path)

    # Decide which files to read
    priority = []
    secondary = []
    for p in tree:
        fname = Path(p).name
        fname_lower = fname.lower()
        if _is_secret_file(fname):
            continue  # Never read secret/env files — they may contain API keys
        if fname_lower in PRIORITY_NAMES or Path(p).suffix.lower() in {".md", ".rst"}:
            priority.append(p)
        elif Path(p).suffix.lower() not in BINARY_EXTENSIONS:
            secondary.append(p)

    # Read priority files first, then fill up with secondary
    to_read = priority[:max_read]
    remaining_slots = max_read - len(to_read)
    to_read += secondary[:remaining_slots]

    for rel_path in to_read:
        ext = Path(rel_path).suffix.lower()
        if ext in BINARY_EXTENSIONS:
            continue
        full_path = _safe_path(root, rel_path)
        if not full_path:
            continue
        try:
            size = os.path.getsize(full_path)
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(MAX_FILE_SIZE)
            if size > MAX_FILE_SIZE:
                content += f"\n\n[... file truncated at {MAX_FILE_SIZE} bytes ...]"
            files[rel_path] = content
        except Exception:
            pass

    # Build dep_files: read ALL source files (up to max_dep) but only
    # the first MAX_DEP_FILE_READ bytes each — import statements are always
    # at the top of the file so this is sufficient for dependency parsing.
    dep_candidates = [
        p for p in tree
        if Path(p).suffix.lower() in _SOURCE_EXTENSIONS
        and not _is_secret_file(Path(p).name)
    ]
    dep_files: dict[str, str] = {}
    for rel_path in dep_candidates[:max_dep]:
        # Reuse already-read content if available (no extra disk I/O)
        if rel_path in files:
            dep_files[rel_path] = files[rel_path]
            continue
        full_path = _safe_path(root, rel_path)
        if not full_path:
            continue
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                dep_files[rel_path] = f.read(MAX_DEP_FILE_READ)
        except Exception:
            pass

    test_files = [p for p in tree if is_test_file(p)]

    return {"tree": tree, "files": files, "dep_files": dep_files, "test_files": test_files}


def format_tree(tree: list[str]) -> str:
    """Format file list as an indented tree string."""
    lines = []
    for path in tree:
        parts = path.split("/")
        indent = "  " * (len(parts) - 1)
        lines.append(f"{indent}{parts[-1]}")
    return "\n".join(lines)


def get_readme(files: dict[str, str]) -> str:
    for key in files:
        if Path(key).name.lower() in {"readme.md", "readme.rst", "readme.txt", "readme"}:
            return files[key]
    return ""


def get_config_files(files: dict[str, str]) -> dict[str, str]:
    """Return only config/manifest files."""
    result = {}
    for path, content in files.items():
        name_lower = Path(path).name.lower()
        if name_lower in PRIORITY_NAMES:
            result[path] = content
    return result
