"""Immutable records for compilation and observations, without timing metrics."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CompileConfig:
    compiler: str = "clang"
    optimization: str = "O0"
    compile_timeout: float = 10.0
    execution_timeout: float = 2.0
    sanitize: bool = True
    max_output_bytes: int = 65536
    memory_limit_mb: int | None = None
    extra_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.compiler, str) or not self.compiler or "\0" in self.compiler:
            raise ValueError("compiler must be a nonempty executable path or name")
        if self.optimization not in ("O0", "O2"):
            raise ValueError("optimization must be O0 or O2")
        for name in ("compile_timeout", "execution_timeout"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not isinstance(self.sanitize, bool):
            raise ValueError("sanitize must be a boolean")
        if type(self.max_output_bytes) is not int or self.max_output_bytes < 1024:
            raise ValueError("max_output_bytes must be an integer of at least 1024")
        if self.memory_limit_mb is not None and (type(self.memory_limit_mb) is not int or self.memory_limit_mb <= 0):
            raise ValueError("memory_limit_mb must be a positive integer or None")
        if not isinstance(self.extra_flags, tuple) or any(not isinstance(flag, str) or "\0" in flag for flag in self.extra_flags):
            raise ValueError("extra_flags must be a tuple of argument strings")
        # High-level validation must not be able to disable UBSan, change the
        # integer model/optimization level, inject source, or redirect artifacts
        # while claiming the configured contract. Only diagnostic switches are
        # extensible; Clang still diagnoses unsupported warning options itself.
        diagnostic_options = {"-w", "-pedantic", "-pedantic-errors", "-fcolor-diagnostics", "-fno-color-diagnostics"}
        if any(flag not in diagnostic_options and not (flag.startswith("-W") and not flag.startswith(("-Wl,", "-Wp,", "-Wa,"))) for flag in self.extra_flags):
            raise ValueError("extra_flags may only configure compiler diagnostics; semantics, target, output and sanitizer options are controlled")

    @property
    def flags(self) -> tuple[str, ...]:
        sanitizer = ("-fsanitize=undefined", "-fno-sanitize-recover=all") if self.sanitize else ()
        return ("-std=c11", f"-{self.optimization}", *sanitizer, *self.extra_flags)


@dataclass(frozen=True, slots=True)
class ExecutionCase:
    stdin: bytes = b""
    arguments: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stdin, bytes):
            raise ValueError("stdin must be bytes")
        if not isinstance(self.arguments, tuple) or any(not isinstance(arg, str) or "\0" in arg for arg in self.arguments):
            raise ValueError("arguments must be a tuple of argument strings")
        if not isinstance(self.environment, tuple):
            raise ValueError("environment must be a tuple of (name, value) pairs")
        for pair in self.environment:
            if not isinstance(pair, tuple) or len(pair) != 2 or any(not isinstance(value, str) or "\0" in value for value in pair):
                raise ValueError("environment must contain string pairs")
            if not pair[0] or "=" in pair[0]:
                raise ValueError("environment variable names must be nonempty and exclude '='")


@dataclass(frozen=True, slots=True)
class CompilerInfo:
    status: str
    path: str | None = None
    version: str | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledArtifact:
    path: Path
    source_sha256: str
    sanitized: bool
    observation_file: str | None = None


@dataclass(frozen=True, slots=True)
class CompilationResult:
    status: str
    artifact: CompiledArtifact | None = None
    command: tuple[str, ...] = ()
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    detail: str | None = None
    source_sha256: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    process_returncode: int | None = None
    return_value: int | None = None
    stdout: str = ""
    stderr: str = ""
    detail: str | None = None
    command: tuple[str, ...] = ()
    signal: int | None = None
