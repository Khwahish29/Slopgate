"""Host side: run one job in the sandbox container and return the runner's result.

    from sandbox.launcher import run_poc, run_job, docker_available
    result = run_poc(workspace, claim)                       # team contract; claim = extract_repro output
    result = run_job(job, repo_path="/path/to/checkout")     # lower level, same result JSON as runner.py documents

    python -m sandbox.launcher --repo ./checkout --job job.json        # prints the result JSON
    python -m sandbox.launcher --build                                  # docker build -t slopgate-sandbox

The container gets: no network, a read-only root filesystem, a small writable tmpfs for scratch, no Linux
capabilities, no new privileges, a pid/memory/cpu cap, a non-root user, and the repo mounted read-only.
The result always has a `status`; if Docker itself is missing or fails the status is UNAVAILABLE or ERROR,
never a crash verdict, so a caller can fall back without mistaking "could not run" for "did not reproduce".
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

IMAGE = os.environ.get("SLOPGATE_SANDBOX_IMAGE", "slopgate-sandbox")
HERE = os.path.dirname(os.path.abspath(__file__))


def docker_available(docker="docker", timeout=10):
    if not shutil.which(docker):
        return False
    try:
        return subprocess.run([docker, "info"], capture_output=True, timeout=timeout).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def docker_argv(repo_path, image=IMAGE, mem_mb=1024, cpus=1.0, pids=256, tmpfs_mb=256, docker="docker"):
    """The exact `docker run` command. Kept separate so tests (and reviewers) can read the isolation flags."""
    return [docker, "run", "--rm", "-i",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/work:rw,exec,nosuid,nodev,size=%dm" % tmpfs_mb,
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", str(pids),
            "--memory", "%dm" % mem_mb,
            "--cpus", str(cpus),
            "--user", "10001:10001",
            "-v", "%s:/repo:ro" % os.path.abspath(repo_path),
            image]


def run_job(job, repo_path, timeout_s=None, image=IMAGE, docker="docker", **limits):
    if not os.path.isdir(repo_path):
        return {"status": "ERROR", "notes": "repo path is not a directory: %s" % repo_path}
    if not docker_available(docker):
        return {"status": "UNAVAILABLE", "notes": "docker is not installed or its daemon is not running"}
    job = dict(job, repo="/repo")
    lim = job.get("limits") or {}
    if timeout_s is None:                                     # whole-container cap: build + every step + start-up slack
        timeout_s = lim.get("build_timeout_s", 120) + sum(s.get("timeout_s", lim.get("step_timeout_s", 10)) for s in job.get("steps", [])) + 30
    try:
        p = subprocess.run(docker_argv(repo_path, image, docker=docker, **limits), input=json.dumps(job), capture_output=True,
                           text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "notes": "container exceeded %ss and was stopped" % timeout_s}
    except OSError as exc:
        return {"status": "ERROR", "notes": "could not start docker: %s" % exc}
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"status": "ERROR", "notes": "container returned no result (exit %s): %s" % (p.returncode, (p.stderr or p.stdout)[:400])}


SHELL_CHARS = set("|&;<>$`()")
SOURCE_EXT = {"c": "c", "cpp": "cpp", "c++": "cpp", "cc": "cpp", "python": "py", "py": "py"}


def claim_to_job(claim):
    """(job_without_repo, skipped) from a repro_extract dict. Pure; nothing runs.

    Risky commands (network, privilege, deletion, pipe-into-shell) are never put in the job; they are
    returned in `skipped`. Commands with shell operators run as `sh -c`, the rest as a plain argv.
    Source blocks are written to poc_<n>.<ext>; data blocks are ignored. If the report gave nothing
    runnable and safe, `steps` is empty and the caller gets NOT_RUNNABLE.
    """
    files, steps, skipped = {}, [], []
    for i, block in enumerate(claim.get("code") or []):
        ext = SOURCE_EXT.get((block.get("lang") or "").lower())
        if block.get("kind") == "source" and ext:
            files["poc_%d.%s" % (i, ext)] = block.get("code", "")
    for c in claim.get("commands") or []:
        if c.get("risky"):
            skipped.append(c.get("cmd"))
            continue
        cmd = (c.get("cmd") or "").strip()
        if not cmd:
            continue
        try:
            argv = ["sh", "-c", cmd] if SHELL_CHARS & set(cmd) else shlex.split(cmd)
        except ValueError:
            skipped.append(cmd)
            continue
        steps.append({"argv": argv})
    expected = {k: v for k, v in (claim.get("expected") or {}).items() if k != "span"}
    return {"files": files, "steps": steps, "expected": expected}, skipped


def run_poc(workspace, claim, ref=None, **kw):
    """The team contract: run_poc(workspace, claim) -> result.

    workspace  slopgate.agent_layer.tools.Workspace (its checkout of `ref`, or the working tree, is mounted read-only)
    claim      extract_repro(...) output, or the part of it the agent holds
    result     runner.py's result plus `skipped` (risky commands not run). Extra statuses from here:
               NOT_RUNNABLE (nothing safe to run), UNAVAILABLE (no Docker). Neither is evidence about the report.
    """
    job, skipped = claim_to_job(claim or {})
    if not job["steps"]:
        return {"status": "NOT_RUNNABLE", "observed": {}, "matches": {}, "steps": [], "skipped": skipped,
                "notes": "no runnable, non-risky command in the report"}
    path = workspace.checkout(ref or claim.get("ref"))[0]
    res = run_job(job, path, **kw)
    res.setdefault("skipped", skipped)
    return res


def build_image(image=IMAGE, docker="docker"):
    return subprocess.run([docker, "build", "-t", image, HERE]).returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true", help="build the image and exit")
    ap.add_argument("--repo")
    ap.add_argument("--job", help="job JSON file")
    args = ap.parse_args(argv)
    if args.build:
        return build_image()
    if not (args.repo and args.job):
        ap.error("--repo and --job are required (or use --build)")
    with open(args.job, encoding="utf-8") as fh:
        print(json.dumps(run_job(json.load(fh), args.repo), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
