"""CPU-only synthetic jobs. Run this module inside the local bounded launcher."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

LAUNCHER = Path(__file__).with_name("run_container_job.py")
spec = importlib.util.spec_from_file_location("container_launcher", LAUNCHER)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def mount(root="/", point="/sys/fs/cgroup", options="ro"):
    return f"30 20 0:24 {root} {point} {options} - cgroup2 cgroup rw\n"


@pytest.mark.parametrize("membership,root,expected", [
    ("/job/one", "/", "/sys/fs/cgroup/job/one"),
    ("/container/job", "/container", "/sys/fs/cgroup/job"),
    ("/", "/", "/sys/fs/cgroup")])
def test_cgroup_mount_root_resolution(membership, root, expected):
    group, parent, options = guard.cgroup_directory("0::" + membership, mount(root))
    assert str(group) == expected and str(parent) == "/sys/fs/cgroup" and options == "ro"


@pytest.mark.parametrize("membership", ["/../host", "/another", "relative"])
def test_unresolvable_cgroup_is_not_assumed_to_be_mount_root(membership):
    with pytest.raises(RuntimeError):
        guard.cgroup_directory("0::" + membership, mount("/container"))


def test_cgroup_mount_escape_decode():
    assert guard.decode_mount_path(r"/space\040path") == "/space path"


@pytest.mark.parametrize("argv,seconds", [
    (["timeout", "--kill-after=30s", "2s", "python"], 2),
    (["/usr/bin/timeout", "-k", "2s", "-s", "TERM", "1.5m", "python"], 90),
    (["timeout", "--foreground", "--", "1h", "python"], 3600)])
def test_existing_evaluation_timeout_argv_is_a_real_internal_deadline(argv, seconds):
    assert guard.timeout_wall(argv) == seconds


@pytest.mark.parametrize("bad", ["0s", "-1", "nan", "inf", "1fortnight"])
def test_nonfinite_or_missing_deadline_refused(bad):
    with pytest.raises(ValueError):
        guard.duration(bad)


def test_process_ownership_uses_ancestry_and_excludes_sibling():
    table = {1: {"ppid": 0}, 2: {"ppid": 1}, 3: {"ppid": 2},
             4: {"ppid": 1}, 5: {"ppid": 4}, 6: {"ppid": 2}}
    assert guard.descendant_rows(table, 2) == [table[3], table[6]]


def test_pidfd_signal_failure_is_evidence_not_numeric_pid_fallback():
    s = guard.Supervisor(SimpleNamespace(), time.monotonic())
    s.known[(123, 456)] = 99
    with patch.object(guard, "pidfd_send_signal", side_effect=PermissionError(1, "denied")) as send:
        s.send(signal.SIGTERM)
    send.assert_called_once_with(99, signal.SIGTERM)
    assert s.errors == [{"pid": 123, "start_ticks": 456, "phase": "signal", "errno": 1}]


def test_process_reuse_during_pidfd_open_is_excluded():
    s = guard.Supervisor(SimpleNamespace(), time.monotonic())
    row = dict(pid=123, start_ticks=456, ppid=os.getpid(), state="S")
    with patch.object(guard, "process_table", return_value={123: row}), \
         patch.object(guard, "pidfd_open", return_value=99), \
         patch.object(guard, "proc_stat", return_value={**row, "start_ticks": 789}), \
         patch.object(os, "close") as close:
        assert s.discover() == []
    assert not s.known
    close.assert_called_once_with(99)


def test_cleanup_failure_is_explicit_and_still_signals_known_children():
    s = guard.Supervisor(SimpleNamespace(cleanup_seconds=.03, grace_seconds=.01, sample_seconds=.02), time.monotonic())
    s.known[(123, 456)] = 99
    with patch.object(s, "discover", side_effect=PermissionError), \
         patch.object(s, "reap"), patch.object(s, "send") as send:
        result = s.cleanup()
    assert not result["complete"] and result["remaining_unknown"] and send.called


def argv(receipt, code, *, memory=96, tasks=16, wall=3):
    return [sys.executable, "-I", "-B", str(LAUNCHER), "--memory-mib", str(memory),
            "--tasks", str(tasks), "--receipt", str(receipt), "--wall-seconds", str(wall),
            "--sample-seconds", ".02", "--grace-seconds", ".1", "--cleanup-seconds", "2",
            "--", sys.executable, "-I", "-B", "-c", code]


def launch(tmp_path, code, **kw):
    receipt = tmp_path / "receipt"
    proc = subprocess.run(argv(receipt, code, **kw), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=10)
    result = json.loads((receipt / "result.json").read_text())
    return proc, receipt, result


def test_actual_entry_exit_receipts_and_no_secret_arguments(tmp_path):
    proc, receipt, result = launch(tmp_path, "print('ARGUMENT_SECRET'); raise SystemExit(7)")
    assert proc.returncode == result["returncode"] == result["command_returncode"] == 7
    assert result["cleanup"]["complete"] and result["entry_verified"]
    assert result["cleanup_verified"] and result["payload_gate_released"]
    entry = json.loads((receipt / "entry.json").read_text())
    assert entry["actual_outer"]["visible_effective_memory_max"] > 0
    assert entry["actual_outer"]["visible_effective_pids_max"] > 0
    assert not entry["per_job_kernel_limits_installed"] and entry["subreaper_verified"]
    assert entry["root"]["start_ticks"] > 0
    assert entry["root"] == result["root"] and entry["source_sha256"] == result["source_sha256"]
    for p in receipt.iterdir():
        if p.is_file():
            assert "ARGUMENT_SECRET" not in p.read_text()


def test_wall_deadline_is_internal_not_only_external_timeout(tmp_path):
    proc, _, result = launch(tmp_path, "import time; time.sleep(60)", wall=.15)
    assert proc.returncode == 124 and result["first_stop_reason"] == "wall_deadline"
    assert result["cleanup"]["complete"] and result["elapsed_s"] < 3


def test_monitored_memory_threshold_is_not_reported_as_kernel_oom(tmp_path):
    proc, _, result = launch(tmp_path, "import time; data=bytearray(80*1024*1024); time.sleep(60)", memory=32)
    assert proc.returncode == 137 and result["first_stop_reason"] == "monitored_memory_threshold"
    assert result["observed_peaks"]["summed_rss_bytes"] > 32 * 1024 ** 2
    assert not result["per_job_kernel_limits_installed"] and result["cleanup"]["complete"]


def test_task_monitor_counts_threads_not_only_processes(tmp_path):
    code = "import threading,time; [threading.Thread(target=lambda:time.sleep(60)).start() for _ in range(6)]; time.sleep(60)"
    proc, _, result = launch(tmp_path, code, tasks=2)
    assert proc.returncode == 137 and result["first_stop_reason"] == "monitored_task_threshold"
    assert result["observed_peaks"]["threads"] > 2 and result["observed_peaks"]["process_count"] == 1
    assert result["cleanup"]["complete"]


def test_setsids_and_double_fork_orphans_are_killed_and_reaped(tmp_path):
    marker = tmp_path / "orphan"
    code = f'''import os,signal,time
p=os.fork()
if p==0:
 os.setsid()
 if os.fork()>0: os._exit(0)
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 open({str(marker)!r},'w').write(str(os.getpid()))
 time.sleep(60)
else:
 while not os.path.exists({str(marker)!r}): time.sleep(.01)
 os._exit(7)
'''
    proc, _, result = launch(tmp_path, code)
    assert proc.returncode == 7 and result["cleanup"]["complete"]
    orphan = int(marker.read_text())
    assert orphan in result["cleanup"]["reaped_pids"]
    assert not Path(f"/proc/{orphan}").exists()
    assert result["cleanup"]["signals"]["KILL"] > 0


def test_sigterm_cleans_only_owned_job_and_preserves_sibling(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    first = subprocess.Popen(argv(one, "import time; time.sleep(60)", wall=5), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    second = subprocess.Popen(argv(two, "import time; time.sleep(60)", wall=5), stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 3
        while not (one / "entry.json").exists() or not (two / "entry.json").exists():
            assert first.poll() is None and second.poll() is None
            assert time.monotonic() < deadline
            time.sleep(.02)
        other_root = json.loads((two / "entry.json").read_text())["root"]
        first.send_signal(signal.SIGTERM)
        assert first.wait(timeout=5) == 143
        assert second.poll() is None
        assert guard.proc_stat(other_root["pid"])["start_ticks"] == other_root["start_ticks"]
        result = json.loads((one / "result.json").read_text())
        assert result["cleanup"]["complete"] and result["first_stop_reason"] == "signal"
        second.send_signal(signal.SIGTERM)
        assert second.wait(timeout=5) == 143
    finally:
        for child in (first, second):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            child.stderr.close()


def test_missing_wall_preflight_never_executes_payload(tmp_path):
    receipt, marker = tmp_path / "receipt", tmp_path / "marker"
    command = [sys.executable, "-I", "-B", str(LAUNCHER), "--memory-mib", "96", "--tasks", "16",
               "--receipt", str(receipt), "--", sys.executable, "-c", f"open({str(marker)!r},'w').write('bad')"]
    env = dict(os.environ)
    env.pop("CONTAINER_JOB_WALL_SECONDS", None)
    proc = subprocess.run(command, env=env, capture_output=True, timeout=5)
    assert proc.returncode == 125 and not marker.exists()
    result = json.loads((receipt / "result.json").read_text())
    assert result["first_stop_reason"] == "preflight_failed" and not result["payload_forked"]


def test_existing_receipt_is_never_reused(tmp_path):
    receipt = tmp_path / "receipt"
    receipt.mkdir()
    marker = tmp_path / "marker"
    proc = subprocess.run(argv(receipt, f"open({str(marker)!r},'w').write('bad')"), capture_output=True, timeout=5)
    assert proc.returncode == 125 and not marker.exists() and not list(receipt.iterdir())


def test_probe_only_reports_actual_scope_without_payload(tmp_path):
    receipt = tmp_path / "receipt"
    proc = subprocess.run([sys.executable, "-I", "-B", str(LAUNCHER), "--probe", "--receipt", str(receipt)],
                          capture_output=True, timeout=5)
    assert proc.returncode == 0
    result = json.loads((receipt / "result.json").read_text())
    assert result["first_stop_reason"] == "probe_only" and not result["payload_forked"]
    assert result["cleanup_verified"] is False
    assert not (receipt / "entry.json").exists()


def test_nested_jobs_have_distinct_accounting_and_parent_cleanup_ownership(tmp_path):
    child_receipt = tmp_path / "child"
    child_argv = argv(child_receipt, "import time; data=bytearray(80*1024*1024); time.sleep(.3)", memory=128)
    code = "import subprocess; raise SystemExit(subprocess.run(" + repr(child_argv) + ").returncode)"
    proc, receipt, result = launch(tmp_path, code, memory=48)
    assert proc.returncode == 0, proc.stderr
    child = json.loads((child_receipt / "result.json").read_text())
    assert child["returncode"] == 0 and child["cleanup"]["complete"]
    samples = [json.loads(line) for line in (receipt / "resources.jsonl").read_text().splitlines()]
    assert any(row["excluded_registered_job_roots"] for row in samples)
    assert any(row["owned_tree_process_count"] > row["process_count"] for row in samples)
    assert result["observed_peaks"]["summed_rss_bytes"] < 48 * 1024 ** 2
    assert child["observed_peaks"]["summed_rss_bytes"] > 80 * 1024 ** 2
    assert not list((receipt / "owned-job-registry").glob("*.json"))


def test_unbounded_outer_limits_refuse_before_payload(tmp_path):
    # Isolated interpreter invokes the same CLI with only the read-only probe stubbed.
    receipt, marker = tmp_path / "receipt", tmp_path / "marker"
    command = argv(receipt, f"open({str(marker)!r},'w').write('bad')")
    boot = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('guard',sys.argv[1]); "
            "g=importlib.util.module_from_spec(s); s.loader.exec_module(g); "
            "g.probe=lambda:{'visible_effective_memory_max':None,'visible_effective_pids_max':None}; "
            "sys.argv=sys.argv[1:]; raise SystemExit(g.main())")
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", boot, str(LAUNCHER), *command[4:]], capture_output=True, timeout=5)
    assert proc.returncode == 125 and not marker.exists()
    result = json.loads((receipt / "result.json").read_text())
    assert not result["payload_forked"] and not result["entry_verified"]
    assert result["cleanup_verified"] is False


def test_inherited_ignored_sigchld_does_not_lose_root_exit(tmp_path):
    command = argv(tmp_path / "receipt", "raise SystemExit(9)")
    boot = "import os,signal,sys; signal.signal(signal.SIGCHLD,signal.SIG_IGN); os.execv(sys.argv[1],sys.argv[1:])"
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", boot, *command], capture_output=True, timeout=5)
    assert proc.returncode == 9
    result = json.loads((tmp_path / "receipt/result.json").read_text())
    assert result["command_returncode"] == 9 and result["cleanup"]["complete"]


def test_missing_exec_is_a_recorded_command_failure_with_complete_cleanup(tmp_path):
    command = argv(tmp_path / "receipt", "pass")
    command = command[:command.index("--")+1] + ["/nonexistent/container-job-test-executable"]
    proc = subprocess.run(command, capture_output=True, timeout=5)
    assert proc.returncode == 125
    result = json.loads((tmp_path / "receipt/result.json").read_text())
    assert result["command_returncode"] == 125 and result["cleanup"]["complete"]
    assert result["first_stop_reason"] == "command_exit" and result["payload_gate_released"]


def boot_run(tmp_path, code, setup):
    command = argv(tmp_path / "receipt", code)
    boot = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('guard',sys.argv[1]); "
            "g=importlib.util.module_from_spec(s); s.loader.exec_module(g); " + setup + "; "
            "sys.argv=sys.argv[1:]; raise SystemExit(g.main())")
    return subprocess.run([sys.executable, "-I", "-B", "-c", boot, str(LAUNCHER), *command[4:]], capture_output=True, timeout=5)


def test_cleanup_failure_retains_command_cause_and_overrides_exit(tmp_path):
    proc = boot_run(tmp_path, "raise SystemExit(7)",
                    "g.Supervisor.cleanup=lambda self,**kw:{'complete':False,'remaining_unknown':True}")
    assert proc.returncode == 125
    result = json.loads((tmp_path / "receipt/result.json").read_text())
    assert result["command_returncode"] == 7 and result["first_stop_reason"] == "command_exit"
    assert not result["cleanup"]["complete"]
    assert result["cleanup_verified"] is False


def test_entry_receipt_failure_does_not_release_exec_gate(tmp_path):
    marker = tmp_path / "marker"
    setup = ("original=g.write_json; "
             "g.write_json=lambda p,v:(_ for _ in ()).throw(OSError(28,'full')) if p.name=='entry.json' else original(p,v)")
    proc = boot_run(tmp_path, f"open({str(marker)!r},'w').write('bad')", setup)
    assert proc.returncode == 125 and not marker.exists()
    result = json.loads((tmp_path / "receipt/result.json").read_text())
    assert result["payload_forked"] and not result["payload_gate_released"]
    assert not result["entry_verified"] and result["cleanup"]["complete"]


def test_parent_sigterm_contains_nested_detached_payload(tmp_path):
    child_receipt, marker = tmp_path / "child", tmp_path / "child-pid"
    child_argv = argv(child_receipt,
                      f"import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); open({str(marker)!r},'w').write(str(os.getpid())); time.sleep(60)", wall=5)
    code = "import subprocess; raise SystemExit(subprocess.run(" + repr(child_argv) + ").returncode)"
    parent = subprocess.Popen(argv(tmp_path / "receipt", code, memory=48, wall=5),
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 3
        while not marker.exists():
            assert parent.poll() is None and time.monotonic() < deadline
            time.sleep(.02)
        child_pid = int(marker.read_text())
        parent.terminate()
        assert parent.wait(timeout=5) == 143
        result = json.loads((tmp_path / "receipt/result.json").read_text())
        assert result["cleanup"]["complete"] and not Path(f"/proc/{child_pid}").exists()
    finally:
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=5)
        parent.stderr.close()


def test_command_signal_receipt_matches_actual_launcher_exit(tmp_path):
    proc, _, result = launch(tmp_path, "import os,signal; os.kill(os.getpid(),signal.SIGKILL)")
    assert proc.returncode == result["returncode"] == 137
    assert result["command_returncode"] == -signal.SIGKILL and result["cleanup_verified"]


def test_missing_python_pidfd_bindings_use_real_libc(monkeypatch):
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.delattr(signal, "pidfd_send_signal", raising=False)
    verified = guard.verify_pidfds()
    assert verified["self_signal_zero_verified"]
    assert set(verified["bindings"].values()) <= {"libc", "linux_syscall_x86_64", "linux_syscall_aarch64"}
    fd = guard.pidfd_open(os.getpid())
    assert not os.get_inheritable(fd)
    os.close(fd)
    with pytest.raises(OSError) as caught:
        guard.pidfd_send_signal(fd, 0)
    assert caught.value.errno == 9


def test_missing_python_and_libc_symbols_use_verified_kernel_syscalls(monkeypatch):
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.delattr(signal, "pidfd_send_signal", raising=False)
    monkeypatch.setattr(guard.ctypes, "CDLL", lambda *a, **kw: SimpleNamespace(syscall=libc.syscall))
    verified = guard.verify_pidfds()
    assert verified["self_signal_zero_verified"]
    assert all(route.startswith("linux_syscall_") for route in verified["bindings"].values())


def test_unsupported_binding_architecture_refuses_without_pid_signal(monkeypatch):
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.delattr(signal, "pidfd_send_signal", raising=False)
    monkeypatch.setattr(guard.ctypes, "CDLL", lambda *a, **kw: SimpleNamespace())
    monkeypatch.setattr(guard.platform, "machine", lambda: "not-qualified")
    with pytest.raises(RuntimeError):
        guard.verify_pidfds()


def test_real_cleanup_without_either_python_pidfd_api(tmp_path):
    proc = boot_run(tmp_path, "import time; time.sleep(60)",
                    "g.os.pidfd_open=None; g.signal.pidfd_send_signal=None")
    assert proc.returncode == 124, proc.stderr
    result = json.loads((tmp_path / "receipt/result.json").read_text())
    entry = json.loads((tmp_path / "receipt/entry.json").read_text())
    assert result["cleanup_verified"] and result["first_stop_reason"] == "wall_deadline"
    assert set(entry["pidfd_bindings"].values()) <= {"libc", "linux_syscall_x86_64", "linux_syscall_aarch64"}


def test_pidfd_cache_and_reaped_history_stay_bounded_under_churn(tmp_path):
    # A separate process owns/reaps its children. Constrain its FD table to
    # reproduce the previous leak rather than relying on the workstation limit.
    boot = """import importlib.util,sys,resource,os,time
