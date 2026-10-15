"""Inspect the frontend, semantics, TAC and graphs with python -m compiler."""

import argparse
from pathlib import Path
import sys

from compiler.ast_nodes import ast_to_json
from compiler.cfg import build_cfg, format_cfg
from compiler.diagnostics import FrontendError
from compiler.ir import format_ir, lower_ir
from compiler.lexer import format_tokens, tokenize
from compiler.parser import parse
from compiler.semantic import analyze
from visualization.graph_renderer import GraphRenderError, ast_to_dot, cfg_to_dot, render


def _same_file(path: Path, source: Path) -> bool:
    """Include symlink/hardlink aliases without resolving nonexistent outputs."""
    try:
        return path.samefile(source)
    except FileNotFoundError:
        return path.absolute() == source.absolute()


def main(argv: list[str] | None = None) -> int:
    arguments = argparse.ArgumentParser(description="CodeDNA C frontend, semantic analysis, TAC and graphs")
    mode = arguments.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tokens", action="store_true", help="Display tokens; do not parse")
    mode.add_argument("--ast", action="store_true", help="Parse and display formatted AST JSON")
    mode.add_argument("--check", action="store_true", help="Validate declarations, initialization and return paths")
    mode.add_argument("--tac", action="store_true", help="Validate and display three-address code")
    mode.add_argument("--cfg", action="store_true", help="Validate and display basic blocks and control-flow edges")
    mode.add_argument("--ast-dot", action="store_true", help="Export the syntax tree as DOT or a rendered graph")
    mode.add_argument("--cfg-dot", action="store_true", help="Export the validated CFG as DOT or a rendered graph")
    arguments.add_argument("-o", "--output", type=Path, help="Write output to this file (parents created)")
    arguments.add_argument("--format", choices=("dot", "svg", "png", "pdf"), help="Graph output format; default dot")
    arguments.add_argument("source", type=Path, help="UTF-8 C source file")
    options = arguments.parse_args(argv)
    graph_mode = options.ast_dot or options.cfg_dot
    if options.format is not None and not graph_mode:
        arguments.error("--format requires --ast-dot or --cfg-dot")
    graph_format = options.format or "dot"
    if graph_mode and graph_format != "dot" and options.output is None:
        arguments.error("rendered graph formats require --output")
    if options.output is not None and not options.output.name:
        arguments.error("--output must include a filename")
    try:
        if options.output is not None:
            outputs = [options.output]
            if graph_mode:
                outputs.append(options.output.with_suffix(".dot"))
            if any(_same_file(path, options.source) for path in outputs):
                arguments.error("output and DOT sidecar paths must not overwrite the input source")
        # Preserve original newline spelling so API and CLI spans agree.
        with options.source.open(encoding="utf-8", newline="") as source_file:
            source = source_file.read()
        diagnostics = ()
        if options.tokens:
            output = format_tokens(tokenize(source))
        else:
            program = parse(source)
            if options.ast:
                output = ast_to_json(program)
            elif options.ast_dot:
                output = ast_to_dot(program)
            elif options.check:
                analysis = analyze(program)
                diagnostics = analysis.diagnostics
                output = "Semantic analysis passed."
            else:
                ir = lower_ir(program)
                diagnostics = ir.diagnostics
                if options.tac:
                    output = format_ir(ir)
                else:
                    cfg = build_cfg(ir)
                    output = cfg_to_dot(cfg) if options.cfg_dot else format_cfg(cfg)
        for diagnostic in diagnostics:
            print(diagnostic.format(str(options.source)), file=sys.stderr)
        if options.output is not None:
            if graph_mode:
                render(output, options.output, graph_format)
            else:
                options.output.parent.mkdir(parents=True, exist_ok=True)
                options.output.write_text(output + ("\n" if output and not output.endswith("\n") else ""), encoding="utf-8")
            print(f"Saved {options.output}")
            return 0
    except FrontendError as error:
        print(error.diagnostic.format(str(options.source)), file=sys.stderr)
        return 1
    except (OSError, UnicodeError) as error:
        print(f"{options.source}: file error: {error}", file=sys.stderr)
        return 2
    except GraphRenderError as error:
        print(f"{options.source}: graph error: {error}", file=sys.stderr)
        return 2
    except RecursionError:
        print(f"{options.source}: frontend error: source nesting exceeds Python's recursion limit", file=sys.stderr)
        return 1
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
