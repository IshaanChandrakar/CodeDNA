"""Real Clang builds, full observations, bounded failures, and artifact lifetime."""

import hashlib
import json
import os
import shutil
import shlex
import signal
import subprocess
import sys
import time

import pytest

from compiler.parser import parse
from runtime.compiler_runner import CompilerRunner, compile_source, execute
from runtime.harness import make_harness
from runtime.models import CompileConfig, CompiledArtifact, ExecutionCase


@pytest.fixture
def clang_runner():
    if shutil.which("clang") is None:
        pytest.skip("Real Clang integration requires a clang executable")
    with CompilerRunner(CompileConfig(sanitize=False)) as runner:
        assert runner.compiler_info.status == "available", runner.compiler_info
        yield runner


def compiled(runner, source, **options):
    result = runner.compile_source(source, **options)
    assert result.status == "success", (result.status, result.detail, result.stderr)
    assert result.artifact is not None
    return result.artifact


def harness_artifact(runner, source):
    harness = make_harness(parse(source))
    return compiled(runner, harness.source, observation_file=harness.observation_file)


def fake_compiler(tmp_path, body):
    path = tmp_path / "clang fixture with spaces"
    path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


@pytest.mark.integration
@pytest.mark.parametrize("expression, expected", [
    ("0", 0), ("1", 1), ("-1", -1), ("256", 256), ("257", 257),
    ("65536", 65536), ("2147483647", 2147483647), ("-2147483647-1", -2147483648),
    ("-7/3", -2), ("-7%3", -1), ("7%-3", 1),
])
def test_real_harness_observes_complete_signed_integer_without_exit_status_aliasing(clang_runner, expression, expected):
    artifact = harness_artifact(clang_runner, f"int main(){{return {expression};}}")
    result = clang_runner.execute(artifact)
    assert result.status == "success"
    assert result.process_returncode == 0
    assert result.return_value == expected
    assert result.stdout == result.stderr == ""


@pytest.mark.integration
@pytest.mark.parametrize("optimization", ["O0", "O2"])
def test_explicit_optimization_and_sanitizer_flags_compile_and_run(optimization):
    if shutil.which("clang") is None:
        pytest.skip("Real Clang integration requires a clang executable")
    with CompilerRunner(CompileConfig(optimization=optimization)) as runner:
        harness = make_harness(parse("int main(){int x=0;for(int i=0;i<4;i=i+1)x=x+i;return x+257;}"))
        compilation = runner.compile_source(harness.source, observation_file=harness.observation_file)
        assert compilation.status == "success", compilation.stderr
        assert compilation.command[1:5] == ("-std=c11", f"-{optimization}", "-fsanitize=undefined", "-fno-sanitize-recover=all")
        assert compilation.artifact.sanitized
        result = runner.execute(compilation.artifact)
        assert (result.status, result.process_returncode, result.return_value) == ("success", 0, 263)


@pytest.mark.integration
def test_raw_success_does_not_invent_a_full_integer_from_process_status(clang_runner):
    artifact = compiled(clang_runner, "int main(void){return 0;}")
    result = clang_runner.execute(artifact)
    assert result.status == "success" and result.process_returncode == 0
    assert result.return_value is None


@pytest.mark.integration
def test_raw_nonzero_exit_is_a_failure_without_full_return_value(clang_runner):
    artifact = compiled(clang_runner, "int main(void){return 17;}")
    result = clang_runner.execute(artifact)
    assert result.status == "nonzero_exit"
    assert result.process_returncode == 17 and result.return_value is None


@pytest.mark.integration
def test_invalid_c_preserves_clang_diagnostics_and_command(clang_runner):
    result = clang_runner.compile_source("int main( { return 0; }")
    assert result.status == "failure"
    assert result.returncode != 0 and result.artifact is None
    assert "error:" in result.stderr
    assert result.command[0] == clang_runner.compiler_info.path
    assert result.source_sha256 == hashlib.sha256(b"int main( { return 0; }").hexdigest()


