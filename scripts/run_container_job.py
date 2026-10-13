#!/usr/bin/env python3
"""Linux container job supervisor. Per-job RSS/tasks are monitored, not cgroups.

Requires visible finite outer cgroup-v2 memory/pids limits, Linux pidfds and a
standalone single-threaded supervisor. See docs/agents/container-jobs.md.
"""
import argparse
import ctypes
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
import uuid
import hashlib

SCHEMA = "container-job-v1"
MIB = 1024 ** 2
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def write_json(path, value):
    """Atomic durable file in a newly owned receipt directory; never overwrite."""
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def decode_mount_path(value):
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), value)


def cgroup_directory(cgroup_text, mount_text):
    """Resolve the v2 group relative to its actual mount root/namespace."""
    memberships = [line[3:] for line in cgroup_text.splitlines() if line.startswith("0::")]
    if len(memberships) != 1:
        raise RuntimeError("A readable cgroup v2 membership is required")
    membership = memberships[0]
    if not membership.startswith("/") or ".." in Path(membership).parts:
        raise RuntimeError("Unresolvable cgroup membership")
    choices = []
    for line in mount_text.splitlines():
        left, sep, right = line.partition(" - ")
        fields = left.split()
        if sep and right.split()[0] == "cgroup2" and len(fields) >= 6:
            root, mount = map(decode_mount_path, fields[3:5])
            if membership == root or membership.startswith(root.rstrip("/") + "/"):
                suffix = membership[len(root):].lstrip("/")
                choices.append((len(root), Path(mount) / suffix, Path(mount), fields[5]))
    if not choices:
        raise RuntimeError("Membership is outside visible cgroup v2 mounts")
    _, group, mount, options = max(choices, key=lambda row: row[0])
    return group, mount, options


def read_files(path, names):
    values = {}
    for name in names:
        try:
            values[name] = (path / name).read_text().strip()
        except OSError:
            values[name] = None
    return values


def probe():
    group, mount, options = cgroup_directory(Path("/proc/self/cgroup").read_text(),
                                            Path("/proc/self/mountinfo").read_text())
    levels = []
    cursor = group
    while True:
        levels.append(dict(path=str(cursor), limits=read_files(cursor, (
            "memory.max", "memory.swap.max", "pids.max", "cpu.max", "cpuset.cpus.effective"))))
        if cursor == mount:
            break
        cursor = cursor.parent
    def finite(name):
        limits = []
        for row in levels:
            value = row["limits"][name]
            if value is not None and value != "max":
                if not value.isdecimal() or int(value) <= 0:
                    raise RuntimeError("Malformed visible cgroup limit: " + name)
                limits.append(int(value))
        return min(limits) if limits else None
    shm = os.statvfs("/dev/shm")
    return dict(cgroup_version=2, cgroup=str(group), mount=str(mount), mount_options=options,
                visible_hierarchy=levels, visible_effective_memory_max=finite("memory.max"),
                visible_effective_pids_max=finite("pids.max"),
                effective_affinity=sorted(os.sched_getaffinity(0)),
                cgroup_directory_writable=os.access(group, os.W_OK),
                shm_total_bytes=shm.f_blocks * shm.f_frsize,
                shm_available_bytes=shm.f_bavail * shm.f_frsize,
                namespace_scope="Visible hierarchy only; hidden provider ancestors not inferred")


def duration(value):
    found = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([smhd]?)", value)
    if not found:
        raise ValueError("Unsupported timeout duration")
    result = float(found[1]) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[found[2]]
    if not math.isfinite(result) or result <= 0:
        raise ValueError("A finite positive wall deadline is required")
    return result


def timeout_wall(command):
    if not command or Path(command[0]).name != "timeout":
        return None
    index = 1
    while index < len(command) and command[index].startswith("-"):
        value = command[index]
        if value == "--":
            index += 1
            break
        if value in ("--signal", "--kill-after", "-s", "-k"):
            index += 2
        elif value.startswith(("--signal=", "--kill-after=")) or value in ("--foreground", "--preserve-status", "-v", "--verbose"):
            index += 1
        else:
            raise ValueError("Unknown leading timeout option; pass explicit --wall-seconds")
    if index >= len(command) - 1:
        raise ValueError("Leading timeout must have a duration and command")
    return duration(command[index])


