"""A second top-level class or function with the same name silently replaces the first. Two
stories merged cleanly that way and a customer endpoint returned 500 with every test green."""

import ast
from collections import Counter
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"


@pytest.mark.parametrize("path", sorted(APP.rglob("*.py")), ids=lambda p: str(p.relative_to(APP)))
def test_a_module_defines_each_top_level_name_once(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = Counter(
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    )
    assert [n for n, c in names.items() if c > 1] == []
