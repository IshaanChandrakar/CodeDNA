"""Precise timing boundaries and real executions through the Phase 4 runner."""

from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import shutil
import signal

import pytest

from compiler.parser import parse
from runtime import compiler_runner as runner_module
from runtime.benchmark_models import TimedExecution
from runtime.compiler_runner import CompilerRunner
from runtime.harness import make_harness
from runtime.models import CompileConfig, CompiledArtifact, ExecutionCase, ExecutionResult


def _compiled(runner, source, *, observation_file=None):
    result = runner.compile_source(source, observation_file=observation_file)
    assert result.status == "success", (result.status, result.detail, result.stderr)
    return result.artifact


def _harness(runner, source="int main(){return 257;}"):
    harness = make_harness(parse(source))
    return _compiled(runner, harness.source, observation_file=harness.observation_file)


def _require_clang():
    if shutil.which("clang") is None:
        pytest.skip("Timed execution integration requires a real Clang executable")


def test_clock_starts_after_input_preparation_and_ends_after_cleanup_before_decoding(tmp_path, monkeypatch):
    events = []
    clock_values = iter((10_000, 10_450))
    decoded = runner_module._read_capture

    def clock():
        assert (tmp_path / "stdin.bin").read_bytes() == b"fixture input"
        events.append("clock")
        return next(clock_values)

    def limits(*arguments):
        events.append("resource setup")
        return None

    class Process:
        stdout = BytesIO(b"captured output")
        stderr = BytesIO(b"captured error")

        def __init__(self, command, **options):
            assert options["stdin"].read() == b"fixture input"
            assert events[-1] == "clock"
            events.append("Popen")

        def wait(self, **options):
            events.append("reaped")
            return 0

    class CaptureThread:
        def __init__(self, *, target, args, daemon):
            self.target, self.args = target, args
            self.ident = None

        def start(self):
            self.ident = 1
            self.target(*self.args)

        def join(self, **options):
            events.append("capture joined")

        def is_alive(self):
            return False

    def read_capture(path):
        assert events.count("clock") == 2
        events.append("decode")
        return decoded(path)

    monkeypatch.setattr(runner_module.time, "perf_counter_ns", clock)
    monkeypatch.setattr(runner_module, "_resource_setup", limits)
    monkeypatch.setattr(runner_module.subprocess, "Popen", Process)
    monkeypatch.setattr(runner_module.threading, "Thread", CaptureThread)
    monkeypatch.setattr(runner_module, "_kill_group", lambda process: events.append("group cleanup"))
    monkeypatch.setattr(runner_module, "_read_capture", read_capture)
    result = runner_module._run_process(
        ("fixture-program",), cwd=tmp_path, environment={}, timeout=10,
        output_bytes=1024, stdin=b"fixture input", execution=True, measure=True,
    )
    assert result.duration_ns == 450
    assert result.returncode == 0
    assert result.stdout == "captured output" and result.stderr == "captured error"
    assert events == [
        "resource setup", "clock", "Popen", "reaped", "group cleanup",
        "capture joined", "capture joined", "clock", "decode", "decode",
    ]


def test_failed_process_launch_never_has_a_duration(tmp_path, monkeypatch):
    calls = []

    def failed_start(*args, **kwargs):
        raise FileNotFoundError("fixture executable disappeared")

    monkeypatch.setattr(runner_module.time, "perf_counter_ns", lambda: calls.append("clock") or 100)
    monkeypatch.setattr(runner_module.subprocess, "Popen", failed_start)
    result = runner_module._run_process(
        ("missing-program",), cwd=tmp_path, environment={}, timeout=1,
        output_bytes=1024, measure=True,
    )
    assert result.duration_ns is None
    assert result.error and "disappeared" in result.error
    assert calls == ["clock"]


