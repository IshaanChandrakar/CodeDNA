"""Real AST/CFG graph structure, safe DOT and optional external rendering."""

from dataclasses import replace
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from compiler.ast_nodes import walk
from compiler.cfg import BasicBlock, ControlFlowGraph, Edge, EdgeKind, build_cfg
from compiler.ir import lower_ir
from compiler.parser import parse
from visualization import graph_renderer
from visualization.graph_renderer import (
    GraphRenderError, GraphvizUnavailableError, ast_to_dot, cfg_to_dot, render,
)


SOURCE = """int main(void) {
    int total = 0;
    for (int i = 0; i < 4; i = i + 1) {
        if (i != 0) total = total + -i;
        else ;
    }
    if (total > 3) return total;
    else return 0;
}
"""


def _outside_strings(dot):
    """Keep DOT syntax while removing its quoted strings, respecting escapes."""
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', dot)


def test_ast_diagram_retains_real_hierarchy_child_roles_values_and_operators():
    program = parse(SOURCE)
    dot = ast_to_dot(program)
    for kind in {type(node).__name__ for node in walk(program)}:
        assert f'label="{kind}' in dot
    for label in (
        "function", "body", "items[0]", "initializer", "condition", "update",
        "then_branch", "else_branch", "target", "value", "operand", "left", "right",
    ):
        assert f'[label="{label}"]' in dot
    for scalar in (
        "name = main", "name = total", "value = 4", "operator = <",
        "operator = !=", "operator = +", "operator = -",
    ):
        assert scalar in dot
    # Every non-root syntax node is connected by its actual child relationship.
    assert dot.count(" -> ") == len(tuple(walk(program))) - 1


def test_ast_diagram_can_show_source_positions_without_modifying_the_ast():
    program = parse("int main(){\n  return 12;\n}")
    before = tuple(walk(program))
    assert "at 2:3 to 2:13" in ast_to_dot(program, include_spans=True)
    assert "at 2:3" not in ast_to_dot(program)
    assert tuple(walk(program)) == before


def test_ast_diagram_escapes_labels_and_never_uses_source_ids_as_dot_syntax():
    program = parse("int main(){return 0;}")
    attack = '"]; injected -> cfg_exit [label="oops\\N\nsecond line\r\t\x01'
    program = replace(
        program,
        node_id=attack,
        function=replace(program.function, name=attack, node_id=attack),
    )
    dot = ast_to_dot(program)
    assert "injected" in dot
    assert "injected" not in _outside_strings(dot)
    assert r'\"' in dot and r"\\N" in dot
    assert "\x01" not in dot and "\r" not in dot
    assert "\nsecond line" not in dot


def test_cfg_diagram_shows_actual_basic_blocks_instructions_and_edge_kinds():
    cfg = build_cfg(lower_ir(parse(SOURCE)))
    dot = cfg_to_dot(cfg)
    assert 'cfg_entry [shape=oval, label="entry"]' in dot
    assert 'cfg_exit [shape=oval, label="exit"]' in dot
    assert "total" in dot and "return" in dot
    assert " != " in dot and " < " in dot and " + " in dot
    assert dot.count(" -> ") == len(cfg.edges)
    for kind in ("entry", "true", "false", "jump", "return"):
        assert f'[label="{kind}"]' in dot
    # Graph node references match the CFG's precise connectivity, including
    # loop jumps and return-to-exit edges, rather than source-level guesses.
    identities = {cfg.entry: "cfg_entry", cfg.exit: "cfg_exit"}
    identities.update({block.block_id: f"cfg_{index}" for index, block in enumerate(cfg.blocks)})
    for edge in cfg.edges:
        assert (
            f'{identities[edge.source]} -> {identities[edge.target]} [label="{edge.kind.value}"]'
            in dot
        )


def test_cfg_diagram_distinguishes_unreachable_blocks_and_escapes_block_names():
    attack = 'dead"]; injected -> cfg_exit [label="\\N'
    cfg = ControlFlowGraph(
        (BasicBlock(attack, (), reachable=False),),
        (Edge("entry", "exit", EdgeKind.ENTRY), Edge(attack, "exit", EdgeKind.FALLTHROUGH)),
    )
    dot = cfg_to_dot(cfg)
    assert "(unreachable)" in dot and 'style="dashed"' in dot
    assert '[label="fallthrough"]' in dot
    assert "injected" in dot and "injected" not in _outside_strings(dot)
    assert 'cfg_0 -> cfg_exit [label="fallthrough"]' in dot


def test_empty_cfg_still_has_meaningful_entry_and_exit_graph():
    cfg = ControlFlowGraph((), (Edge("entry", "exit", EdgeKind.ENTRY),))
    dot = cfg_to_dot(cfg)
    assert 'cfg_entry -> cfg_exit [label="entry"]' in dot


def test_graph_exports_are_deterministic_across_independent_frontend_runs():
    first = parse(SOURCE)
    second = parse(SOURCE)
    assert ast_to_dot(first) == ast_to_dot(second)
    assert cfg_to_dot(build_cfg(lower_ir(first))) == cfg_to_dot(build_cfg(lower_ir(second)))


