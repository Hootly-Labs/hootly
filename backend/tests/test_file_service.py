"""Tests for file_service: test detection, walk_repo, format helpers."""
import pytest
from pathlib import Path

from services.file_service import (
    format_tree,
    get_config_files,
    get_readme,
    is_test_file,
    walk_repo,
)


class TestIsTestFile:
    @pytest.mark.parametrize("path,expected", [
        # Should be detected as test files
        ("test_main.py",                  True),
        ("test_routes.py",                True),
        ("main_test.py",                  True),
        ("routes_test.py",                True),
        ("tests/test_routes.py",          True),
        ("tests/test_auth.py",            True),
        ("__tests__/api.test.ts",         True),
        ("__tests__/Button.test.tsx",     True),
        ("src/api.test.js",               True),
        ("src/api.spec.ts",               True),
        ("conftest.py",                   True),
        ("src/conftest.py",               True),
        ("spec/models_spec.rb",           True),
        # Should NOT be detected as test files
        ("main.py",                       False),
        ("routes.py",                     False),
        ("models/user.py",                False),
        ("components/Button.tsx",         False),
        ("services/auth.ts",              False),
        ("attest.py",                     False),  # contains 'test' but isn't one
        ("protest.py",                    False),
        ("latest.py",                     False),
        ("contest/app.py",                False),
    ])
    def test_detection(self, path, expected):
        assert is_test_file(path) == expected


class TestWalkRepo:
    def test_basic_files_in_tree(self, tmp_path):
        (tmp_path / "main.py").write_text("x = 1")
        (tmp_path / "utils.py").write_text("def f(): pass")
        result = walk_repo(str(tmp_path))
        assert "main.py" in result["tree"]
        assert "utils.py" in result["tree"]

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "lodash.js").write_text("")
        (tmp_path / "index.js").write_text("const x = 1")
        result = walk_repo(str(tmp_path))
        assert not any("node_modules" in p for p in result["tree"])
        assert "index.js" in result["tree"]

    def test_skips_dot_directories(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("")
        (tmp_path / "main.py").write_text("x = 1")
        result = walk_repo(str(tmp_path))
        assert not any(".git" in p for p in result["tree"])

    def test_skips_pycache(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"")
        (tmp_path / "main.py").write_text("x = 1")
        result = walk_repo(str(tmp_path))
        assert not any("__pycache__" in p for p in result["tree"])

    def test_test_files_listed(self, tmp_path):
        (tmp_path / "test_main.py").write_text("def test_x(): pass")
        (tmp_path / "main.py").write_text("x = 1")
        result = walk_repo(str(tmp_path))
        assert "test_main.py" in result["test_files"]
        assert "main.py" not in result["test_files"]

    def test_file_content_read(self, tmp_path):
        content = "def hello(): return 'world'"
        (tmp_path / "hello.py").write_text(content)
        result = walk_repo(str(tmp_path))
        assert result["files"]["hello.py"] == content

    def test_binary_files_in_tree_not_in_files(self, tmp_path):
        (tmp_path / "logo.png").write_bytes(b"\x89PNG")
        (tmp_path / "main.py").write_text("x = 1")
        result = walk_repo(str(tmp_path))
        assert "logo.png" in result["tree"]
        assert "logo.png" not in result["files"]

    def test_priority_files_always_read(self, tmp_path):
        (tmp_path / "README.md").write_text("# Project")
        (tmp_path / "package.json").write_text('{"name":"test"}')
        for i in range(100):
            (tmp_path / f"file{i}.py").write_text(f"x = {i}")
        result = walk_repo(str(tmp_path))
        assert "README.md" in result["files"]
        assert "package.json" in result["files"]

    def test_dep_files_populated(self, tmp_path):
        (tmp_path / "main.py").write_text("import os")
        (tmp_path / "app.ts").write_text("import React from 'react'")
        result = walk_repo(str(tmp_path))
        assert "main.py" in result["dep_files"]
        assert "app.ts" in result["dep_files"]

    def test_returns_all_expected_keys(self, tmp_path):
        result = walk_repo(str(tmp_path))
        assert set(result.keys()) >= {"tree", "files", "dep_files", "test_files"}

    def test_nested_directory_structure(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "api").mkdir()
        (tmp_path / "src" / "api" / "routes.py").write_text("from fastapi import APIRouter")
        result = walk_repo(str(tmp_path))
        assert "src/api/routes.py" in result["tree"]

    def test_large_file_truncated(self, tmp_path):
        big_content = "x = 1\n" * 20_000  # > 80KB
        (tmp_path / "big.py").write_text(big_content)
        result = walk_repo(str(tmp_path))
        if "big.py" in result["files"]:
            assert "truncated" in result["files"]["big.py"]


class TestFormatTree:
    def test_flat_files(self):
        result = format_tree(["main.py", "utils.py"])
        assert "main.py" in result
        assert "utils.py" in result

    def test_nested_files_indented(self):
        result = format_tree(["src/main.py", "src/utils/helper.py"])
        lines = result.splitlines()
        main_line = next(l for l in lines if "main.py" in l)
        helper_line = next(l for l in lines if "helper.py" in l)
        # helper is 2 levels deep, should be more indented
        assert len(helper_line) - len(helper_line.lstrip()) > len(main_line) - len(main_line.lstrip())

    def test_empty_tree(self):
        result = format_tree([])
        assert result == ""


class TestGetReadme:
    def test_finds_readme_md(self):
        files = {"README.md": "# Hello", "main.py": "x = 1"}
        assert get_readme(files) == "# Hello"

    def test_finds_readme_case_insensitive(self):
        files = {"readme.md": "# Lower"}
        assert get_readme(files) == "# Lower"

    def test_finds_readme_rst(self):
        files = {"README.rst": "Hello\n====="}
        assert get_readme(files) == "Hello\n====="

    def test_returns_empty_if_no_readme(self):
        files = {"main.py": "x = 1", "utils.py": "pass"}
        assert get_readme(files) == ""


class TestGetConfigFiles:
    def test_returns_package_json(self):
        files = {"package.json": '{"name":"test"}', "main.js": "const x = 1"}
        result = get_config_files(files)
        assert "package.json" in result
        assert "main.js" not in result

    def test_returns_requirements_txt(self):
        files = {"requirements.txt": "fastapi\nuvicorn", "app.py": "x = 1"}
        result = get_config_files(files)
        assert "requirements.txt" in result

    def test_empty_when_no_configs(self):
        files = {"main.py": "x = 1", "utils.py": "pass"}
        result = get_config_files(files)
        assert result == {}