s=importlib.util.spec_from_file_location('g',sys.argv[1]); g=importlib.util.module_from_spec(s); s.loader.exec_module(g)
resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
supervisor=g.Supervisor(None,time.monotonic())
maximum=0
for index in range(180):
 p=os.fork()
 if p==0:
  time.sleep(.002); os._exit(0)
 supervisor.discover()
 while True:
  supervisor.reap()
  if supervisor.no_children: break
  time.sleep(.001)
 maximum=max(maximum,len(supervisor.known))
assert maximum == 0 and supervisor.reaped_total == 180
assert len(supervisor.reaped) == 64
supervisor.close()
"""
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", boot, str(LAUNCHER)], capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr


def test_sigterm_does_not_interrupt_payload_finally_twice(tmp_path):
    marker = tmp_path / "cleanup-finished"
    code = f"""import signal,time
signal.signal(signal.SIGTERM,lambda *a:(_ for _ in ()).throw(SystemExit(0)))
try: time.sleep(60)
finally:
 time.sleep(.25)
 open({str(marker)!r},'w').write('done')
"""
    command = argv(tmp_path / "receipt", code, wall=.2)
    command[command.index("--grace-seconds")+1] = "1"
    proc = subprocess.run(command, capture_output=True, timeout=5)
    result = json.loads((tmp_path / "receipt/result.json").read_text())
    assert proc.returncode == 124 and marker.read_text() == "done"
    assert result["cleanup_verified"] and result["cleanup"]["signals"]["TERM"] == 1


def test_leading_timeout_preserves_its_kill_after_grace(tmp_path):
    marker = tmp_path / "cleanup-finished"
    code = f"""import signal,time
