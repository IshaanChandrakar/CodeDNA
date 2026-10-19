"""Regressions for process completion, bounded capture and infrastructure errors."""

from io import BytesIO
from pathlib import Path
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from runtime import compiler_runner as runner_module
from runtime.compiler_runner import CompilerRunner
from runtime.models import CompileConfig, CompiledArtifact, CompilerInfo


class _InlineCapture:
    """Run the real bounded capture synchronously in process lifecycle tests."""

    def __init__(self, *, target, args, daemon):
        self.target, self.args = target, args
        self.ident = None

    def start(self):
        self.ident = 1
        self.target(*self.args)

    def join(self, **options):
        pass

    def is_alive(self):
        return False


def _expired_process(monkeypatch, *, completed):
    instances = []

    class Process:
        def __init__(self, *arguments, **options):
            self.stdout, self.stderr = BytesIO(), BytesIO()
            self.returncode = None
            self.killed = False
            self.polls = 0
            instances.append(self)

        def poll(self):
            self.polls += 1
            if completed:
                self.returncode = 0
            return self.returncode

        def wait(self, **options):
            self.returncode = -9 if self.killed and not completed else 0
            return self.returncode

    first_clock = True

    def clock():
        nonlocal first_clock
        if first_clock:
            first_clock = False
            return 100.0
        return 102.0

    def kill(process):
        process.killed = True

    monkeypatch.setattr(runner_module.subprocess, "Popen", Process)
    monkeypatch.setattr(runner_module.threading, "Thread", _InlineCapture)
    monkeypatch.setattr(runner_module.time, "monotonic", clock)
    monkeypatch.setattr(runner_module, "_kill_group", kill)
    return instances


def test_completed_process_is_reaped_before_expired_watchdog_is_classified(tmp_path, monkeypatch):
    processes = _expired_process(monkeypatch, completed=True)
    result = runner_module._run_process(
        ("completed-fixture",), cwd=tmp_path, environment={}, timeout=1,
        output_bytes=1024,
    )
    assert result.timeout is False
    assert result.returncode == 0
    assert result.error is None
    assert processes[0].polls > 0


def test_live_process_at_expired_watchdog_is_still_terminated(tmp_path, monkeypatch):
    processes = _expired_process(monkeypatch, completed=False)
    result = runner_module._run_process(
        ("live-fixture",), cwd=tmp_path, environment={}, timeout=1,
        output_bytes=1024,
    )
    assert result.timeout is True
    assert result.returncode == -9
    assert processes[0].killed


def test_capture_file_failure_is_an_os_error_not_an_output_limit(tmp_path, monkeypatch):
    class Process:
        def __init__(self, *arguments, **options):
            self.stdout, self.stderr = BytesIO(), BytesIO()
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, **options):
            self.returncode = -9
            return self.returncode

    original_open = Path.open

    def failing_capture_open(path, mode="r", *arguments, **options):
        if path.name in {"stdout.bin", "stderr.bin"} and "w" in mode:
            raise OSError("fixture capture storage unavailable")
        return original_open(path, mode, *arguments, **options)

    monkeypatch.setattr(CompilerRunner, "_detect_compiler", lambda runner: CompilerInfo("available", path="fixture-clang"))
    monkeypatch.setattr(runner_module.subprocess, "Popen", Process)
    monkeypatch.setattr(runner_module.threading, "Thread", _InlineCapture)
    monkeypatch.setattr(runner_module, "_kill_group", lambda process: None)
    monkeypatch.setattr(Path, "open", failing_capture_open)
    with CompilerRunner(CompileConfig(sanitize=False)) as runner:
        executable = runner.root / "fixture-program"
        executable.write_text("fixture executable")
        artifact = CompiledArtifact(executable, "fixture-source-sha256", False)
        result = runner.execute(artifact)
    assert result.status == "os_error"
    assert result.return_value is None
    assert "fixture capture storage unavailable" in result.detail


def test_single_short_write_over_limit_is_detected_before_deadline(tmp_path):
    # BufferedReader.read(8192) must not wait for EOF/full-buffer completion:
    # this flushed write already exceeds the configured 1024-byte boundary.
    captures_before = set(threading.enumerate())
    result = runner_module._run_process(
        (sys.executable, "-c", "import os,time; os.write(1,b'x'*1025); time.sleep(5)"),
        cwd=tmp_path, environment=dict(os.environ), timeout=1,
        output_bytes=1024,
    )
    assert result.output_limit is True
    assert result.timeout is False
    assert result.error is None
    assert result.stdout == "x" * 1024
    assert len((tmp_path / "stdout.bin").read_bytes()) == 1024
    assert set(threading.enumerate()) <= captures_before