def validate(args):
    if args.memory_mib <= 0 or args.tasks <= 0:
        raise ValueError("memory-mib and tasks must be positive")
    for name in ("sample_seconds", "grace_seconds", "cleanup_seconds"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(name + " must be finite and positive")
    if not .02 <= args.sample_seconds <= 2 or not args.grace_seconds < args.cleanup_seconds <= 60:
        raise ValueError("Sample must be .02-2s; cleanup must exceed grace and be <=60s")
    if args.wall_seconds is None:
        configured = os.environ.get("CONTAINER_JOB_WALL_SECONDS")
        args.wall_seconds = duration(configured) if configured is not None else timeout_wall(args.command)
    if args.wall_seconds is None or not math.isfinite(args.wall_seconds) or args.wall_seconds <= 0:
        raise ValueError("Pass --wall-seconds, CONTAINER_JOB_WALL_SECONDS or leading timeout duration")


def proc_stat(pid):
    """Identity and counters from one stat read; no arguments or environment."""
    raw = Path(f"/proc/{pid}/stat").read_text()
    tail = raw[raw.rfind(")") + 2:].split()
    return dict(pid=pid, start_ticks=int(tail[19]), ppid=int(tail[1]), state=tail[0],
                rss_bytes=max(0, int(tail[21])) * os.sysconf("SC_PAGE_SIZE"),
                threads=int(tail[17]), cpu_ticks=int(tail[11]) + int(tail[12]))


def process_table():
    table = {}
    for path in Path("/proc").iterdir():
        if path.name.isdecimal():
            try:
                row = proc_stat(int(path.name))
                table[row["pid"]] = row
            except ProcessLookupError:
                pass
            except FileNotFoundError:
                pass
            # Permission/parse errors are not silently converted into complete coverage.
    return table


def descendant_rows(table, parent):
    owned = {parent}
    while True:
        more = {pid for pid, row in table.items() if row["ppid"] in owned}
        if more <= owned:
            break
        owned |= more
    owned.discard(parent)
    return [table[pid] for pid in sorted(owned) if pid in table]


def subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "Cannot enable child subreaper")
    actual = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(actual), 0, 0, 0) != 0 or actual.value != 1:
        raise RuntimeError("Subreaper enablement was not verified")