def test_input_setup_failure_does_not_start_the_measurement(tmp_path, monkeypatch):
    calls = []

    def failed_write(path, content):
        raise PermissionError("fixture input creation denied")

    monkeypatch.setattr(Path, "write_bytes", failed_write)
    monkeypatch.setattr(runner_module.time, "perf_counter_ns", lambda: calls.append("clock") or 100)
    result = runner_module._run_process(
        ("unused-program",), cwd=tmp_path, environment={}, timeout=1,
        output_bytes=1024, measure=True,
    )
    assert result.duration_ns is None
    assert result.error and "denied" in result.error
    assert calls == []


def test_keyboard_interrupt_terminates_group_reaps_and_joins_before_propagating(tmp_path, monkeypatch):
    events = []

    class InterruptedProcess:
        stdout, stderr = BytesIO(b""), BytesIO(b"")
        interrupted = False

        def __init__(self, *args, **kwargs):
            pass

        def wait(self, **options):
            if not self.interrupted:
                self.interrupted = True
                events.append("interrupt")
                raise KeyboardInterrupt
            events.append("reaped")
            return -9

    class CaptureThread:
        def __init__(self, **options):
            self.ident = None

        def start(self):
            self.ident = 1

        def join(self, **options):
            events.append("joined")

    monkeypatch.setattr(runner_module.subprocess, "Popen", InterruptedProcess)
    monkeypatch.setattr(runner_module.threading, "Thread", CaptureThread)
    monkeypatch.setattr(runner_module, "_kill_group", lambda process: events.append("group terminated"))
    with pytest.raises(KeyboardInterrupt):
        runner_module._run_process(("fixture",), cwd=tmp_path, environment={}, timeout=10, output_bytes=1024)
    assert events == ["interrupt", "group terminated", "reaped", "joined", "joined"]


def test_keyboard_interrupt_during_thread_start_is_preserved_after_child_cleanup(tmp_path, monkeypatch):
    events = []

    class Process:
        stdout, stderr = BytesIO(b""), BytesIO(b"")

        def __init__(self, *args, **options):
            pass

        def wait(self, **options):
            events.append("reaped")
            return -9

    class InterruptedThread:
        ident = None

        def __init__(self, **options):
            pass

        def start(self):
            events.append("capture interrupted")
            raise KeyboardInterrupt

        def join(self, **options):
            pytest.fail("An unstarted capture must not be joined")

    monkeypatch.setattr(runner_module.subprocess, "Popen", Process)
    monkeypatch.setattr(runner_module.threading, "Thread", InterruptedThread)
    monkeypatch.setattr(runner_module, "_kill_group", lambda process: events.append("group terminated"))
    with pytest.raises(KeyboardInterrupt):
        runner_module._run_process(("fixture",), cwd=tmp_path, environment={}, timeout=10, output_bytes=1024)
    assert events == ["capture interrupted", "group terminated", "reaped"]


def test_thread_start_failure_is_a_structured_os_error_after_child_cleanup(tmp_path, monkeypatch):
    events = []

    class Process:
        stdout, stderr = BytesIO(b""), BytesIO(b"")

        def __init__(self, *args, **options):
            pass

        def wait(self, **options):
            events.append("reaped")
            return -9

    class FailedThread:
        ident = None

        def __init__(self, **options):
            pass

        def start(self):
            events.append("capture failed")
            raise RuntimeError("fixture thread resource exhaustion")

        def join(self, **options):
            pytest.fail("An unstarted capture must not be joined")

    with CompilerRunner(CompileConfig(compiler=str(tmp_path / "missing-clang"))) as runner:
        path = runner.root / "program"
        path.touch()
        monkeypatch.setattr(runner_module.subprocess, "Popen", Process)
        monkeypatch.setattr(runner_module.threading, "Thread", FailedThread)
        monkeypatch.setattr(runner_module, "_kill_group", lambda process: events.append("group terminated"))
        result = runner.execute(CompiledArtifact(path, "sourcehash", False))
    assert result.status == "os_error" and result.return_value is None
    assert "thread resource exhaustion" in result.detail
    assert events == ["capture failed", "group terminated", "reaped"]