def test_dot_output_succeeds_without_external_graphviz(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_renderer.shutil, "which", lambda executable: None)
    dot = ast_to_dot(parse(SOURCE))
    path = tmp_path / "nested" / "ast.dot"
    assert render(dot, str(path), format="dot") == path
    assert path.read_text(encoding="utf-8") == dot


def test_dot_output_honors_requested_filename_and_retains_dot_sidecar(tmp_path):
    dot = "digraph G {}\n"
    path = tmp_path / "graph.txt"
    assert render(dot, path, format="dot") == path
    assert path.read_text() == dot
    assert path.with_suffix(".dot").read_text() == dot


@pytest.mark.parametrize("format", ["svg", "png", "pdf"])
def test_missing_graphviz_reports_preserved_dot_source(tmp_path, monkeypatch, format):
    monkeypatch.setattr(graph_renderer.shutil, "which", lambda executable: None)
    dot = ast_to_dot(parse("int main(){return 0;}"))
    path = tmp_path / f"ast.{format}"
    with pytest.raises(GraphvizUnavailableError) as caught:
        render(dot, path, format=format)
    assert caught.value.dot_path == path.with_suffix(".dot")
    assert caught.value.dot_path.read_text() == dot
    assert "unavailable" in str(caught.value) and str(caught.value.dot_path) in str(caught.value)
    assert not path.exists()


def test_renderer_failure_reports_diagnostic_and_retains_dot(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_renderer.shutil, "which", lambda executable: "/fake/dot")
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr=b"syntax error near bogus")
    monkeypatch.setattr(graph_renderer.subprocess, "run", fail)
    dot = "digraph G { bogus }\n"
    path = tmp_path / "graph.svg"
    with pytest.raises(GraphRenderError) as caught:
        render(dot, path)
    assert "syntax error near bogus" in str(caught.value)
    assert caught.value.dot_path.read_text() == dot
    assert not path.exists()


def test_renderer_disappearing_after_probe_still_preserves_dot(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_renderer.shutil, "which", lambda executable: "/fake/dot")
    def fail(command, **kwargs):
        raise FileNotFoundError("executable disappeared")
    monkeypatch.setattr(graph_renderer.subprocess, "run", fail)
    with pytest.raises(GraphvizUnavailableError) as caught:
        render("digraph G {}", tmp_path / "graph.svg")
    assert caught.value.dot_path.exists()


def test_renderer_timeout_preserves_dot_and_reports_useful_error(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_renderer.shutil, "which", lambda executable: "/fake/dot")
    def fail(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 30)
    monkeypatch.setattr(graph_renderer.subprocess, "run", fail)
    with pytest.raises(GraphRenderError, match="timed out") as caught:
        render("digraph G {}", tmp_path / "graph.svg")
    assert caught.value.dot_path.exists()


def test_rendered_output_cannot_overwrite_its_dot_sidecar(tmp_path):
    path = tmp_path / "graph.dot"
    with pytest.raises(GraphRenderError, match="sidecar"):
        render("digraph G {}", path, format="svg")
    assert path.read_text() == "digraph G {}"


@pytest.mark.parametrize("format", ["jpeg", "SVG", "", "svg; touch unexpected"])
def test_render_rejects_unplanned_formats(tmp_path, format):
    with pytest.raises(ValueError, match="Graph format"):
        render("digraph G {}", tmp_path / "graph", format=format)
    assert list(tmp_path.iterdir()) == []


def test_render_uses_argument_list_and_writes_actual_renderer_output(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_renderer.shutil, "which", lambda executable: "/fake tools/dot")
    commands = []
    def succeed(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=b"<svg>actual renderer output</svg>")
    monkeypatch.setattr(graph_renderer.subprocess, "run", succeed)
    path = tmp_path / "graph with spaces; $name.svg"
    assert render("digraph G {}", path) == path
    assert path.read_bytes() == b"<svg>actual renderer output</svg>"
    assert commands[0][0] == ["/fake tools/dot", "-Tsvg", str(path.with_suffix(".dot"))]
    assert "shell" not in commands[0][1]


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("dot") is None, reason="external Graphviz 'dot' executable is unavailable")
@pytest.mark.parametrize("graph_kind", ["ast", "cfg"])
@pytest.mark.parametrize("format", ["svg", "png", "pdf"])
def test_actual_graphviz_renders_real_program_graphs(tmp_path, graph_kind, format):
    program = parse(SOURCE)
    dot = ast_to_dot(program) if graph_kind == "ast" else cfg_to_dot(build_cfg(lower_ir(program)))
    path = render(dot, tmp_path / f"{graph_kind}.{format}", format=format)
    signatures = {"svg": b"<?xml", "png": b"\x89PNG\r\n\x1a\n", "pdf": b"%PDF-"}
    assert path.read_bytes().startswith(signatures[format])
    assert path.with_suffix(".dot").read_text() == dot


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("dot") is None, reason="external Graphviz 'dot' executable is unavailable")
def test_actual_graphviz_accepts_escaped_malicious_labels(tmp_path):
    program = parse("int main(){return 0;}")
    program = replace(program, function=replace(program.function, name='quote" slash\\ line\n<angle>'))
    path = render(ast_to_dot(program), tmp_path / "escaped.svg")
    assert b"<svg" in path.read_bytes()
