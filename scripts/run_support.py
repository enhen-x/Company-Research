"""Bounded processes, atomic files and deterministic fingerprints (stdlib only)."""
from __future__ import annotations

import codecs
import hashlib
import json
import math
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_text(path, text):
    """Replace one owned file; unchanged content keeps its mtime and no temp remains."""
    path = Path(path)
    payload = text.encode("utf-8")
    try:
        if path.read_bytes() == payload:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def atomic_json(path, payload):
    return atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def fingerprints(project, folders):
    project = Path(project)
    found = {}
    for folder in folders:
        base = project / folder
        for p in sorted(base.rglob("*")) if base.is_dir() else [base]:
            if not p.is_file() or any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(project).parts):
                continue
            if p.suffix.lower() not in (".csv", ".json", ".py", ".md", ".png", ".html"):
                continue
            found[p.relative_to(project).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(found, sort_keys=True).encode()).hexdigest()
    return {"sha256": digest, "files": found}


class BatchLock:
    """A nonblocking OS lock; a crashed worker cannot leave a stale lock owner."""
    def __init__(self, path):
        self.path = Path(path)
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError(f"同一批次正在运行，请等待现有任务结束：{self.path}") from exc
        self.stream = stream
        return self

    def __exit__(self, *args):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class _WindowsJob:
    """Kill descendants even if their immediate parent exits with stdout inherited."""
    def __init__(self, proc):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("ProcessUserTime", ctypes.c_longlong), ("JobUserTime", ctypes.c_longlong),
                        ("Flags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                        ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcesses", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]

        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IO", Counters), ("ProcessMemory", ctypes.c_size_t),
                        ("JobMemory", ctypes.c_size_t), ("PeakProcessMemory", ctypes.c_size_t),
                        ("PeakJobMemory", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            return
        limits = Extended()
        limits.Basic.Flags = 0x2000
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, int(proc._handle)):
            kernel.CloseHandle(handle)
            return
        self.handle = handle

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def kill_tree(proc, job=None):
    if job is not None:
        job.close()
    if os.name == "nt" and proc.poll() is None:
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass
    elif os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass


def run_process(command, *, cwd=None, timeout=900, heartbeat=10, label="阶段", echo=True):
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v <= 0
           for v in (timeout, heartbeat)):
        raise ValueError("timeout/heartbeat 必须为有限正数")
    started = time.monotonic()
    result = {"command": list(map(str, command)), "started_at": now(), "status": "RUNNING"}
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    opts = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **opts)
    except OSError as exc:
        return dict(result, status="FAIL", exit_code=None, error=str(exc), elapsed_seconds=0, finished_at=now(), output="")
    job = _WindowsJob(proc)
    messages = queue.Queue(maxsize=64)
    stop = threading.Event()

    def put(item):
        while not stop.is_set():
            try:
                messages.put(item, timeout=.1)
                return
            except queue.Full:
                pass

    def read_output():
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while not stop.is_set():
                block = proc.stdout.read1(4096)
                if not block:
                    break
                put(decoder.decode(block))
            tail = decoder.decode(b"", final=True)
            if tail:
                put(tail)
        except (OSError, ValueError):
            pass
        finally:
            put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    tail, ended, timed_out = "", False, False
    next_beat = started + heartbeat
    try:
        while not ended or proc.poll() is None:
            current = time.monotonic()
            if current - started >= timeout:
                timed_out = True
                kill_tree(proc, job)
                print(f"[{label}] TIMEOUT：已终止进程树并停止等待输出，上限 {timeout:g}s", flush=True)
                break
            if current >= next_beat:
                print(f"[{label}] 仍在运行，已用 {current-started:.1f}s（上限 {timeout:g}s）", flush=True)
                next_beat = current + heartbeat
            try:
                block = messages.get(timeout=min(.1, max(.001, timeout-(current-started))))
            except queue.Empty:
                continue
            if block is None:
                ended = True
            else:
                tail = (tail + block)[-12000:]
                if echo:
                    print(block, end="", flush=True)
    except BaseException:
        kill_tree(proc, job)
        raise
    finally:
        job.close()
        stop.set()
        reader.join(timeout=.5)
        if not reader.is_alive():
            proc.stdout.close()
    code = proc.poll()
    return dict(result, status="TIMEOUT" if timed_out else ("PASS" if code == 0 else "FAIL"),
                exit_code=code, elapsed_seconds=round(time.monotonic()-started, 3), finished_at=now(), output=tail)
