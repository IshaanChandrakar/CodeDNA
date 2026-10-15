"""Original installation smoke tests retained alongside the frontend suite."""

from importlib import import_module

import pytest


@pytest.mark.parametrize(
    "package",
    ["compiler", "transformations", "runtime", "fingerprint", "visualization"],
)
def test_project_package_imports(package: str) -> None:
    """The editable installation exposes each planned package."""
    module = import_module(package)
    assert module.__file__ is not None


@pytest.mark.parametrize("module", ["ply.lex", "ply.yacc", "graphviz"])
def test_frontend_dependency_imports(module: str) -> None:
    """The initial frontend and graph bindings can be imported."""
    import_module(module)
