"""Controlled full-return observation for validated CodeDNA programs.

The public source language remains the restricted frontend subset.  The fuller
C wrapper below is generated infrastructure, never accepted user source.  Its
JSON file is separate from stdout/stderr and from the wrapper's process status.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

from compiler.ast_nodes import Declaration, Function, Identifier, Program, walk
from compiler.codegen import emit_c
from compiler.parser import parse
from compiler.semantic import INT_MAX, INT_MIN, analyze


OBSERVATION_FILE = "codedna_observation.json"
PROTOCOL_VERSION = 1
MAX_OBSERVATION_BYTES = 4096
_MAIN_HEADER = "int main(void) {"


@dataclass(frozen=True, slots=True)
class HarnessSource:
    source: str
    entry_name: str
    canonical_source: str
    observation_file: str = OBSERVATION_FILE
    protocol_version: int = PROTOCOL_VERSION


class ObservationError(ValueError):
    """An observation is absent from the supported versioned integer protocol."""


def make_harness(program: Program) -> HarnessSource:
    """Emit validated subset C and wrap its computation without regex rewriting.

    The only renamed text is the verified canonical emitter's opening function
    header.  User identifiers are collected structurally to allocate a stable,
    collision-free internal entry.  Standard headers follow the user function:
    their macros must not alter accepted user names such as ``EOF``/``INT_MIN``.
    """
    if not isinstance(program, Program):
        raise TypeError("make_harness requires a parsed Program, not raw C source")
    canonical_source = emit_c(program)
    if not canonical_source.startswith(_MAIN_HEADER + "\n"):
        raise ValueError("Canonical C emitter returned an unexpected main header")
    # Round-trip through the unchanged frontend as an additional boundary check.
    # This also covers negative literal nodes introduced by safe transformations.
    emitted_program = parse(canonical_source)
    analyze(emitted_program)
    user_names = {
        node.name for node in walk(emitted_program)
        if isinstance(node, (Declaration, Identifier, Function))
    }
    entry_name = "codedna_entry"
    suffix = 1
    while entry_name in user_names:
        entry_name = f"codedna_entry_{suffix}"
        suffix += 1
    computation = (
        f"static int {entry_name}(void) {{"
        + canonical_source[len(_MAIN_HEADER):]
    )
    wrapper = f'''
/* Generated infrastructure: not part of the accepted user C subset. */
#include <limits.h>
#include <stdio.h>

_Static_assert(CHAR_BIT == 8, "CODEDNA_TARGET_INT32: CHAR_BIT must be 8");
_Static_assert(sizeof(int) == 4, "CODEDNA_TARGET_INT32: sizeof(int) must be 4");
_Static_assert(INT_MIN == (-2147483647 - 1) && INT_MAX == 2147483647,
               "CODEDNA_TARGET_INT32: int must have the signed 32-bit range");

int main(void) {{
    int codedna_return_value = {entry_name}();
    FILE *codedna_observation = fopen("{OBSERVATION_FILE}", "wx");
    if (codedna_observation == NULL) {{
        fputs("CODEDNA_OBSERVATION_ERROR: cannot create observation file\\n", stderr);
        return 120;
    }}
    if (fprintf(codedna_observation,
                "{{\\"protocol_version\\":{PROTOCOL_VERSION},\\"return_value\\":%d}}\\n",
                codedna_return_value) < 0) {{
        (void)fclose(codedna_observation);
        fputs("CODEDNA_OBSERVATION_ERROR: cannot write observation file\\n", stderr);
        return 121;
    }}
    if (fclose(codedna_observation) != 0) {{
        fputs("CODEDNA_OBSERVATION_ERROR: cannot close observation file\\n", stderr);
        return 122;
    }}
    return 0;
}}
'''
    return HarnessSource(
        source=computation + wrapper,
        entry_name=entry_name,
        canonical_source=canonical_source,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ObservationError(f"Duplicate observation field: {name}")
        result[name] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ObservationError(f"Non-finite JSON number is not an observation: {value}")


def parse_observation(text: str) -> int:
    """Read exactly version 1's integer result; reject ambiguous or bad records.

    Python booleans are not accepted as integers.  Unknown/duplicate fields,
    non-finite values, noninteger numbers and results outside signed 32-bit range
    are protocol failures, never valid program observations.
    """
    if not isinstance(text, str):
        raise ObservationError("Observation must be JSON text")
    if len(text) > MAX_OBSERVATION_BYTES:
        raise ObservationError("Observation exceeds the protocol size limit")
    try:
        observation = json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite,
        )
    except ObservationError:
        raise
    except (ValueError, RecursionError) as error:
        raise ObservationError(f"Malformed observation JSON: {error}") from error
    if not isinstance(observation, dict) or set(observation) != {"protocol_version", "return_value"}:
        raise ObservationError("Observation must contain exactly protocol_version and return_value")
    if type(observation["protocol_version"]) is not int or observation["protocol_version"] != PROTOCOL_VERSION:
        raise ObservationError("Unsupported observation protocol_version; expected integer 1")
    value = observation["return_value"]
    if type(value) is not int or not INT_MIN <= value <= INT_MAX:
        raise ObservationError("Observation return_value must be a signed 32-bit integer")
    return value
