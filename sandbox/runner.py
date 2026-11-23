"""Runs ONE reproduction job inside the sandbox container. Standard library only.

    stdin : a JSON job      stdout : a JSON result (always exactly one JSON object, exit code 0)

Job:
  {"repo": "/repo",                      # read-only checkout of the project at the claimed version
   "files": {"poc/in.txt": "text"},      # optional files to create in the scratch copy (relative paths)
   "build": ["make", "CFLAGS=-fsanitize=address -g"],   # optional argv, run in the scratch copy
   "steps": [{"argv": ["./prog", "poc/in.txt"], "stdin": "", "timeout_s": 10}],
   "expected": {"sanitizer": "AddressSanitizer", "error": "heap-buffer-overflow",
                "signal": null, "frames": ["buf_reserve"], "crash_in": "lib/buf.c"},
   "limits": {"cpu_s": 20, "mem_mb": 1024, "out_kb": 64, "file_mb": 64}}

Result: {"status", "observed", "matches", "build", "steps", "notes"} with status one of
  REPRODUCED      a step crashed and the crash matches every field given in `expected`
  CRASH_MISMATCH  a step crashed but not the way the report says
  NOT_REPRODUCED  every step ran to completion without a crash
  BUILD_FAILED / TIMEOUT / REFUSED / ERROR
`observed` is {sanitizer, error, signal, frames, crash_in, exit_code, step}; `matches` says per field
whether it agreed. A crash that does not match is NOT evidence the report is true, and NOT_REPRODUCED
is not proof it is false: the caller decides what either means.

Safety here is defence in depth: the container (launcher.py) is the boundary; this file additionally
refuses program names outside ALLOWED, paths that leave the scratch copy, and applies rlimits.
"""
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile

ALLOWED = {"make", "gcc", "cc", "clang", "g++", "c++", "sh", "bash", "valgrind", "python3", "cmake", "ctest", "xxd", "head", "printf", "echo", "cat", "true"}
DEFAULT_LIMITS = {"cpu_s": 20, "mem_mb": 1024, "out_kb": 64, "file_mb": 64, "step_timeout_s": 10, "build_timeout_s": 120}
SIGNALS = {signal.SIGSEGV: "SIGSEGV", signal.SIGABRT: "SIGABRT", signal.SIGFPE: "SIGFPE",
           signal.SIGBUS: "SIGBUS", signal.SIGILL: "SIGILL"}
ASAN = re.compile(r"ERROR: (AddressSanitizer|LeakSanitizer|MemorySanitizer|UndefinedBehaviorSanitizer|ThreadSanitizer): ([A-Za-z0-9_-]+)")
UBSAN = re.compile(r"^(\S+?):(\d+):\d+: runtime error: (.+)$", re.M)
FRAME = re.compile(r"^\s*#\d+ 0x[0-9a-f]+ in (\S+) (\S+?)(?::\d+)?(?::\d+)?\s*$", re.M)
VALGRIND = re.compile(r"==\d+== (Invalid (?:read|write) of size \d+|Conditional jump or move depends on uninitialised|Process terminating with default action of signal \d+ \((\w+)\))")


class Refused(Exception):
    pass


def clip(text, limit_kb):
    b = (text or "").encode("utf-8", "replace")
    if len(b) <= limit_kb * 1024:
        return b.decode("utf-8", "replace")
    return b[: limit_kb * 1024].decode("utf-8", "replace") + "\n... [truncated, %d bytes total]" % len(b)


def safe_rel(root, rel):
    """Absolute path of `rel` inside root, or Refused if it leaves root."""
    full = os.path.realpath(os.path.join(root, rel))
    if os.path.isabs(rel) or not (full == root or full.startswith(root + os.sep)):
        raise Refused("path leaves the scratch directory: %s" % rel)
    return full


def check_argv(argv):
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise Refused("argv must be a non-empty list of strings")
    prog = os.path.basename(argv[0])
    # the program under test is built into the scratch copy and run as ./name or a relative path
    if argv[0].startswith("./") or ("/" in argv[0] and not os.path.isabs(argv[0])):
        return
    if prog not in ALLOWED:
        raise Refused("program not allowed: %s" % argv[0])


def make_preexec(limits):
    def fn():
        os.setsid()
        mb = limits["mem_mb"] * 1024 * 1024
        for res, val in ((resource.RLIMIT_CPU, limits["cpu_s"]), (resource.RLIMIT_FSIZE, limits["file_mb"] * 1024 * 1024),
                         (resource.RLIMIT_NPROC, 256), (resource.RLIMIT_CORE, 0)):
            resource.setrlimit(res, (val, val))
        try:                                     # ASan reserves huge virtual ranges, so only cap when not sanitising
            if os.environ.get("SLOPGATE_CAP_AS", "") == "1":
                resource.setrlimit(resource.RLIMIT_AS, (mb, mb))
        except (ValueError, OSError):
            pass
    return fn


