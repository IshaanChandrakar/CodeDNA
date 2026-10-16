"""Inspect the frontend, semantics, TAC and graphs with python -m compiler."""

import argparse
from pathlib import Path
import sys

from compiler.ast_nodes import ast_to_json
from compiler.cfg import build_cfg, format_cfg
from compiler.diagnostics import FrontendError
from compiler.ir import emit_c, format_ir, lower_ir
from compiler.lexer import format_tokens, tokenize
from compiler.parser import parse
from compiler.semantic import analyze
from transformations.common import MAX_UNROLL_LIMIT
from transformations.pipeline import PASS_NAMES, apply_transformations
from visualization.graph_renderer import GraphRenderError, ast_to_dot, cfg_to_dot, render


def _same_file(path: Path, source: Path) -> bool:
    """Include symlink/hardlink aliases without resolving nonexistent outputs."""
    try:
        return path.samefile(source)
    except FileNotFoundError:
        return path.absolute() == source.absolute()


def main(argv: list[str] | None = None) -> int:
    arguments = argparse.ArgumentParser(description="CodeDNA C frontend, semantic analysis, TAC and graphs")
    mode = arguments.add_mutually_exclusive_group()
    mode.add_argument("--tokens", action="store_true", help="Display tokens; do not parse")
    mode.add_argument("--ast", action="store_true", help="Parse and display formatted AST JSON")
    mode.add_argument("--check", action="store_true", help="Validate declarations, initialization and return paths")
    mode.add_argument("--tac", action="store_true", help="Validate and display three-address code")
    mode.add_argument("--cfg", action="store_true", help="Validate and display basic blocks and control-flow edges")
    mode.add_argument("--ast-dot", action="store_true", help="Export the syntax tree as DOT or a rendered graph")
    mode.add_argument("--cfg-dot", action="store_true", help="Export the validated CFG as DOT or a rendered graph")
    mode.add_argument("--c", action="store_true", help="Validate and emit canonical subset C without compiling it")
    mode.add_argument("--report", action="store_true", help="Display the requested transformation sequence's JSON reports")
    arguments.add_argument(
        "--transform", action="append", choices=PASS_NAMES, default=[],
        help="Apply a pass; repeat this option to specify the exact sequence",
    )
    arguments.add_argument("--max-unroll", type=int, help="Maximum iterations per loop (default 32; allowed 0..1024)")
    arguments.add_argument("-o", "--output", type=Path, help="Write output to this file (parents created)")
    arguments.add_argument("--format", choices=("dot", "svg", "png", "pdf"), help="Graph output format; default dot")
    arguments.add_argument("source", type=Path, help="UTF-8 C source file")
    options = arguments.parse_args(argv)
    if not any((options.tokens, options.ast, options.check, options.tac, options.cfg,
                options.ast_dot, options.cfg_dot, options.c, options.report)):
        if options.transform:
            options.report = True
        else:
            arguments.error("an inspection mode or --transform is required")
    if options.report and not options.transform:
        arguments.error("--report requires at least one --transform")
    if options.tokens and options.transform:
        arguments.error("--tokens inspects original source and cannot be combined with --transform")
    if options.max_unroll is not None:
        if "unroll" not in options.transform:
            arguments.error("--max-unroll requires --transform unroll")
        if not 0 <= options.max_unroll <= MAX_UNROLL_LIMIT:
            arguments.error(f"--max-unroll must be between 0 and {MAX_UNROLL_LIMIT}")
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
            transformed = None
            if options.transform:
                transformed = apply_transformations(
                    program, options.transform,
                    max_iterations=32 if options.max_unroll is None else options.max_unroll,
                )
                program = transformed.program
                if not options.report:
                    for report in transformed.reports:
                        for decision in report.decisions:
                            if decision.status == "rejected":
                                print(
                                    f"{options.source}:{decision.span.start_line}:{decision.span.start_column}: "
                                    f"transformation {report.name} rejected [{decision.code}]: {decision.message}",
                                    file=sys.stderr,
                                )
            if options.report:
                diagnostics = analyze(program).diagnostics
                output = transformed.to_json()
            elif options.c:
                diagnostics = analyze(program).diagnostics
                output = emit_c(program)
            elif options.ast:
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