@pytest.mark.integration
def test_unsupported_option_is_a_structured_compilation_failure():
    if shutil.which("clang") is None:
        pytest.skip("Real Clang integration requires a clang executable")
    with CompilerRunner(CompileConfig(sanitize=False, extra_flags=("-Werror", "-Wcodedna-intentionally-invalid-option"))) as runner:
        result = runner.compile_source("int main(void){return 0;}")
        assert result.status == "failure"
        assert "-Wcodedna-intentionally-invalid-option" in result.command
        assert "error:" in result.stderr


def test_missing_compiler_is_explicit_and_never_produces_an_artifact(tmp_path):
    with CompilerRunner(CompileConfig(compiler=str(tmp_path / "absent-clang"))) as runner:
        assert runner.compiler_info.status == "missing"
        result = runner.compile_source("int main(void){return 0;}")
        assert result.status == "unavailable" and result.artifact is None
        assert "not found" in result.detail


def test_non_clang_compiler_and_failed_version_probes_are_unavailable(tmp_path):
    path = fake_compiler(tmp_path, "print('some other compiler 1.0')\n")
    with CompilerRunner(CompileConfig(compiler=str(path))) as runner:
        assert runner.compiler_info.status == "error"
        assert "other compiler" in runner.compiler_info.stdout
        assert runner.compile_source("int main(){return 0;}").status == "unavailable"


def test_version_probe_failure_captures_both_streams_and_status(tmp_path):
    path = fake_compiler(tmp_path, "import sys\nprint('clang fixture')\nprint('version failure', file=sys.stderr)\nsys.exit(7)\n")
    with CompilerRunner(CompileConfig(compiler=str(path))) as runner:
        assert runner.compiler_info.status == "error"
        assert runner.compiler_info.returncode == 7
        assert "clang fixture" in runner.compiler_info.stdout
        assert "version failure" in runner.compiler_info.stderr


def test_version_probe_timeout_is_structured(tmp_path):
    path = fake_compiler(tmp_path, "import time\ntime.sleep(20)\n")
    with CompilerRunner(CompileConfig(compiler=str(path), compile_timeout=0.1)) as runner:
        assert runner.compiler_info.status == "timeout"
        assert runner.compile_source("int main(){return 0;}").status == "timeout"


def test_version_probe_occurs_once_and_compilation_timeout_keeps_partial_diagnostics(tmp_path):
    log = tmp_path / "version-count.txt"
    # Keep the version branch in the shell itself: this case measures the
    # runner's timeout behavior, not cold Python interpreter launch time.
    path = tmp_path / "timeout clang fixture"
    path.write_text(f'''#!/bin/sh
if [ "$1" = "--version" ]; then
    printf 'probe\\n' >> {shlex.quote(str(log))}
    printf 'clang fixture 1.0\\n'
else
    printf 'started compilation\\n' >&2
    sleep 20
fi
''')
    path.chmod(0o700)
    with CompilerRunner(CompileConfig(compiler=str(path), compile_timeout=1.0)) as runner:
        for _ in range(2):
            result = runner.compile_source("int main(){return 0;}")
            assert result.status == "timeout" and result.artifact is None
            assert "started compilation" in result.stderr
        assert log.read_text().splitlines() == ["probe"]


def test_compiler_disappearing_after_detection_is_an_os_error(tmp_path):
    path = fake_compiler(tmp_path, "print('clang fixture 1.0')\n")
    with CompilerRunner(CompileConfig(compiler=str(path))) as runner:
        assert runner.compiler_info.status == "available"
        path.unlink()
        result = runner.compile_source("int main(){return 0;}")
        assert result.status == "os_error" and result.artifact is None


def test_success_without_a_binary_is_not_successful_compilation(tmp_path):
    path = fake_compiler(tmp_path, "print('clang fixture 1.0')\n")
    with CompilerRunner(CompileConfig(compiler=str(path))) as runner:
        result = runner.compile_source("int main(){return 0;}")
        assert result.status == "failure" and result.artifact is None
        assert "without producing" in result.detail