class Supervisor:
    def __init__(self, args, started):
        self.args, self.started = args, started
        self.known = {}  # (pid,birth) -> pidfd; never kill a bare numeric PID
        self.root = None
        self.root_status = None
        self.reaped = []
        self.no_children = False
        self.errors = []
        self.signal_counts = {"TERM": 0, "KILL": 0}
        self.registry = None
        self.source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.outer_group = None

    def accounting_rows(self, rows):
        """Partition nested instances of this exact trusted launcher, not cleanup.

        Children inherit the registry automatically. It is not a malicious-code
        trust boundary: all same-user payloads must be cooperative.
        """
        if self.registry is None:
            return rows, []
        table = {row["pid"]: row for row in rows}
        excluded, roots = set(), []
        for path in self.registry.glob("*.json"):
            try:
                mode = path.lstat().st_mode
                if not stat.S_ISREG(mode):
                    raise RuntimeError("Job registry record is not regular")
                record = json.loads(path.read_text())
            except FileNotFoundError:
                continue  # A child completed and removed its own registration.
            if record.get("schema") != SCHEMA or record.get("source_sha256") != self.source_sha256:
                raise RuntimeError("Nested job registry source mismatch")
            try:
                guardian, root = record["supervisor"], record["root"]
                for identity in (guardian, root):
                    if (type(identity["pid"]) is not int or identity["pid"] <= 0
                            or type(identity["start_ticks"]) is not int or identity["start_ticks"] <= 0):
                        raise ValueError("Invalid process identity")
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError("Malformed nested job registry identity") from error
            current, payload = table.get(guardian["pid"]), table.get(root["pid"])
            if current is None or current["start_ticks"] != guardian["start_ticks"] or current["state"] in ("Z", "X"):
                continue
            if payload is None or payload["start_ticks"] != root["start_ticks"] or payload["ppid"] != guardian["pid"]:
                continue
            excluded.add(payload["pid"])
            excluded.update(r["pid"] for r in descendant_rows(table, payload["pid"]))
            roots.append(root)
        return [row for row in rows if row["pid"] not in excluded], roots

    def discover(self):
        table = process_table()
        rows = descendant_rows(table, os.getpid())
        for row in rows:
            identity = row["pid"], row["start_ticks"]
            if identity not in self.known:
                fd = None
                try:
                    fd = os.pidfd_open(row["pid"])
                    fresh = proc_stat(row["pid"])
                except (ProcessLookupError, FileNotFoundError):
                    if fd is not None:
                        os.close(fd)
                    continue
                if (fresh["pid"], fresh["start_ticks"], fresh["ppid"]) != (row["pid"], row["start_ticks"], row["ppid"]):
                    os.close(fd)
                    continue
                self.known[identity] = fd
        # Include already identified children during a reparenting snapshot race.
        return [row for row in table.values() if (row["pid"], row["start_ticks"]) in self.known]

    def reap(self):
        self.no_children = False
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                self.no_children = True
                return
            if pid == 0:
                return
            self.reaped.append(pid)
            if self.root and pid == self.root[0]:
                self.root_status = os.waitstatus_to_exitcode(status)

    def send(self, sig):
        for identity, fd in self.known.items():
            try:
                signal.pidfd_send_signal(fd, sig)
                self.signal_counts["TERM" if sig == signal.SIGTERM else "KILL"] += 1
            except ProcessLookupError:
                pass
            except OSError as error:
                self.errors.append(dict(pid=identity[0], start_ticks=identity[1], phase="signal", errno=error.errno))

    def sample(self, rows):
        accounted, roots = self.accounting_rows(rows)
        live = [row for row in accounted if row["state"] not in ("Z", "X")]
        return dict(elapsed_s=round(time.monotonic() - self.started, 3),
                    process_count=len(live), threads=sum(row["threads"] for row in live),
                    summed_rss_bytes=sum(row["rss_bytes"] for row in live),
                    owned_tree_process_count=sum(row["state"] not in ("Z", "X") for row in rows),
                    excluded_registered_job_roots=roots,
                    live_cpu_ticks=sum(row["cpu_ticks"] for row in live),
                    outer_counters=read_files(self.outer_group, (
                        "memory.current", "memory.peak", "memory.events", "memory.swap.current",
                        "pids.current", "pids.events", "cpu.stat")) if self.outer_group else {},
                    identities=[dict(pid=r["pid"], start_ticks=r["start_ticks"]) for r in live])

    def cleanup(self):
        start = time.monotonic()
        remaining = []
        while True:
            try:
                rows = self.discover()
                discovery_ok = True
            except (OSError, ValueError, RuntimeError) as error:
                rows = []
                discovery_ok = False
                if not any(e.get("phase") == "cleanup_discovery" for e in self.errors):
                    self.errors.append(dict(phase="cleanup_discovery", error_class=type(error).__name__))
            self.reap()
            remaining = [r for r in rows if r["state"] not in ("Z", "X")]
            if not remaining and self.no_children:
                return dict(complete=True, elapsed_s=round(time.monotonic() - start, 3),
                            remaining=[], reaped_pids=self.reaped, signals=self.signal_counts,
                            errors=self.errors, verified_no_waitable_children=True)
            elapsed = time.monotonic() - start
            if elapsed >= self.args.cleanup_seconds:
                return dict(complete=False, elapsed_s=round(elapsed, 3), remaining=remaining,
                            reaped_pids=self.reaped, signals=self.signal_counts,
                            errors=self.errors, remaining_unknown=not discovery_ok,
                            verified_no_waitable_children=False)
            self.send(signal.SIGTERM if elapsed < self.args.grace_seconds else signal.SIGKILL)
            time.sleep(min(self.args.sample_seconds, .1))

    def close(self):
        for fd in self.known.values():
            os.close(fd)