signal.signal(signal.SIGTERM,lambda *a:(_ for _ in ()).throw(SystemExit(0)))
try: time.sleep(60)
finally:
 time.sleep(.4)
 open({str(marker)!r},'w').write('done')
"""
    receipt = tmp_path / "receipt"
    command = [sys.executable, "-I", "-B", str(LAUNCHER), "--memory-mib", "96", "--tasks", "16",
               "--receipt", str(receipt), "--sample-seconds", ".02", "--",
               "timeout", "--kill-after=2s", "0.2s", sys.executable, "-I", "-B", "-c", code]
    proc = subprocess.run(command, capture_output=True, timeout=8)
    result = json.loads((receipt / "result.json").read_text())
    entry = json.loads((receipt / "entry.json").read_text())
    assert proc.returncode == 124 and marker.read_text() == "done", proc.stderr
    assert result["cleanup_verified"] and result["first_stop_reason"] == "command_exit"
    assert result["cleanup"]["signals"]["TERM"] == 0
    assert entry["deadline_source"] == "leading_timeout_backstop" and entry["wall_seconds"] > 2.2


def test_resource_log_budget_does_not_stop_monitoring(tmp_path):
    receipt = tmp_path / "receipt"
    command = argv(receipt, "import time; time.sleep(.3)")
    command[command.index("--"):command.index("--")] = ["--resource-log-bytes", "1024"]
    proc = subprocess.run(command, capture_output=True, timeout=5)
    result = json.loads((receipt / "result.json").read_text())
    assert proc.returncode == 0 and result["cleanup_verified"]
    assert result["resource_log_truncated"] and result["sample_count"] > result["logged_samples"]
    assert (receipt / "resources.jsonl").stat().st_size == result["logged_bytes"] <= 1024


def test_malformed_json_registry_is_recorded_and_cleaned(tmp_path):
    code = "import os,pathlib,time; pathlib.Path(os.environ['CONTAINER_JOB_REGISTRY'],'bad.json').write_text('[]'); time.sleep(60)"
    proc, receipt, result = launch(tmp_path, code)
    assert proc.returncode == 125 and result["first_stop_reason"] == "supervisor_error"
    assert result["cleanup_verified"]
    assert json.loads((receipt / "error.json").read_text())["error_class"] == "RuntimeError"


def test_reaped_root_exit_code_is_not_overwritten_by_reused_numeric_pid():
    supervisor = guard.Supervisor(None, time.monotonic())
    supervisor.root, supervisor.root_status = (123, 456), 7
    with patch.object(os, "waitpid", side_effect=[(123, 9 << 8), ChildProcessError()]):
        supervisor.reap()
    assert supervisor.root_status == 7


def test_nofile_capacity_is_qualified_before_exec(tmp_path):
    proc = boot_run(tmp_path, "pass", "g.resource.setrlimit(g.resource.RLIMIT_NOFILE,(64,64))")
    result = json.loads((tmp_path / "receipt/result.json").read_text())
    assert proc.returncode == 125 and not result["payload_forked"]
    assert result["first_stop_reason"] == "preflight_failed"


def test_probe_qualifies_pidfds_when_python_bindings_are_missing(tmp_path):
    receipt = tmp_path / "receipt"
    boot = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('g',sys.argv[1]); "
            "g=importlib.util.module_from_spec(s); s.loader.exec_module(g); "
            "g.os.pidfd_open=None; g.signal.pidfd_send_signal=None; sys.argv=sys.argv[1:]; raise SystemExit(g.main())")
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", boot, str(LAUNCHER),
                           "--probe", "--receipt", str(receipt)], capture_output=True, timeout=5)
    observed = json.loads((receipt / "probe.json").read_text())["observed"]
    assert proc.returncode == 0 and observed["pidfd"]["self_signal_zero_verified"]
    assert observed["rlimit_nofile"][1] > 0


def test_native_exec_restores_signal_defaults_and_blocked_mask(tmp_path):
    receipt = tmp_path / "receipt"
    command = argv(receipt, "pass")
    command = command[:command.index("--")+1] + ["/bin/cat", "/proc/self/status"]
    # Python ordinarily ignores SIGPIPE and inherits blocked masks across exec.
    boot = "import os,signal,sys; signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGUSR1}); os.execv(sys.argv[1],sys.argv[1:])"
    proc = subprocess.run([sys.executable, "-I", "-B", "-c", boot, *command], capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, proc.stderr
    status = dict(line.split(':',1) for line in proc.stdout.splitlines() if ':' in line)
    assert int(status["SigBlk"].strip(),16) == 0
    assert not int(status["SigIgn"].strip(),16) & (1 << (signal.SIGPIPE-1))


def test_pidfd_is_closed_when_proc_stat_has_unexpected_error():
    supervisor = guard.Supervisor(None, time.monotonic())
    row = dict(pid=123, start_ticks=456, ppid=os.getpid(), state="S")
    with patch.object(guard, "process_table", return_value={123:row}), patch.object(guard,"pidfd_open",return_value=99), patch.object(guard,"proc_stat",side_effect=ValueError), patch.object(os,"close") as close:
        with pytest.raises(ValueError):supervisor.discover()
    close.assert_called_once_with(99)
    assert not supervisor.known


def test_payload_keeps_original_soft_nofile_limit(tmp_path):
    marker = tmp_path / "nofile"
    proc = boot_run(tmp_path, f"import resource; open({str(marker)!r},'w').write(str(resource.getrlimit(resource.RLIMIT_NOFILE)[0]))", "g.resource.setrlimit(g.resource.RLIMIT_NOFILE,(64,g.resource.getrlimit(g.resource.RLIMIT_NOFILE)[1]))")
    entry = json.loads((tmp_path / "receipt/entry.json").read_text())
    assert proc.returncode == 0 and marker.read_text() == "64"
    assert entry["guardian_rlimit_nofile"][0] >= entry["actual_outer"]["visible_effective_pids_max"]+64
    assert entry["payload_rlimit_nofile"][0] == 64


def test_guardian_death_preserves_timeout_forwarding_and_child_deadline(tmp_path):
    receipt, marker = tmp_path / "receipt", tmp_path / "child"
    code = f"import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); open({str(marker)!r},'w').write(str(os.getpid())); time.sleep(60)"
    command = [sys.executable, "-I", "-B", str(LAUNCHER), "--memory-mib", "96", "--tasks", "16", "--receipt",str(receipt),"--sample-seconds",".02","--","timeout","--kill-after=0.3s","0.5s",sys.executable,"-I","-B","-c",code]
    # A separate subreaper contains/reaps survivors of the intentionally killed
    # guardian, without modifying pytest's own child ownership.
    boot = f"""import importlib.util,subprocess,time,os,sys,signal