def test_compiler_output_is_bounded_and_marked_truncated(tmp_path):
    path = fake_compiler(tmp_path, "import sys\nif '--version' in sys.argv: print('clang fixture')\nelse: print('diagnostic '*10000, file=sys.stderr)\n")
    with CompilerRunner(CompileConfig(compiler=str(path), max_output_bytes=1024)) as runner:
        result = runner.compile_source("int main(){return 0;}")
        assert result.status == "output_limit" and result.artifact is None
        assert len(result.stderr.encode()) <= 1024
        assert "truncated" in result.detail
        assert all(path.stat().st_size <= 1024 for path in runner.root.rglob("stderr.bin"))


@pytest.mark.integration
def test_missing_executable_is_a_structured_failure(clang_runner):
    artifact = compiled(clang_runner, "int main(void){return 0;}")
    artifact.path.unlink()
    result = clang_runner.execute(artifact)
    assert result.status == "missing_executable" and result.return_value is None


@pytest.mark.integration
def test_executable_without_permission_is_an_os_error(clang_runner):
    artifact = compiled(clang_runner, "int main(void){return 0;}")
    artifact.path.chmod(0o600)
    result = clang_runner.execute(artifact)
    assert result.status == "os_error" and result.return_value is None


@pytest.mark.integration
def test_signal_termination_is_distinct_from_nonzero_exit(clang_runner):
    artifact = compiled(clang_runner, "#include <signal.h>\nint main(void){raise(SIGTERM);return 0;}")
    result = clang_runner.execute(artifact)
    assert result.status == "signal"
    assert result.signal == signal.SIGTERM
    assert result.process_returncode == -signal.SIGTERM
    assert result.return_value is None


@pytest.mark.integration
def test_infinite_program_is_terminated_by_execution_timeout():
    if shutil.which("clang") is None:
        pytest.skip("Real Clang integration requires a clang executable")
    with CompilerRunner(CompileConfig(execution_timeout=0.1, sanitize=False)) as runner:
        artifact = harness_artifact(runner, "int main(){for(int i=0;i<1;i=i+0);return 0;}")
        result = runner.execute(artifact)
        assert result.status == "timeout"
        assert result.return_value is None and result.process_returncode != 0


@pytest.mark.integration
def test_execution_output_is_bounded_and_never_a_success():
    if shutil.which("clang") is None:
        pytest.skip("Real Clang integration requires a clang executable")
    with CompilerRunner(CompileConfig(sanitize=False, max_output_bytes=1024)) as runner:
        artifact = compiled(runner, '#include <stdio.h>\nint main(void){for(int i=0;i<20000;i++) putchar(\'x\');return 0;}')
        result = runner.execute(artifact)
        assert result.status == "output_limit"
        assert len(result.stdout.encode()) <= 1024 and len(result.stderr.encode()) <= 1024
        assert "truncated" in result.detail
        assert all(path.stat().st_size <= 1024 for path in runner.root.rglob("stdout.bin"))


@pytest.mark.integration
@pytest.mark.parametrize("parent_returns", [False, True])
def test_descendant_processes_are_terminated_on_timeout_and_normal_parent_exit(parent_returns):
    if os.name != "posix" or shutil.which("clang") is None or shutil.which("ps") is None:
        pytest.skip("Process-group integration requires POSIX, Clang and ps")
    ending = "return 0;" if parent_returns else "for(;;)pause();"
    source = '''#include <stdio.h>
#include <unistd.h>
#include <sys/types.h>
int main(void){pid_t child=fork();if(child<0)return 5;
if(child==0){for(;;)pause();}
printf("%ld\\n",(long)child);fflush(stdout);
''' + ending + "}"
    with CompilerRunner(CompileConfig(sanitize=False, execution_timeout=1.0)) as runner:
        artifact = compiled(runner, source)
        result = runner.execute(artifact)
        assert result.status == ("success" if parent_returns else "timeout")
        child_pid = int(result.stdout.strip())
        deadline = time.monotonic() + 1
        while True:
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)], capture_output=True, text=True, check=False).stdout.strip()
            if not state or state.startswith("Z"):
                break
            if time.monotonic() >= deadline:
                pytest.fail(f"Descendant {child_pid} remained alive after process-group termination: {state}")
            time.sleep(0.01)