def test_stream_limit_is_reported_while_writer_still_holds_pipe_open(tmp_path):
    reader, writer = os.pipe()
    limited, failures = threading.Event(), []
    capture = threading.Thread(
        target=runner_module._capture_pipe,
        args=(os.fdopen(reader, "rb"), tmp_path / "capture.bin", 1024, limited, failures),
    )
    capture.start()
    try:
        os.write(writer, b"x" * 1025)
        # No EOF/full8192-byte buffer is available. The byte violation alone
        # must wake supervision, including when a descendant owns this writer.
        assert limited.wait(timeout=2), "Exceeded limit was hidden until EOF"
    finally:
        os.close(writer)
        capture.join(timeout=2)
    assert not capture.is_alive()
    assert not failures
    assert (tmp_path / "capture.bin").read_bytes() == b"x" * 1024


@pytest.mark.parametrize("completed,second_error", [(True, ProcessLookupError), (False, None), (True, PermissionError)])
def test_group_cleanup_reaps_zombie_permission_race_without_hiding_live_errors(monkeypatch, completed, second_error):
    calls = []

    class Process:
        pid = 1234

        def poll(self):
            calls.append("poll")
            return 0 if completed else None

        def wait(self, *, timeout):
            calls.append("wait")
            if not completed:
                raise subprocess.TimeoutExpired("fixture", timeout)
            return 0

    def kill_group(pid, requested_signal):
        assert pid == 1234 and requested_signal == signal.SIGKILL
        calls.append("killpg")
        raise PermissionError("fixture EPERM") if calls.count("killpg") == 1 else second_error()

    monkeypatch.setattr(runner_module.os, "killpg", kill_group)
    if completed and second_error is ProcessLookupError:
        runner_module._kill_group(Process())
        assert calls == ["killpg", "wait", "killpg"]
    else:
        with pytest.raises(PermissionError):
            runner_module._kill_group(Process())
        assert calls[0] == "killpg" and "wait" in calls
        assert calls.count("killpg") > 1 if completed else calls.count("killpg") == 1


@pytest.mark.integration
@pytest.mark.skipif(os.name != "posix", reason="Process groups require POSIX")
def test_real_exited_unreaped_leader_can_be_cleaned_up_without_an_os_error():
    process = subprocess.Popen(["/usr/bin/true"], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while True:
            # poll()/wait() would reap the very state being tested. Observe it
            # externally, then let the production cleanup handle Darwin EPERM.
            state = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(process.pid)],
                capture_output=True, text=True, timeout=2, check=False,
            ).stdout.strip()
            if state.startswith("Z"):
                break
            assert time.monotonic() < deadline, f"Child did not exit: {state}"
            time.sleep(0.01)
        runner_module._kill_group(process)
        assert process.wait(timeout=2) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)


@pytest.mark.parametrize("interrupted", [True, False])
def test_failed_cleanup_preserves_primary_failure_and_attempts_bounded_reap_and_joins(tmp_path, monkeypatch, interrupted):
    events = []
    instances = []

    class Process:
        stdout, stderr = BytesIO(), BytesIO()
        waits = 0

        def __init__(self, *arguments, **options):
            instances.append(self)

        def wait(self, *, timeout):
            assert 0 < timeout <= 1
            self.waits += 1
            events.append("wait")
            if interrupted and self.waits == 1:
                raise KeyboardInterrupt("fixture original interrupt")
            raise subprocess.TimeoutExpired("fixture unkillable child", timeout)

    class Capture:
        def __init__(self, **options):
            self.ident = None
            self.number = sum(event == "start" for event in events)

        def start(self):
            events.append("start")
            if not interrupted and self.number == 1:
                raise RuntimeError("fixture original capture-start failure")
            self.ident = self.number + 1

        def join(self, *, timeout):
            assert self.ident is not None, "An unstarted capture must not be joined"
            assert 0 < timeout <= 1
            events.append(f"join {self.number}")

    def failed_kill(process):
        events.append("kill")
        raise PermissionError("fixture cleanup EPERM")

    monkeypatch.setattr(runner_module.subprocess, "Popen", Process)
    monkeypatch.setattr(runner_module.threading, "Thread", Capture)
    monkeypatch.setattr(runner_module, "_kill_group", failed_kill)
    options = dict(cwd=tmp_path, environment={}, timeout=1, output_bytes=1024, measure=True)
    if interrupted:
        with pytest.raises(KeyboardInterrupt, match="fixture original interrupt") as caught:
            runner_module._run_process(("fixture",), **options)
        assert "fixture cleanup EPERM" in " ".join(caught.value.__notes__)
        assert events[-2:] == ["join 0", "join 1"]
    else:
        result = runner_module._run_process(("fixture",), **options)
        assert "fixture original capture-start failure" in result.error
        assert "fixture cleanup EPERM" in result.error
        assert "fixture unkillable child" in result.error
        assert type(result.duration_ns) is int and result.duration_ns >= 0
        assert not result.timeout and not result.output_limit
        assert events[-1] == "join 0" and "join 1" not in events
    assert len(instances) == 1
    assert instances[0].waits == (2 if interrupted else 1)
