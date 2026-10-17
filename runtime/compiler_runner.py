"""Context-owned Clang builds and bounded subprocess execution.

This is a local runner for trusted coursework fixtures, not a sandbox for
hostile code. Process groups, wall-clock deadlines and available POSIX resource
limits contain accidental runaway programs. Optional timing measures end-to-end
process execution and supervision; ordinary Phase 4 execution records retain
their original fields and do not collect performance measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from typing import TYPE_CHECKING

from runtime.models import (
    CompilationResult, CompileConfig, CompiledArtifact, CompilerInfo,
    ExecutionCase, ExecutionResult,
)

if TYPE_CHECKING:
    from runtime.benchmark_models import TimedExecution

try:
    import resource
except ImportError:  # pragma: no cover - POSIX is the supported execution target.
    resource = None


@dataclass(frozen=True, slots=True)
class _ProcessResult:
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timeout: bool = False
    output_limit: bool = False
    error: str | None = None
    duration_ns: int | None = None


class _CaptureStartError(RuntimeError):
    """Output supervision could not start after the child was launched."""


def _kill_group(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - fallback for non-POSIX Python.
            process.kill()
    except ProcessLookupError:
        pass


def _join_capture_threads(threads: list[threading.Thread]) -> None:
    """Join started captures without masking an interrupted/failed start."""
    for thread in threads:
        # A Thread enters the cleanup list before start(), since an interrupt
        # can arrive during that call. Joining an unstarted thread raises and
        # would otherwise hide KeyboardInterrupt from the benchmark handler.
        if thread.ident is not None:
            thread.join(timeout=1)


def _capture_pipe(pipe, path: Path, maximum: int, limited: threading.Event, failures: list[str]) -> None:
    """Drain one stream without unbounded memory or output-file growth."""
    written = 0
    try:
        with path.open("wb") as stream:
            while chunk := pipe.read(8192):
                remaining = maximum - written
                if remaining > 0:
                    retained = chunk[:remaining]
                    stream.write(retained)
                    written += len(retained)
                if len(chunk) > remaining:
                    limited.set()
    except OSError as error:
        failures.append(f"Cannot capture process output: {error}")
        limited.set()
    finally:
        pipe.close()


def _read_capture(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _valid_observation_filename(value: object) -> bool:
    return (
        isinstance(value, str) and bool(value)
        and Path(value).name == value
        and value not in {".", "..", "stdin.bin", "stdout.bin", "stderr.bin"}
        and "\0" not in value
    )


def _resource_setup(timeout: float, file_limit: int, address_space: int | None):
    if resource is None or os.name != "posix":
        return None

    def setup() -> None:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        seconds = max(1, math.ceil(timeout) + 1)
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
        if address_space is not None and hasattr(resource, "RLIMIT_AS"):
            resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))

    return setup


def _run_process(
    command: tuple[str, ...], *, cwd: Path, environment: dict[str, str],
    timeout: float, output_bytes: int, stdin: bytes = b"",
    execution: bool = False, address_space: int | None = None,
    measure: bool = False,
) -> _ProcessResult:
    stdout_path, stderr_path = cwd / "stdout.bin", cwd / "stderr.bin"
    input_path = cwd / "stdin.bin"
    process = None
    limited = threading.Event()
    failures: list[str] = []
    threads = []
    timed_out = False
    returncode = None
    started_ns = None
    duration_ns = None
    try:
        input_path.write_bytes(stdin)
        with input_path.open("rb") as input_stream:
            arguments = list(command)
            limits = _resource_setup(timeout, output_bytes, address_space) if execution else None
            if measure:
                started_ns = time.perf_counter_ns()
            process = subprocess.Popen(
                arguments, cwd=cwd, env=environment, stdin=input_stream,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                start_new_session=os.name == "posix",
                preexec_fn=limits,
            )
            for pipe, destination in ((process.stdout, stdout_path), (process.stderr, stderr_path)):
                thread = threading.Thread(
                    target=_capture_pipe,
                    args=(pipe, destination, output_bytes, limited, failures), daemon=True,
                )
                threads.append(thread)
                try:
                    thread.start()
                except RuntimeError as error:
                    raise _CaptureStartError(f"Cannot start output capture thread: {error}") from error
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if limited.is_set() or remaining <= 0:
                    timed_out = remaining <= 0 and not limited.is_set()
                    _kill_group(process)
                    returncode = process.wait()
                    break
                try:
                    returncode = process.wait(timeout=min(remaining, 0.025))
                    break
                except subprocess.TimeoutExpired:
                    pass
            # A child may have exited while its descendants still hold pipes.
            # Kill the context's process group before waiting for the drainers.
            _kill_group(process)
            _join_capture_threads(threads)
            if any(thread.is_alive() for thread in threads):
                failures.append("Process output streams did not close after termination")
            if measure:
                duration_ns = time.perf_counter_ns() - started_ns
    except KeyboardInterrupt:
        # A user interruption must not leave measured or ordinary subprocesses
        # (or descendants holding output pipes) running after the caller exits.
        if process is not None:
            _kill_group(process)
            process.wait()
            _join_capture_threads(threads)
        raise
    except (OSError, subprocess.SubprocessError, _CaptureStartError) as error:
        if process is not None:
            _kill_group(process)
            process.wait()
            _join_capture_threads(threads)
            if measure:
                duration_ns = time.perf_counter_ns() - started_ns
        return _ProcessResult(
            returncode, _read_capture(stdout_path), _read_capture(stderr_path),
            error=f"Cannot start or manage process: {error}", output_limit=limited.is_set(),
            duration_ns=duration_ns,
        )
    return _ProcessResult(
        returncode, _read_capture(stdout_path), _read_capture(stderr_path),
        timeout=timed_out, output_limit=limited.is_set(),
        error="; ".join(failures) if failures else None,
        duration_ns=duration_ns,
    )


class CompilerRunner:
    """Own all builds/runs and remove them when the context finishes.

    Artifacts are intentionally ephemeral. Keep this context open while using
    them; serializable reports contain their source hash and commands rather
    than promising that executable paths remain available later.
    """

    def __init__(self, config: CompileConfig | None = None) -> None:
        self.config = config if config is not None else CompileConfig()
        if not isinstance(self.config, CompileConfig):
            raise ValueError("config must be a CompileConfig")
        self.compiler_info = CompilerInfo("missing", detail="Runner context has not been entered")
        self.root: Path | None = None
        self._temporary: TemporaryDirectory | None = None
        self._entered = False
        self._directory_number = 0
        # Snapshot once so baseline/variant processes see the same inherited
        # environment even if the host process changes os.environ in between.
        self._environment = dict(os.environ)

    def __enter__(self) -> CompilerRunner:
        if self._entered:
            raise RuntimeError("A CompilerRunner context can only be entered once")
        self._entered = True
        try:
            self._temporary = TemporaryDirectory(prefix="codedna-")
            self.root = Path(self._temporary.name)
            self.compiler_info = self._detect_compiler()
        except BaseException:
            # __exit__ is never invoked when __enter__ itself fails. Release
            # the workspace even if a caller retains this runner or traceback.
            self.close()
            raise
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        self.close()

    def close(self) -> None:
        """Release every private source, executable, capture and observation."""
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None

    def _active(self) -> None:
        if self._temporary is None:
            raise RuntimeError("CompilerRunner must be used inside an active with context")

    def _directory(self, kind: str) -> Path:
        self._active()
        path = self.root / f"{kind}-{self._directory_number:04d}"
        self._directory_number += 1
        path.mkdir(mode=0o700)
        return path

    def _controlled_environment(self, case: ExecutionCase | None = None) -> dict[str, str]:
        environment = self._environment.copy()
        if case is not None:
            environment.update(case.environment)
        environment.update({
            "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=0:exitcode=86",
        })
        return environment

    def _detect_compiler(self) -> CompilerInfo:
        path = shutil.which(self.config.compiler)
        if path is None:
            return CompilerInfo("missing", detail=f"Clang executable {self.config.compiler!r} was not found or is not executable")
        result = _run_process(
            (path, "--version"), cwd=self._directory("version"),
            environment=self._controlled_environment(), timeout=self.config.compile_timeout,
            output_bytes=self.config.max_output_bytes,
        )
        common = dict(path=path, stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)
        if result.timeout:
            return CompilerInfo("timeout", **common, detail="Compiler version probe timed out")
        if result.output_limit:
            return CompilerInfo("error", **common, detail="Compiler version output exceeded the capture limit and was truncated")
        if result.error is not None:
            return CompilerInfo("error", **common, detail=result.error)
        version = (result.stdout or result.stderr).strip()
        if result.returncode != 0 or "clang" not in version.lower():
            return CompilerInfo("error", **common, detail="The configured executable did not report a successful Clang version")
        return CompilerInfo("available", **common, version=version)

    def compile_source(
        self, source: str, *, label: str = "program", observation_file: str | None = None,
    ) -> CompilationResult:
        """Compile one independent source into a context-owned executable."""
        self._active()
        if not isinstance(source, str):
            raise ValueError("source must be a string")
        if observation_file is not None and not _valid_observation_filename(observation_file):
            raise ValueError("observation_file must be a private plain filename")
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if self.compiler_info.status != "available":
            status = "timeout" if self.compiler_info.status == "timeout" else "unavailable"
            return CompilationResult(
                status, detail=self.compiler_info.detail, source_sha256=source_sha256,
                stdout=self.compiler_info.stdout, stderr=self.compiler_info.stderr,
                returncode=self.compiler_info.returncode,
            )
        command: tuple[str, ...] = ()
        try:
            # Labels never enter a shell or determine file paths. Separate
            # numbered directories provide collision-free baseline/variant builds.
            directory = self._directory("build")
            source_path, executable = directory / "program.c", directory / "program"
            source_path.write_text(source, encoding="utf-8")
            command = (self.compiler_info.path, *self.config.flags, str(source_path), "-o", str(executable))
            result = _run_process(
                command, cwd=directory, environment=self._controlled_environment(),
                timeout=self.config.compile_timeout, output_bytes=self.config.max_output_bytes,
            )
        except OSError as error:
            return CompilationResult("os_error", command=command, detail=str(error), source_sha256=source_sha256)
        fields = dict(
            command=command, returncode=result.returncode, stdout=result.stdout,
            stderr=result.stderr, source_sha256=source_sha256,
        )
        if result.timeout:
            return CompilationResult("timeout", **fields, detail="Clang compilation timed out; its process group was terminated")
        if result.output_limit:
            return CompilationResult("output_limit", **fields, detail=f"Compiler output exceeded max_output_bytes={self.config.max_output_bytes}; captures were truncated")
        if result.error is not None:
            return CompilationResult("os_error", **fields, detail=result.error)
        if result.returncode != 0:
            return CompilationResult("failure", **fields, detail="Clang compilation failed; inspect compiler diagnostics")
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return CompilationResult("failure", **fields, detail="Clang returned success without producing an executable artifact")
        artifact = CompiledArtifact(executable, source_sha256, self.config.sanitize, observation_file)
        return CompilationResult("success", artifact=artifact, **fields)

    def execute(self, artifact: CompiledArtifact, case: ExecutionCase | None = None) -> ExecutionResult:
        """Execute once under controlled conditions and read full observation.

        Raw C without an observation protocol may succeed with ``return_value``
        absent. An exit status is never substituted for the full returned int.
        """
        return self._execute(artifact, case, measure=False).execution

    def timed_execute(self, artifact: CompiledArtifact, case: ExecutionCase | None = None) -> TimedExecution:
        """Run through the existing protections with an optional duration record.

        ``duration_ns`` is end-to-end process execution time measured with the
        monotonic high-resolution ``perf_counter_ns`` clock. It starts immediately
        before ``Popen`` and ends after process reaping, process-group cleanup and
        bounded output-capture joins. It includes process/sanitizer startup, the
        C observation harness, supervision and capture. It excludes compilation,
        run-directory/input-file setup, capture decoding and Python observation
        parsing. Nanosecond timestamps do not imply nanosecond timing accuracy.

        A launch failure has no duration. Started failures can retain durations
        for diagnosis; their failed observations are not successful samples.
        """
        return self._execute(artifact, case, measure=True)

    def _execute(
        self, artifact: CompiledArtifact, case: ExecutionCase | None, *, measure: bool,
    ) -> TimedExecution:
        from runtime.benchmark_models import TimedExecution

        self._active()
        duration_ns = None

        def observed(execution: ExecutionResult) -> TimedExecution:
            return TimedExecution(execution, duration_ns)

        case = case if case is not None else ExecutionCase()
        if not isinstance(artifact, CompiledArtifact) or not isinstance(case, ExecutionCase):
            raise ValueError("execute requires a CompiledArtifact and ExecutionCase")
        path = Path(artifact.path)
        command = (str(path), *case.arguments)
        if artifact.observation_file is not None and not _valid_observation_filename(artifact.observation_file):
            return observed(ExecutionResult("protocol_error", command=command, detail="Observation filename must remain private to the execution directory"))
        try:
            if not path.resolve().is_relative_to(self.root.resolve()):
                return observed(ExecutionResult("os_error", command=command, detail="Artifact is outside this runner's private workspace"))
            if not path.is_file():
                return observed(ExecutionResult("missing_executable", command=command, detail="Compiled executable does not exist"))
            directory = self._directory("run")
            result = _run_process(
                command, cwd=directory, environment=self._controlled_environment(case),
                timeout=self.config.execution_timeout, output_bytes=self.config.max_output_bytes,
                stdin=case.stdin, execution=True,
                address_space=self.config.memory_limit_mb * 1024 * 1024 if self.config.memory_limit_mb is not None else None,
                measure=measure,
            )
            duration_ns = result.duration_ns
        except OSError as error:
            return observed(ExecutionResult("os_error", command=command, detail=str(error)))
        process_signal = -result.returncode if result.returncode is not None and result.returncode < 0 else None
        fields = dict(
            command=command, process_returncode=result.returncode, stdout=result.stdout,
            stderr=result.stderr, signal=process_signal,
        )
        if result.timeout:
            return observed(ExecutionResult("timeout", **fields, detail="Execution timed out; its process group was terminated"))
        if result.output_limit:
            return observed(ExecutionResult("output_limit", **fields, detail=f"Execution output exceeded max_output_bytes={self.config.max_output_bytes}; captures were truncated"))
        if result.error is not None:
            status = "missing_executable" if not path.exists() else "os_error"
            return observed(ExecutionResult(status, **fields, detail=result.error))
        if artifact.sanitized and result.returncode != 0 and any(
            marker in result.stderr.lower() for marker in ("runtime error:", "undefinedbehaviorsanitizer", "ubsan:")
        ):
            return observed(ExecutionResult("undefined_behavior", **fields, detail="UndefinedBehaviorSanitizer reported a runtime arithmetic or C-language fault"))
        if process_signal is not None:
            return observed(ExecutionResult("signal", **fields, detail=f"Program terminated by signal {process_signal}"))
        if result.returncode != 0:
            return observed(ExecutionResult("nonzero_exit", **fields, detail="Process returned a nonzero infrastructure status; no full return value was accepted"))
        if artifact.observation_file is None:
            return observed(ExecutionResult("success", **fields))
        try:
            observation_path = directory / artifact.observation_file
            # Opening a FIFO/device here could block beyond the subprocess
            # deadline. Only the ordinary private file produced by the harness
            # is a protocol observation; links cannot redirect the read.
            if observation_path.is_symlink() or not observation_path.is_file():
                raise ValueError("Observation is missing or is not a regular private file")
            with observation_path.open("rb") as stream:
                observation = stream.read(self.config.max_output_bytes + 1)
            if len(observation) > self.config.max_output_bytes:
                return observed(ExecutionResult("output_limit", **fields, detail="Observation file exceeded max_output_bytes and was rejected"))
            from runtime.harness import parse_observation
            returned_int = parse_observation(observation.decode("utf-8"))
        except (OSError, ValueError, UnicodeError) as error:
            return observed(ExecutionResult("protocol_error", **fields, detail=f"Invalid or missing full-return observation: {error}"))
        return observed(ExecutionResult("success", return_value=returned_int, **fields))


def compile_source(
    source: str, config: CompileConfig | None = None, *, workspace: CompilerRunner,
    label: str = "program", observation_file: str | None = None,
) -> CompilationResult:
    """Delegate without hiding the executable's required workspace lifetime."""
    if config is not None and config != workspace.config:
        raise ValueError("config must match the active workspace configuration")
    return workspace.compile_source(source, label=label, observation_file=observation_file)


def execute(
    artifact: CompiledArtifact, case: ExecutionCase | None = None, config: CompileConfig | None = None,
    *, workspace: CompilerRunner,
) -> ExecutionResult:
    """Delegate one execution to the context owning its compiled artifact."""
    if config is not None and config != workspace.config:
        raise ValueError("config must match the active workspace configuration")
    return workspace.execute(artifact, case)