def run(argv, cwd, stdin, timeout_s, limits, env=None):
    check_argv(argv)
    e = dict(os.environ, **(env or {}))
    e.setdefault("ASAN_OPTIONS", "detect_leaks=0:abort_on_error=0:symbolize=1")
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             preexec_fn=make_preexec(limits), env=e)
    except FileNotFoundError:
        return {"argv": argv, "exit_code": 127, "signal": None, "timed_out": False, "stdout": "", "stderr": "not found: %s" % argv[0]}
    try:
        out, err = p.communicate((stdin or "").encode(), timeout=timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        out, err = p.communicate()
        timed_out = True
    sig = None
    code = p.returncode
    if code is not None and code < 0:
        sig = SIGNALS.get(signal.Signals(-code), signal.Signals(-code).name)
    return {"argv": argv, "exit_code": code, "signal": sig, "timed_out": timed_out,
            "stdout": clip(out.decode("utf-8", "replace"), limits["out_kb"]),
            "stderr": clip(err.decode("utf-8", "replace"), limits["out_kb"])}


def parse_crash(res, root=""):
    """What the program's output says about how it died. Empty dict if it did not crash."""
    if res.get("timed_out"):
        return {}
    text = res["stderr"] + "\n" + res["stdout"]
    if root:                                     # report repo-relative paths, not the scratch location
        text = text.replace(root.rstrip("/") + "/", "")
    obs = {}
    m = ASAN.search(text)
    if m:
        obs["sanitizer"], obs["error"] = m.group(1), m.group(2)
    else:
        u = UBSAN.search(text)
        if u:
            obs["sanitizer"], obs["error"], obs["crash_in"] = "UndefinedBehaviorSanitizer", u.group(3), u.group(1)
        else:
            v = VALGRIND.search(text)
            if v:
                obs["sanitizer"], obs["error"] = "Valgrind", v.group(1)
                if v.group(2):
                    obs["signal"] = "SIG" + v.group(2) if not v.group(2).startswith("SIG") else v.group(2)
    if res.get("signal") in SIGNALS.values() and not res.get("timed_out"):   # SIGKILL (timeout, OOM) is not a crash
        obs["signal"] = res["signal"]
    frames = []
    for fn, loc in FRAME.findall(text):
        if not fn.startswith("__") and "libc" not in loc and "libasan" not in loc and "sanitizer" not in loc:
            frames.append((fn, loc.rsplit(":", 1)[0] if ":" in loc else loc))
    if frames:
        obs["frames"] = [f for f, _ in frames[:12]]
        obs.setdefault("crash_in", frames[0][1])
    return obs


def compare(expected, observed):
    """Per-field agreement for the fields `expected` actually gives. Frames match if any wanted name appears."""
    out = {}
    for key, want in (expected or {}).items():
        if want in (None, "", []):
            continue
        got = observed.get(key)
        if key == "frames":
            out[key] = bool(got) and any(w in got for w in want)
        elif key == "crash_in":
            out[key] = bool(got) and (str(got).endswith(str(want)) or str(want).endswith(str(got)))
        elif key == "error":
            out[key] = bool(got) and (str(want).lower() in str(got).lower() or str(got).lower() in str(want).lower())
        else:
            out[key] = got == want
    return out


def execute(job):
    limits = dict(DEFAULT_LIMITS, **(job.get("limits") or {}))
    repo = job.get("repo")
    if not repo or not os.path.isdir(repo):
        return {"status": "ERROR", "notes": "repo directory missing: %s" % repo}
    scratch_root = tempfile.mkdtemp(prefix="job-", dir=os.environ.get("SLOPGATE_WORK", "/work"))
    root = os.path.realpath(os.path.join(scratch_root, "src"))
    result = {"status": "ERROR", "observed": {}, "matches": {}, "build": None, "steps": [], "notes": ""}
    try:
        shutil.copytree(repo, root, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        for rel, content in (job.get("files") or {}).items():
            path = safe_rel(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        if job.get("build"):
            b = run(job["build"], root, "", limits["build_timeout_s"], limits)
            result["build"] = {k: b[k] for k in ("argv", "exit_code", "timed_out", "stderr")}
            if b["timed_out"]:
                result["status"] = "TIMEOUT"
                result["notes"] = "build timed out"
                return result
            if b["exit_code"] != 0:
                result["status"] = "BUILD_FAILED"
                return result
        crashed = None
        for i, step in enumerate(job.get("steps") or []):
            res = run(step.get("argv"), root, step.get("stdin", ""), step.get("timeout_s", limits["step_timeout_s"]), limits, step.get("env"))
            obs = parse_crash(res, root)
            result["steps"].append({"i": i, "argv": res["argv"], "exit_code": res["exit_code"], "signal": res["signal"],
                                    "timed_out": res["timed_out"], "stdout": res["stdout"], "stderr": res["stderr"]})
            if obs and crashed is None:
                crashed = dict(obs, exit_code=res["exit_code"], step=i)
        if crashed:
            result["observed"] = crashed
            result["matches"] = compare(job.get("expected"), crashed)
            ok = bool(result["matches"]) and all(result["matches"].values())
            result["status"] = "REPRODUCED" if ok else "CRASH_MISMATCH"
            if not result["matches"]:
                result["notes"] = "crash observed; the report named no crash details to compare"
        elif any(s["timed_out"] for s in result["steps"]):
            result["status"] = "TIMEOUT"
        else:
            result["status"] = "NOT_REPRODUCED"
        return result
    except Refused as exc:
        result.update(status="REFUSED", notes=str(exc))
        return result
    except Exception as exc:                                         # never let a job crash the runner silently
        result.update(status="ERROR", notes="%s: %s" % (type(exc).__name__, exc))
        return result
    finally:
        shutil.rmtree(scratch_root, ignore_errors=True)


def main():
    try:
        job = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "ERROR", "notes": "job is not valid JSON: %s" % exc}))
        return 0
    print(json.dumps(execute(job)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
