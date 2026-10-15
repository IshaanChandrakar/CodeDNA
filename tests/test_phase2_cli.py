"""Actual Phase 2 CLI output, source errors, graph files and optional rendering."""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from compiler.__main__ import main


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*arguments, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "compiler", *map(str, arguments)], cwd=cwd,
        capture_output=True, text=True, timeout=20,
    )


def source_file(tmp_path, body):
    path = tmp_path / "program.c"
    path.write_text(f"int main(){{\n{body}\n}}\n", encoding="utf-8")
    return path


def test_check_and_tac_actual_outputs(tmp_path):
    path = source_file(tmp_path, "int x=2+3*4;return x;")
    check = run_cli("--check", path)
    assert check.returncode == 0 and check.stdout == "Semantic analysis passed.\n" and check.stderr == ""
    tac = run_cli("--tac", path)
    assert tac.returncode == 0 and tac.stderr == ""
    assert tac.stdout == "%t0 = 3 * 4\n%t1 = 2 + %t0\nx = %t1\nreturn x\n"


@pytest.mark.parametrize("mode", ["--check", "--tac", "--cfg", "--cfg-dot"])
@pytest.mark.parametrize("body,code", [
    ("return missing;", "UNDECLARED_VARIABLE"),
    ("int x;return x;", "UNINITIALIZED_VARIABLE"),
    ("int x=1;{int x=2;}return x;", "DUPLICATE_DECLARATION"),
    ("return 1/(2-2);", "DIVISION_BY_ZERO"),
    ("int x=0;return 1%x;", "MODULO_BY_ZERO"),
    ("return 2147483647+1;", "INTEGER_OVERFLOW"),
    ("int x=1;", "MISSING_RETURN"),
])
def test_analysis_modes_report_structured_semantic_errors(mode, body, code, tmp_path):
    path = source_file(tmp_path, body)
    result = run_cli(mode, path)
    assert result.returncode == 1 and result.stdout == ""
    assert f"semantic error [{code}]" in result.stderr
    assert f"{path}:" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("mode", ["--ast", "--ast-dot", "--tokens"])
def test_phase1_modes_and_syntax_graph_do_not_impose_new_semantic_checks(mode, tmp_path):
    path = source_file(tmp_path, "return missing;")
    result = run_cli(mode, path)
    assert result.returncode == 0 and result.stderr == ""
    assert "missing" in result.stdout


@pytest.mark.parametrize("mode", ["--check", "--tac", "--cfg", "--cfg-dot"])
def test_unreachable_warnings_use_stderr_without_failing(mode, tmp_path):
    path = source_file(tmp_path, "return 1;\nint x=2;")
    result = run_cli(mode, path)
    assert result.returncode == 0
    assert f"{path}:3:1: semantic warning [UNREACHABLE_STATEMENT]" in result.stderr
    assert result.stdout


def test_cfg_reports_real_branch_and_loop_connectivity():
    result = run_cli("--cfg", "examples/loops/sum.c")
    assert result.returncode == 0 and result.stderr == ""
    assert "B1:\n  L0:\n  %t0 = i < 4" in result.stdout
    assert "B1 -> B2 [true]" in result.stdout
    assert "B1 -> B4 [false]" in result.stdout
    assert "B3 -> B1 [jump]" in result.stdout
    assert "B4 -> exit [return]" in result.stdout


@pytest.mark.parametrize("mode,header", [("--ast-dot", "digraph AST"), ("--cfg-dot", "digraph CFG")])
def test_dot_stdout_and_saved_file_are_deterministic_without_renderer(mode, header, tmp_path, monkeypatch, capsys):
    # Exercise the actual entry point with the renderer forcibly absent.
    monkeypatch.setattr(shutil, "which", lambda name: None)
    source = ROOT / "examples" / "loops" / "sum.c"
    assert main([mode, str(source)]) == 0
    direct = capsys.readouterr()
    assert direct.err == "" and direct.out.startswith(header)
    target = tmp_path / "nested" / "graph.dot"
    assert main([mode, "--output", str(target), str(source)]) == 0
    saved = capsys.readouterr()
    assert saved.out == f"Saved {target}\n" and saved.err == ""
    assert target.read_text() == direct.out