@pytest.mark.parametrize("failure", [KeyboardInterrupt, RuntimeError, SystemExit])
def test_interrupted_discovery_cleans_workspace_even_when_enter_fails(tmp_path, monkeypatch, failure):
    def failed_discovery(runner):
        assert runner.root.is_dir()
        (runner.root / "probe-artifact").touch()
        raise failure("fixture discovery interruption")

    monkeypatch.setattr(CompilerRunner, "_detect_compiler", failed_discovery)
    runner = CompilerRunner(CompileConfig(compiler=str(tmp_path / "unused-clang")))
    with pytest.raises(failure, match="fixture discovery interruption"):
        with runner:
            pytest.fail("A failed discovery cannot enter the calling context")
    assert not runner.root.exists()
    assert runner._temporary is None


def test_ordinary_and_timed_methods_delegate_once_to_the_same_execution_path(tmp_path, monkeypatch):
    calls = []
    with CompilerRunner(CompileConfig(compiler=str(tmp_path / "missing-clang"))) as runner:
        path = runner.root / "program"
        path.touch()
        artifact = CompiledArtifact(path, "sourcehash", False)
        case = ExecutionCase(stdin=b"input", arguments=("literal argument",), environment=(("CUSTOM", "fixture"),))

        def process(command, **options):
            calls.append((command, options))
            return runner_module._ProcessResult(0, duration_ns=321 if options["measure"] else None)

        monkeypatch.setattr(runner_module, "_run_process", process)
        ordinary = runner.execute(artifact, case)
        timed = runner.timed_execute(artifact, case)
    assert isinstance(ordinary, ExecutionResult)
    assert isinstance(timed, TimedExecution)
    assert timed.execution == ordinary and timed.duration_ns == 321
    assert len(calls) == 2
    assert [call[1]["measure"] for call in calls] == [False, True]
    assert calls[0][0] == calls[1][0] == (str(path), "literal argument")
    for _, options in calls:
        assert options["stdin"] == b"input"
        assert options["environment"]["CUSTOM"] == "fixture"
        assert options["execution"] is True
        assert options["timeout"] == runner.config.execution_timeout
        assert options["output_bytes"] == runner.config.max_output_bytes


@pytest.mark.integration
@pytest.mark.parametrize("optimization", ["O0", "O2"])
def test_real_timed_clang_preserves_full_return_and_phase4_result_fields(optimization):
    _require_clang()
    with CompilerRunner(CompileConfig(optimization=optimization)) as runner:
        artifact = _harness(runner, "int main(){int x=0;for(int i=0;i<4;i=i+1)x=x+i;return x+257;}")
        ordinary = runner.execute(artifact)
        timed = runner.timed_execute(artifact)
        assert timed.execution == ordinary
        assert timed.execution.return_value == 263
        assert timed.execution.process_returncode == 0
        assert timed.execution.status == "success"
        assert type(timed.duration_ns) is int and timed.duration_ns > 0
        assert "duration_ns" not in asdict(ordinary)
        assert "duration_ns" not in asdict(timed.execution)


@pytest.mark.integration
def test_compilation_and_plain_execution_do_not_read_the_performance_clock(monkeypatch):
    _require_clang()
    calls = []
    timestamps = iter((1_000, 1_250))

    def clock():
        calls.append("clock")
        return next(timestamps)

    monkeypatch.setattr(runner_module.time, "perf_counter_ns", clock)
    with CompilerRunner() as runner:
        artifact = _harness(runner)
        assert calls == []
        assert runner.execute(artifact).return_value == 257
        assert calls == []
        timed = runner.timed_execute(artifact)
        assert calls == ["clock", "clock"]
        assert timed.duration_ns == 250 and timed.execution.return_value == 257