def run(args):
    started = time.monotonic()
    args.receipt = args.receipt.resolve()
    args.receipt.mkdir(parents=True, mode=0o700, exist_ok=False)
    interrupted = []
    stop_reason, root_started, gate = None, False, None
    gate_released = False
    registration = None
    supervisor = Supervisor(args, started)
    previous = {}
    entry_verified = False
    cleanup = dict(complete=True, payload_started=False, remaining=[])
    samples, peaks = 0, dict(summed_rss_bytes=0, threads=0, process_count=0)
    launch = dict(schema=SCHEMA, mode="monitored_process_tree", started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                  supervisor=proc_stat(os.getpid()), executable=Path(args.command[0]).name if args.command else None,
                  argument_count=max(0, len(args.command) - 1), automatic_retries=0,
                  source_sha256=supervisor.source_sha256)
    write_json(args.receipt / "launch.json", launch)
    def stop(sig, frame):
        interrupted.append(sig)
    try:
        outer = probe()
        supervisor.outer_group = Path(outer["cgroup"]) if "cgroup" in outer else None
        if args.probe:
            write_json(args.receipt / "probe.json", dict(schema=SCHEMA, observed=outer))
            stop_reason = "probe_only"
            returncode = 0
        else:
            validate(args)
            if not args.command:
                raise ValueError("Specify a foreground command after --")
            if outer["visible_effective_memory_max"] is None or outer["visible_effective_pids_max"] is None:
                raise RuntimeError("Finite visible outer memory.max and pids.max are required")
            if args.memory_mib * MIB > outer["visible_effective_memory_max"] or args.tasks > outer["visible_effective_pids_max"]:
                raise ValueError("Requested monitored thresholds exceed observed outer hard limits")
            if len(list(Path("/proc/self/task").iterdir())) != 1 or descendant_rows(process_table(), os.getpid()):
                raise RuntimeError("Supervisor must start single-threaded without existing children")
            if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
                raise RuntimeError("Linux pidfd APIs are required")
            fd = os.pidfd_open(os.getpid())
            os.close(fd)
            subreaper()
            previous[signal.SIGCHLD] = signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            for sig in STOP_SIGNALS:
                previous[sig] = signal.signal(sig, stop)
            allowed = set(os.sched_getaffinity(0))
            cpus = allowed if args.cpus is None else {int(x) for x in args.cpus.split(",")}
            if not cpus or not cpus <= allowed:
                raise ValueError("Requested CPUs must be a nonempty subset of inherited affinity")
            os.sched_setaffinity(0, cpus)
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "RAYON_NUM_THREADS"):
                os.environ[name] = "2"
            registry_env = os.environ.get("CONTAINER_JOB_REGISTRY")
            registry = Path(registry_env) if registry_env else args.receipt / "owned-job-registry"
            if registry_env:
                status = registry.lstat()
                if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid() or stat.S_IMODE(status.st_mode) != 0o700:
                    raise RuntimeError("Inherited job registry must be an owned private directory")
            else:
                registry.mkdir(mode=0o700)
            supervisor.registry = registry.resolve()
            os.environ["CONTAINER_JOB_REGISTRY"] = str(supervisor.registry)
            read_gate, gate = os.pipe2(os.O_CLOEXEC)
            pid = os.fork()
            if pid == 0:
                os.close(gate)
                for sig in STOP_SIGNALS:
                    signal.signal(sig, signal.SIG_DFL)
                try:
                    os.setsid()
                    token = os.read(read_gate, 1)
                    os.close(read_gate)
                    if token != b"1":
                        os._exit(125)
                    os.execvpe(args.command[0], args.command, os.environ)
                except BaseException:
                    os.write(2, b"Container payload exec failed\n")
                    os._exit(125)
            root_started = True
            os.close(read_gate)
            row = proc_stat(pid)
            supervisor.root = pid, row["start_ticks"]
            supervisor.known[supervisor.root] = os.pidfd_open(pid)
            write_json(args.receipt / "entry.json", dict(schema=SCHEMA, mode="monitored_process_tree",
                       root=dict(pid=pid, start_ticks=row["start_ticks"]), supervisor=launch["supervisor"],
                       source_sha256=supervisor.source_sha256,
                       actual_outer=outer, cpus=sorted(os.sched_getaffinity(0)), subreaper_verified=True,
                       thresholds=dict(summed_rss_bytes=args.memory_mib * MIB, linux_threads=args.tasks),
                       per_job_kernel_limits_installed=False, wall_seconds=args.wall_seconds,
                       accounting="Own processes plus nested supervisor overhead; registered child payloads separately monitored",
                       job_registry=str(supervisor.registry),
                       deadline_monotonic=started + args.wall_seconds, sample_seconds=args.sample_seconds,
                       cpu_quota_installed=False, gpu_memory_accounted=False,
                       limitations="Sampling can overshoot; RSS counts shared pages more than once; no GPU, page-cache or hostile-code containment"))
            entry_verified = True
            registration = supervisor.registry / (str(os.getpid()) + "-" + str(launch["supervisor"]["start_ticks"]) + "-" + uuid.uuid4().hex + ".json")
            write_json(registration, dict(schema=SCHEMA, supervisor=launch["supervisor"],
                       root=dict(pid=pid, start_ticks=row["start_ticks"]), source_sha256=supervisor.source_sha256))
            if not interrupted and time.monotonic() < started + args.wall_seconds:
                os.write(gate, b"1")
                gate_released = True
            os.close(gate)
            gate = None
            with (args.receipt / "resources.jsonl").open("x") as stream:
                while True:
                    rows = supervisor.discover()
                    supervisor.reap()
                    sample = supervisor.sample(rows)
                    samples += 1
                    for key in peaks:
                        peaks[key] = max(peaks[key], sample[key])
                    stream.write(json.dumps(sample) + "\n")
                    stream.flush()
                    if interrupted:
                        stop_reason = "signal"
                        break
                    if time.monotonic() >= started + args.wall_seconds:
                        stop_reason = "wall_deadline"
                        break
                    if sample["summed_rss_bytes"] > args.memory_mib * MIB:
                        stop_reason = "monitored_memory_threshold"
                        break
                    if sample["threads"] > args.tasks:
                        stop_reason = "monitored_task_threshold"
                        break
                    if supervisor.root_status is not None:
                        stop_reason = "command_exit"
                        break
                    time.sleep(args.sample_seconds)
            returncode = {"signal": 128 + interrupted[0] if interrupted else 125,
                          "wall_deadline": 124, "monitored_memory_threshold": 137,
                          "monitored_task_threshold": 137}.get(stop_reason, supervisor.root_status)
    except (OSError, ValueError, RuntimeError) as error:
        stop_reason = stop_reason or ("signal" if interrupted else ("supervisor_error" if root_started else "preflight_failed"))
        returncode = 125
        write_json(args.receipt / "error.json", dict(schema=SCHEMA, error_class=type(error).__name__,
                                                    errno=getattr(error, "errno", None), phase=stop_reason))
    finally:
        if gate is not None:
            os.close(gate)
        if root_started:
            try:
                cleanup = supervisor.cleanup()
            except (OSError, ValueError, RuntimeError) as error:
                cleanup = dict(complete=False, error_class=type(error).__name__, remaining_unknown=True)
            supervisor.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if not cleanup["complete"]:
        returncode = 125
    launcher_code = returncode if returncode >= 0 else 128 - returncode
    cleanup_verified = bool(root_started and cleanup["complete"]
                            and cleanup.get("verified_no_waitable_children") is True
                            and not cleanup.get("remaining") and not cleanup.get("remaining_unknown"))
    write_json(args.receipt / "result.json", dict(schema=SCHEMA, mode="monitored_process_tree",
               returncode=launcher_code, command_returncode=supervisor.root_status,
               root=dict(pid=supervisor.root[0], start_ticks=supervisor.root[1]) if supervisor.root else None,
               supervisor=launch["supervisor"], source_sha256=supervisor.source_sha256,
               cleanup_verified=cleanup_verified,
               first_stop_reason=stop_reason, elapsed_s=round(time.monotonic() - started, 3),
               entry_verified=entry_verified, payload_forked=root_started,
               payload_gate_released=gate_released, cleanup=cleanup,
               interrupt_signals=interrupted, sample_count=samples, observed_peaks=peaks,
               per_job_kernel_limits_installed=False, automatic_retries=0))
    if registration is not None and cleanup["complete"]:
        registration.unlink()
    return launcher_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-mib", type=int, default=6144)
    parser.add_argument("--tasks", type=int, default=256)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--wall-seconds", type=float)
    parser.add_argument("--sample-seconds", type=float, default=.1)
    parser.add_argument("--grace-seconds", type=float, default=2)
    parser.add_argument("--cleanup-seconds", type=float, default=8)
    parser.add_argument("--cpus", help="Comma-separated subset of inherited CPU affinity")
    parser.add_argument("--probe", action="store_true", help="Read actual host bounds; never execute a payload")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if args.probe and args.command:
        parser.error("--probe cannot execute a command")
    try:
        return run(args)
    except (OSError, ValueError, RuntimeError) as error:
        print("Container job refused/receipt failed: " + type(error).__name__, file=sys.stderr)
        return 125


if __name__ == "__main__":
    sys.exit(main())
