"""Tests for the regex-based import/dependency parser."""
import pytest
from services.dependency_parser import detect_language, parse_dependencies


class TestDetectLanguage:
    @pytest.mark.parametrize("path,expected", [
        ("main.py",          "python"),
        ("app.js",           "javascript"),
        ("index.jsx",        "javascript"),
        ("index.mjs",        "javascript"),
        ("page.ts",          "typescript"),
        ("component.tsx",    "typescript"),
        ("main.go",          "go"),
        ("lib.rs",           "rust"),
        ("app.rb",           "ruby"),
        ("Main.java",        "java"),
        ("Program.cs",       "csharp"),
        ("main.cpp",         "cpp"),
        ("main.c",           "c"),
        ("App.swift",        "swift"),
        ("Main.kt",          "kotlin"),
        ("unknown.xyz",      "other"),
        ("no_extension",     "other"),
    ])
    def test_language_detection(self, path, expected):
        assert detect_language(path) == expected


class TestParseDependencies:
    def test_returns_nodes_and_edges(self):
        files = {"main.py": "x = 1"}
        result = parse_dependencies(files, list(files.keys()))
        assert "nodes" in result
        assert "edges" in result

    def test_nodes_have_correct_fields(self):
        files = {"main.py": "x = 1", "app.js": "const x = 1"}
        result = parse_dependencies(files, list(files.keys()))
        nodes = {n["id"]: n for n in result["nodes"]}
        assert nodes["main.py"]["language"] == "python"
        assert nodes["app.js"]["language"] == "javascript"
        assert "label" in nodes["main.py"]

    def test_empty_input(self):
        result = parse_dependencies({}, [])
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_no_self_edges(self):
        files = {"main.py": "from main import something"}
        result = parse_dependencies(files, list(files.keys()))
        assert not any(e["source"] == e["target"] for e in result["edges"])

    # ── Python ────────────────────────────────────────────────────────────────

    def test_python_absolute_import(self):
        files = {
            "main.py": "from services.auth import login",
            "services/auth.py": "def login(): pass",
        }
        result = parse_dependencies(files, list(files.keys()))
        edges = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("main.py", "services/auth.py") in edges

    def test_python_import_statement(self):
        files = {
            "main.py": "import models",
            "models.py": "class User: pass",
        }
        result = parse_dependencies(files, list(files.keys()))
        edges = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("main.py", "models.py") in edges

    def test_python_relative_import(self):
        files = {
            "services/auth.py": "from .helpers import hash_pw",
            "services/helpers.py": "def hash_pw(p): pass",
        }
        result = parse_dependencies(files, list(files.keys()))
        edges = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("services/auth.py", "services/helpers.py") in edges

    def test_python_stdlib_excluded(self):
        files = {
            "main.py": "import os\nimport sys\nimport re\nfrom pathlib import Path\nfrom datetime import datetime",
        }
        result = parse_dependencies(files, list(files.keys()))
        # No edges expected — all imports are stdlib
        assert result["edges"] == []

    def test_python_third_party_not_in_tree_excluded(self):
        files = {
            "main.py": "import fastapi\nimport sqlalchemy",
        }
        result = parse_dependencies(files, list(files.keys()))
        # fastapi/sqlalchemy not in file tree → no edges
        assert result["edges"] == []

    # ── JavaScript / TypeScript ───────────────────────────────────────────────

    def test_js_relative_import(self):
        files = {
            "src/app.js": "import { helper } from './utils'",
            "src/utils.js": "export const helper = () => {}",
        }
        result = parse_dependencies(files, list(files.keys()))
        edges = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("src/app.js", "src/utils.js") in edges

    def test_ts_relative_import(self):
        files = {
            "src/page.tsx": "import { Button } from './components/Button'",
            "src/components/Button.tsx": "export const Button = () => null",
        }
        result = parse_dependencies(files, list(files.keys()))
        edges = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("src/page.tsx", "src/components/Button.tsx") in edges

    def test_js_require(self):
        files = {
            "server.js": "const db = require('./database')",
            "database.js": "module.exports = {}",
        }
        result = parse_dependencies(files, list(files.keys()))
        edges = {(e["source"], e["target"]) for e in result["edges"]}
        assert ("server.js", "database.js") in edges

    # ── Go ────────────────────────────────────────────────────────────────────

    def test_go_import(self):
        files = {
            "main.go": 'import "myapp/handlers"',
            "handlers/handler.go": "package handlers",
        }
        result = parse_dependencies(files, list(files.keys()))
        # Go import matching is path-based; just ensure no crash
        assert "nodes" in result

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_file_with_no_imports(self):
        files = {"utils.py": "def add(a, b):\n    return a + b"}
        result = parse_dependencies(files, list(files.keys()))
        assert result["edges"] == []

    def test_multiple_imports_same_file(self):
        files = {
            "main.py": "from auth import login\nfrom models import User",
            "auth.py": "def login(): pass",
            "models.py": "class User: pass",
        }
        result = parse_dependencies(files, list(files.keys()))
        sources = [e["source"] for e in result["edges"]]
        assert sources.count("main.py") >= 2