def test_missing_renderer_cli_preserves_dot_and_reports_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    output = tmp_path / "graph.svg"
    assert main(["--cfg-dot", "--format", "svg", "--output", str(output), str(ROOT / "examples/loops/sum.c")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "graph error" in captured.err and "executable is unavailable" in captured.err
    assert str(output.with_suffix(".dot")) in captured.err
    assert output.with_suffix(".dot").read_text().startswith("digraph CFG")
    assert not output.exists()


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("dot") is None, reason="external Graphviz dot executable is unavailable")
@pytest.mark.parametrize("mode", ["--ast-dot", "--cfg-dot"])
def test_actual_cli_svg_rendering(mode, tmp_path):
    output = tmp_path / "graph.svg"
    result = run_cli(mode, "--format", "svg", "--output", output, "examples/loops/sum.c")
    assert result.returncode == 0 and result.stderr == ""
    assert "<svg" in output.read_text()
    assert output.with_suffix(".dot").exists()


@pytest.mark.parametrize("arguments", [
    ("--tac", "--format", "svg"),
    ("--ast-dot", "--format", "svg"),
    ("--cfg-dot", "--format", "invalid"),
    ("--check", "--tac"),
])
def test_invalid_mode_and_render_options(arguments):
    result = run_cli(*arguments, "examples/basic/minimal.c")
    assert result.returncode == 2
    assert "error:" in result.stderr and "Traceback" not in result.stderr


def test_cli_refuses_to_overwrite_its_source_or_graph_sidecar(tmp_path):
    source = source_file(tmp_path, "return 0;")
    original = source.read_text()
    result = run_cli("--tac", "--output", source, source)
    assert result.returncode == 2 and "overwrite" in result.stderr
    dot_source = tmp_path / "input.dot"
    dot_source.write_text(original)
    result = run_cli("--ast-dot", "--format", "svg", "--output", tmp_path / "input.svg", dot_source)
    assert result.returncode == 2 and "overwrite" in result.stderr
    assert source.read_text() == dot_source.read_text() == original


def test_cli_refuses_source_overwrite_via_a_hardlink(tmp_path):
    source = source_file(tmp_path, "return 0;")
    alias = tmp_path / "alias.tac"
    alias.hardlink_to(source)
    original = source.read_text()
    result = run_cli("--tac", "--output", alias, source)
    assert result.returncode == 2 and "overwrite" in result.stderr
    assert alias.read_text() == source.read_text() == original


def test_cli_handles_an_output_symlink_loop_as_a_file_error(tmp_path):
    source = source_file(tmp_path, "return 0;")
    output = tmp_path / "loop.tac"
    output.symlink_to(output.name)
    result = run_cli("--tac", "--output", output, source)
    assert result.returncode == 2
    assert "file error" in result.stderr and "Traceback" not in result.stderr


def test_graph_output_requires_a_filename():
    result = run_cli("--ast-dot", "--output", "/", "examples/basic/minimal.c")
    assert result.returncode == 2
    assert "filename" in result.stderr and "Traceback" not in result.stderr


def test_output_file_failure_does_not_print_traceback(tmp_path):
    source = source_file(tmp_path, "return 0;")
    output = tmp_path / "directory"
    output.mkdir()
    result = run_cli("--tac", "--output", output, source)
    assert result.returncode == 2
    assert "file error" in result.stderr and "Traceback" not in result.stderr


def test_tac_can_be_saved_and_inspected_outside_the_checkout(tmp_path):
    output = tmp_path / "nested" / "program.tac"
    result = run_cli("--tac", "--output", output, ROOT / "examples/basic/minimal.c", cwd=tmp_path)
    assert result.returncode == 0 and result.stderr == ""
    assert output.read_text() == "return 0\n"