@pytest.mark.integration
def test_duration_stops_before_python_observation_parsing(monkeypatch):
    _require_clang()
    from runtime import harness as harness_module

    with CompilerRunner() as runner:
        artifact = _harness(runner)
        calls = []
        timestamps = iter((2_000, 2_700))
        original_parser = harness_module.parse_observation

        def clock():
            calls.append("clock")
            return next(timestamps)

        def parse_after_timing(text):
            assert calls == ["clock", "clock"]
            calls.append("parse observation")
            return original_parser(text)

        monkeypatch.setattr(runner_module.time, "perf_counter_ns", clock)
        monkeypatch.setattr(harness_module, "parse_observation", parse_after_timing)
        timed = runner.timed_execute(artifact)
        assert timed.duration_ns == 700 and timed.execution.return_value == 257
        assert calls == ["clock", "clock", "parse observation"]


@pytest.mark.integration
def test_started_timeout_retains_diagnostic_duration_and_no_return_value():
    _require_clang()
    with CompilerRunner(CompileConfig(execution_timeout=0.1)) as runner:
        artifact = _harness(runner, "int main(){for(int i=0;i<1;i=i+0);return 0;}")
        timed = runner.timed_execute(artifact)
        assert timed.execution.status == "timeout"
        assert timed.execution.return_value is None
        assert type(timed.duration_ns) is int and timed.duration_ns > 0


@pytest.mark.integration
def test_started_protocol_failure_retains_duration_without_fabricating_observation():
    _require_clang()
    with CompilerRunner() as runner:
        artifact = _compiled(runner, "int main(void){return 0;}", observation_file="missing.json")
        timed = runner.timed_execute(artifact)
        assert timed.execution.status == "protocol_error"
        assert timed.execution.return_value is None and timed.execution.process_returncode == 0
        assert type(timed.duration_ns) is int and timed.duration_ns > 0


@pytest.mark.parametrize("failure", ["missing", "outside", "invalid_observation", "nonexecutable"])
def test_prelaunch_and_launch_failures_have_no_duration(tmp_path, monkeypatch, failure):
    with CompilerRunner(CompileConfig(compiler=str(tmp_path / "missing-clang"))) as runner:
        path = runner.root / "program"
        observation = None
        expected = "missing_executable"
        if failure == "outside":
            path, expected = tmp_path / "foreign", "os_error"
        elif failure == "invalid_observation":
            observation, expected = "../foreign.json", "protocol_error"
        elif failure == "nonexecutable":
            path.touch()
            path.chmod(0o600)
            expected = "os_error"
        calls = []
        monkeypatch.setattr(runner_module.time, "perf_counter_ns", lambda: calls.append("clock") or 100)
        timed = runner.timed_execute(CompiledArtifact(path, "sourcehash", False, observation))
        assert timed.execution.status == expected
        assert timed.duration_ns is None
        assert calls == (["clock"] if failure == "nonexecutable" else [])


@pytest.mark.integration
@pytest.mark.parametrize("source, expected", [
    ("#include <signal.h>\nint main(void){raise(SIGTERM);return 0;}", "signal"),
    ("int main(void){return 17;}", "nonzero_exit"),
    ("int main(void){volatile int x=2147483647;return x+1;}", "undefined_behavior"),
])
def test_started_process_failures_retain_the_existing_classification(source, expected):
    _require_clang()
    with CompilerRunner() as runner:
        timed = runner.timed_execute(_compiled(runner, source))
        assert timed.execution.status == expected
        assert timed.execution.return_value is None
        assert type(timed.duration_ns) is int and timed.duration_ns > 0
        if expected == "signal":
            assert timed.execution.signal == signal.SIGTERM


@pytest.mark.integration
def test_timed_execution_keeps_existing_output_limits():
    _require_clang()
    with CompilerRunner(CompileConfig(max_output_bytes=1024)) as runner:
        artifact = _compiled(runner, '#include <stdio.h>\nint main(void){for(int i=0;i<20000;i++)putchar(\'x\');return 0;}')
        timed = runner.timed_execute(artifact)
        assert timed.execution.status == "output_limit"
        assert len(timed.execution.stdout.encode()) <= 1024
        assert type(timed.duration_ns) is int and timed.duration_ns > 0