@pytest.mark.integration
def test_missing_observation_is_a_protocol_error_with_no_exit_value_fallback(clang_runner):
    artifact = compiled(clang_runner, "int main(void){return 0;}", observation_file="observation.json")
    result = clang_runner.execute(artifact)
    assert result.status == "protocol_error"
    assert result.process_returncode == 0 and result.return_value is None


@pytest.mark.integration
def test_fifo_observation_is_rejected_without_blocking_on_a_read(clang_runner):
    if os.name != "posix":
        pytest.skip("FIFO protocol failure requires POSIX")
    artifact = compiled(
        clang_runner,
        '#include <sys/stat.h>\nint main(void){return mkfifo("observation.json",0600);}',
        observation_file="observation.json",
    )
    result = clang_runner.execute(artifact)
    assert result.status == "protocol_error" and result.return_value is None
    assert "regular private file" in result.detail


@pytest.mark.integration
@pytest.mark.parametrize("observation", [
    "garbage", '{"protocol_version":1,"return_value":true}',
    '{"protocol_version":1,"return_value":2147483648}',
    '{"protocol_version":1,"return_value":1,"unexpected":2}',
    "x" * 5000,
])
def test_bad_observation_file_is_never_an_accepted_result(clang_runner, observation):
    source = '#include <stdio.h>\nint main(void){FILE *f=fopen("observation.json","w");fputs(' + json.dumps(observation) + ',f);fclose(f);return 0;}'
    artifact = compiled(clang_runner, source, observation_file="observation.json")
    result = clang_runner.execute(artifact)
    assert result.status == "protocol_error" and result.return_value is None


@pytest.mark.integration
def test_each_execution_has_a_fresh_observation_directory(clang_runner):
    artifact = harness_artifact(clang_runner, "int main(){return 257;}")
    first, second = clang_runner.execute(artifact), clang_runner.execute(artifact)
    assert (first.status, first.return_value) == ("success", 257)
    assert (second.status, second.return_value) == ("success", 257)
    assert len(tuple(clang_runner.root.rglob(artifact.observation_file))) == 2


@pytest.mark.integration
def test_arguments_stdin_and_controlled_environment_are_passed_without_a_shell(clang_runner, tmp_path):
    marker = tmp_path / "unwanted-shell-file"
    argument = f"$(touch {marker})"
    source = r'''#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv){
 char input[32]; if(fgets(input,sizeof(input),stdin)==NULL)return 5;
 printf("%s|%s|%s|%s|%s|%s",input,argv[1],getenv("CUSTOM"),getenv("LC_ALL"),getenv("TZ"),getenv("UBSAN_OPTIONS"));
 fputs("separate stderr",stderr);return 0;
}'''
    artifact = compiled(clang_runner, source)
    case = ExecutionCase(
        stdin=b"payload\n", arguments=(argument,),
        environment=(("CUSTOM", "fixture"), ("LC_ALL", "unknown"), ("TZ", "unknown"), ("UBSAN_OPTIONS", "halt_on_error=0")),
    )
    result = clang_runner.execute(artifact, case)
    assert result.status == "success"
    assert result.stdout.startswith(f"payload\n|{argument}|fixture|C|UTC|")
    assert "halt_on_error=1" in result.stdout
    assert result.stderr == "separate stderr"
    assert result.command[1:] == (argument,)
    assert not marker.exists()


@pytest.mark.integration
def test_identical_sources_get_distinct_private_builds_with_equal_hashes(clang_runner):
    first = clang_runner.compile_source("int main(void){return 0;}", label="../../danger;echo test")
    second = clang_runner.compile_source("int main(void){return 0;}", label="same")
    assert first.status == second.status == "success"
    assert first.artifact.path != second.artifact.path
    assert first.source_sha256 == second.source_sha256
    assert first.artifact.path.is_relative_to(clang_runner.root)
    assert second.artifact.path.is_relative_to(clang_runner.root)
    assert first.command[0] == second.command[0]
    assert first.command[1:3] == second.command[1:3] == ("-std=c11", "-O0")