from pathlib import Path
spec=importlib.util.spec_from_file_location('g',{str(LAUNCHER)!r});g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
g.subreaper()
owner=subprocess.Popen({command!r},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
try:
 deadline=time.monotonic()+3
 while not Path({str(marker)!r}).exists():
  assert owner.poll() is None and time.monotonic()<deadline
  time.sleep(.01)
 owner.kill();assert owner.wait(timeout=3)==-signal.SIGKILL
 deadline=time.monotonic()+2
 while True:
  try:pid,status=os.waitpid(-1,os.WNOHANG)
  except ChildProcessError:break
  assert time.monotonic()<deadline,'timeout lost descendant deadline'
  time.sleep(.02)
 assert not Path({str(receipt/'result.json')!r}).exists()
finally:
 if owner.poll() is None:owner.kill();owner.wait(timeout=3)
 supervisor=g.Supervisor(type('A',(),dict(cleanup_seconds=2,grace_seconds=.1,sample_seconds=.02))(),time.monotonic())
 supervisor.cleanup(immediate=True);supervisor.close();owner.stderr.close()
"""
    proc = subprocess.run([sys.executable,'-I','-B','-c',boot],capture_output=True,timeout=8)
    assert proc.returncode == 0, proc.stderr


def test_timeout_backstop_anchors_after_slow_entry_persistence(tmp_path):
    receipt = tmp_path / 'receipt'
    command = [sys.executable,'-I','-B',str(LAUNCHER),'--memory-mib','96','--tasks','16','--receipt',str(receipt),'--sample-seconds','.02','--','timeout','--kill-after=0.2s','0.2s',sys.executable,'-I','-B','-c','import time; time.sleep(.05)']
    boot = "import importlib.util,sys,time; s=importlib.util.spec_from_file_location('g',sys.argv[1]); g=importlib.util.module_from_spec(s); s.loader.exec_module(g); original=g.write_json; g.write_json=lambda p,v:(time.sleep(.3) if p.name=='entry.json' else None) or original(p,v); sys.argv=sys.argv[1:]; raise SystemExit(g.main())"
    proc = subprocess.run([sys.executable,'-I','-B','-c',boot,str(LAUNCHER),*command[4:]],capture_output=True,timeout=5)
    result=json.loads((receipt/'result.json').read_text());entry=json.loads((receipt/'entry.json').read_text())
    assert proc.returncode==0 and result['cleanup_verified']
    assert entry['deadline_anchor']=='gate_release' and entry['deadline_monotonic'] is None
    assert result['effective_deadline_monotonic']>entry['preparation_deadline_monotonic']+.25
