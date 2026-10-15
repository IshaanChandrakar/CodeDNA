"""Deterministic AST/CFG DOT export and optional external Graphviz rendering.

DOT export is pure Python and never requires the ``dot`` executable.  Rendered
formats retain a readable DOT sidecar even when Graphviz is unavailable or
reports an error.  Graph identifiers are generated here; user strings occur
only in escaped, quoted labels.
"""

from __future__ import annotations

from dataclasses import fields
from enum import Enum
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING

from compiler.ast_nodes import Node, Program, walk

if TYPE_CHECKING:
    from compiler.cfg import ControlFlowGraph


class GraphRenderError(Exception):
    """Rendering failed; ``dot_path`` identifies the inspectable DOT source."""

    def __init__(self, message: str, dot_path: Path) -> None:
        self.dot_path = dot_path
        super().__init__(f"{message}; DOT source: {dot_path}")


class GraphvizUnavailableError(GraphRenderError):
    """The optional external Graphviz ``dot`` executable was not found."""


def _quote(text: str) -> str:
    """Quote a DOT string without interpreting user backslashes as escapes."""
    escaped = []
    for character in text:
        if character == "\\":
            escaped.append("\\\\")
        elif character == '"':
            escaped.append('\\"')
        elif character == "\n":
            escaped.append("\\n")
        elif character == "\r":
            escaped.append("\\r")
        elif character == "\t":
            escaped.append("    ")
        elif ord(character) < 32 or ord(character) == 127:
            # DOT has no portable JSON-style control-character escape.  Display
            # the hexadecimal spelling literally, rather than emit raw bytes.
            escaped.append(f"\\\\x{ord(character):02x}")
        else:
            escaped.append(character)
    return '"' + "".join(escaped) + '"'


def _scalar(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if value is None:
        return "None"
    return str(value)


def ast_to_dot(program: Program, *, include_spans: bool = False) -> str:
    """Describe the actual syntax tree, its scalar fields and child roles.

    Nodes follow deterministic preorder.  Child edges retain dataclass field
    names, including tuple indices, so loop headers and branch arms remain
    distinguishable.  Source positions can be included for inspection without
    embedding source text or making source IDs into executable DOT syntax.
    """
    nodes = tuple(walk(program))
    graph_ids = {id(node): f"ast_{index}" for index, node in enumerate(nodes)}
    lines = [
        "digraph AST {",
        "  graph [rankdir=TB];",
        '  node [shape=box, fontname="monospace"];',
        '  edge [fontname="monospace"];',
    ]
    edges = []
    for node in nodes:
        graph_id = graph_ids[id(node)]
        label = [type(node).__name__]
        for field in fields(node):
            if field.name in {"node_id", "span"}:
                continue
            value = getattr(node, field.name)
            if isinstance(value, Node):
                edges.append((graph_id, graph_ids[id(value)], field.name))
            elif isinstance(value, tuple):
                for index, item in enumerate(value):
                    if isinstance(item, Node):
                        edges.append((graph_id, graph_ids[id(item)], f"{field.name}[{index}]"))
                    else:
                        label.append(f"{field.name}[{index}] = {_scalar(item)}")
            else:
                label.append(f"{field.name} = {_scalar(value)}")
        if include_spans:
            span = node.span
            label.append(
                f"at {span.start_line}:{span.start_column}"
                f" to {span.end_line}:{span.end_column}"
            )
        lines.append(f"  {graph_id} [label={_quote(chr(10).join(label))}];")
    lines.extend(
        f"  {source} -> {target} [label={_quote(role)}];"
        for source, target, role in edges
    )
    return "\n".join([*lines, "}", ""])


def cfg_to_dot(cfg: ControlFlowGraph) -> str:
    """Describe TAC basic blocks, typed edges, entry/exit and reachability."""
    from compiler.ir import format_instruction

    graph_ids = {cfg.entry: "cfg_entry", cfg.exit: "cfg_exit"}
    graph_ids.update({block.block_id: f"cfg_{index}" for index, block in enumerate(cfg.blocks)})
    lines = [
        "digraph CFG {",
        "  graph [rankdir=TB];",
        '  node [shape=box, fontname="monospace"];',
        '  edge [fontname="monospace"];',
        f"  cfg_entry [shape=oval, label={_quote(cfg.entry)}];",
        f"  cfg_exit [shape=oval, label={_quote(cfg.exit)}];",
    ]
    for block in cfg.blocks:
        label = [block.block_id]
        if not block.reachable:
            label.append("(unreachable)")
        label.extend(format_instruction(instruction) for instruction in block.instructions)
        attributes = [f"label={_quote(chr(10).join(label))}"]
        if not block.reachable:
            attributes.extend(['style="dashed"', 'color="gray50"'])
        lines.append(f"  {graph_ids[block.block_id]} [{', '.join(attributes)}];")
    for edge in cfg.edges:
        # Edge order comes directly from deterministic CFG construction.  All
        # edge kinds are visible, including real jumps that form loop backs.
        lines.append(
            f"  {graph_ids[edge.source]} -> {graph_ids[edge.target]}"
            f" [label={_quote(_scalar(edge.kind))}];"
        )
    return "\n".join([*lines, "}", ""])


def render(dot: str, path: Path | str, format: str = "svg") -> Path:
    """Save DOT and optionally render SVG, PNG or PDF with external Graphviz.

    ``path`` is the exact requested output filename.  The DOT source is always
    saved at ``path.with_suffix('.dot')`` before invoking a renderer.  ``dot``
    format needs no external executable and writes the requested path directly.
    Render failures leave the sidecar available through ``error.dot_path``.
    """
    if format not in {"dot", "svg", "png", "pdf"}:
        raise ValueError("Graph format must be one of: dot, svg, png, pdf")
    output_path = Path(path)
    dot_path = output_path.with_suffix(".dot")
    try:
        dot_path.parent.mkdir(parents=True, exist_ok=True)
        dot_path.write_text(dot, encoding="utf-8")
    except OSError as error:
        raise GraphRenderError(f"Cannot save DOT source: {error}", dot_path) from error
    if format == "dot":
        if output_path != dot_path:
            try:
                output_path.write_text(dot, encoding="utf-8")
            except OSError as error:
                raise GraphRenderError(f"Cannot save requested graph output: {error}", dot_path) from error
        return output_path
    if output_path == dot_path:
        raise GraphRenderError("Rendered output must use a filename other than its .dot sidecar", dot_path)
    executable = shutil.which("dot")
    if executable is None:
        raise GraphvizUnavailableError(
            "Graphviz 'dot' executable is unavailable; install Graphviz to render this graph", dot_path,
        )
    try:
        completed = subprocess.run(
            [executable, f"-T{format}", str(dot_path.resolve())],
            capture_output=True, check=True, timeout=30,
        )
    except FileNotFoundError as error:
        raise GraphvizUnavailableError("Graphviz 'dot' executable became unavailable", dot_path) from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or b"").decode("utf-8", errors="replace").strip()
        message = f"Graphviz 'dot' failed with exit code {error.returncode}"
        if detail:
            message += f": {detail}"
        raise GraphRenderError(message, dot_path) from error
    except subprocess.TimeoutExpired as error:
        raise GraphRenderError("Graphviz 'dot' timed out after 30 seconds", dot_path) from error
    except OSError as error:
        raise GraphRenderError(f"Cannot render graph: {error}", dot_path) from error
    try:
        output_path.write_bytes(completed.stdout)
    except OSError as error:
        raise GraphRenderError(f"Cannot save rendered graph: {error}", dot_path) from error
    return output_path