@pytest.mark.integration
@pytest.mark.parametrize("operation", [
    "volatile int x=2147483647;int y=x+1;return y;",
    "volatile int x=65536;int y=x*x;return y;",
    "volatile int x=0;return 1/x;",
    "volatile int x=-2147483647-1;return x/-1;",
    "volatile int x=-2147483647-1;return x%-1;",
])
def test_real_ubsan_faults_are_undefined_behavior_instead_of_matching_results(operation):
    if shutil.which("clang") is None:
        pytest.skip("Real Clang integration requires a clang executable")
    with CompilerRunner() as runner:
        artifact = compiled(runner, "int main(void){" + operation + "}")
        result = runner.execute(artifact)
        assert result.status == "undefined_behavior", (result.status, result.stderr)
        assert result.process_returncode != 0 and result.return_value is None
        assert "runtime error:" in result.stderr.lower()


@pytest.mark.integration
def test_context_exit_cleans_sources_executables_captures_and_observations():
    if shutil.which("clang") is None:
        pytest.skip("Real Clang integration requires a clang executable")
    with CompilerRunner(CompileConfig(sanitize=False)) as runner:
        artifact = harness_artifact(runner, "int main(){return 3;}")
        assert runner.execute(artifact).return_value == 3
        root = runner.root
        assert root.exists() and artifact.path.exists()
        assert tuple(root.rglob("program.c")) and tuple(root.rglob("stdin.bin"))
    assert not root.exists() and not artifact.path.exists()
    with pytest.raises(RuntimeError, match="active with context"):
        runner.execute(artifact)


def test_context_cleans_up_even_when_calling_code_raises(tmp_path):
    path = fake_compiler(tmp_path, "print('clang fixture')\n")
    with pytest.raises(RuntimeError, match="intentional"):
        with CompilerRunner(CompileConfig(compiler=str(path))) as runner:
            root = runner.root
            raise RuntimeError("intentional")
    assert not root.exists()


def test_runner_requires_active_context_and_cannot_be_reentered(tmp_path):
    runner = CompilerRunner(CompileConfig(compiler=str(tmp_path / "missing")))
    with pytest.raises(RuntimeError, match="active with context"):
        runner.compile_source("int main(){return 0;}")
    with runner:
        with pytest.raises(RuntimeError, match="only be entered once"):
            runner.__enter__()
    runner.close()


@pytest.mark.integration
def test_top_level_delegates_keep_workspace_ownership_explicit(clang_runner):
    compilation = compile_source("int main(void){return 0;}", clang_runner.config, workspace=clang_runner)
    assert compilation.status == "success"
    assert execute(compilation.artifact, ExecutionCase(), clang_runner.config, workspace=clang_runner).status == "success"
    with pytest.raises(ValueError, match="match"):
        compile_source("int main(void){return 0;}", CompileConfig(), workspace=clang_runner)
    with pytest.raises(ValueError, match="match"):
        execute(compilation.artifact, config=CompileConfig(), workspace=clang_runner)


@pytest.mark.parametrize("filename", ["", ".", "..", "../observation.json", "/tmp/observation.json", "stdout.bin", "stdin.bin", "bad\0name"])
def test_observation_filename_cannot_escape_or_conflict_with_private_capture(tmp_path, filename):
    with CompilerRunner(CompileConfig(compiler=str(tmp_path / "missing"))) as runner:
        with pytest.raises(ValueError, match="private plain filename"):
            runner.compile_source("int main(void){return 0;}", observation_file=filename)


def test_artifact_from_another_workspace_is_not_executed(tmp_path):
    with CompilerRunner(CompileConfig(compiler=str(tmp_path / "missing"))) as runner:
        artifact = CompiledArtifact(tmp_path / "foreign-program", "sourcehash", False)
        result = runner.execute(artifact)
        assert result.status == "os_error"
        assert "outside" in result.detail


@pytest.mark.parametrize("filename", ["../outside.json", "/etc/passwd", "stdout.bin"])
def test_hand_constructed_artifact_cannot_bypass_observation_path_validation(tmp_path, filename):
    with CompilerRunner(CompileConfig(compiler=str(tmp_path / "missing"))) as runner:
        artifact = CompiledArtifact(runner.root / "program", "sourcehash", False, filename)
        result = runner.execute(artifact)
        assert result.status == "protocol_error" and result.return_value is None
