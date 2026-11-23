# Reproduction sandbox

Runs a proof-of-concept from a report against the claimed version of the code, in a locked-down Docker container, and says whether it crashed the way the report says. Files: `sandbox/Dockerfile`, `sandbox/runner.py` (inside the container), `sandbox/launcher.py` (host), tests in `tests/test_sandbox.py`.

## How the pieces connect

```
report ──► repro_extract (Khwahish) ──► job JSON ──► agent_layer/sandbox.py (Prakruti)
                                                         │ run_job(job, repo_path)
                                                         ▼
                                  sandbox/launcher.py ──► docker run … slopgate-sandbox ──► runner.py
                                                         ◄────────── result JSON ◄────────────┘
```

`repro_extract` already produces steps, commands, expected `{sanitizer, error, signal, frames, crash_in}` and a `sandbox_ready` flag. The job below is that output reshaped; the integration layer owns that mapping.

## Team contract

`run_poc(workspace, claim) -> result` in `sandbox/launcher.py`. `workspace` is the agent's `Workspace` (its checkout of the claimed ref is mounted read-only), `claim` is the `extract_repro` dict. `claim_to_job` does the mapping: non-risky commands become steps (`sh -c` if they use shell operators), source blocks become `poc_<n>.<ext>` files, risky commands are returned in `skipped` and never run, `expected` is passed through. Nothing runnable and safe gives `NOT_RUNNABLE` without starting Docker. Prakruti's `agent_layer/sandbox.py` only needs to call this and turn the status into evidence.

## Job (stdin of the runner / first argument of `run_job`)

| field | meaning |
|---|---|
| `repo` | checkout of the project at the claimed version (the launcher mounts it read-only at `/repo`) |
| `files` | `{relative path: text}` written into the scratch copy, e.g. the PoC input |
| `build` | argv, e.g. `["make", "CFLAGS=-fsanitize=address -g"]` |
| `steps` | `[{argv, stdin, timeout_s, env}]`, run in order; `./prog` style paths run the built program |
| `expected` | what the report claims: `sanitizer`, `error`, `signal`, `frames` (any listed name must appear in the stack), `crash_in` |
| `limits` | `cpu_s`, `mem_mb`, `out_kb`, `file_mb`, `step_timeout_s`, `build_timeout_s` |

## Result

`status`: `REPRODUCED` (crashed and every given `expected` field matched), `CRASH_MISMATCH` (crashed differently), `NOT_REPRODUCED` (no crash), `BUILD_FAILED`, `TIMEOUT`, `REFUSED` (a program or path outside the allowed set), `ERROR`, and from the launcher only `UNAVAILABLE` (no Docker), `NOT_RUNNABLE` (nothing safe to run).
Also: `observed` (what crashed: sanitizer, error, signal, frames, `crash_in` repo-relative, exit code, step), `matches` (per-field agreement), `build`, per-step `steps` with clipped stdout/stderr, `notes`.

How to read it: `REPRODUCED` is evidence for the report. `NOT_REPRODUCED` is **not** proof the report is false (the PoC may be incomplete), so it should lead to UNVERIFIED, not HALLUCINATED, unless other evidence refutes the report. `NOT_RUNNABLE`/`UNAVAILABLE`/`ERROR`/`TIMEOUT` mean "could not decide" and must never be treated as a negative.

## Isolation

The container runs with no network, read-only root filesystem, a 256 MB writable `/work` tmpfs, all Linux capabilities dropped, `no-new-privileges`, a 256-process cap, 1 GB memory and 1 CPU, as a non-root user; the repo is mounted read-only and copied into scratch, so a job cannot change it. The whole container has a wall-clock cap, and the runner adds CPU/file-size rlimits, an output cap, a program allowlist and a refusal of paths that leave the scratch directory. The allowlist is a second layer, not the boundary: the container is.

## Use

```
make sandbox-image                                  # docker build -t slopgate-sandbox sandbox/
python -m sandbox.launcher --repo ./checkout --job job.json
```

```python
from sandbox.launcher import run_job
result = run_job(job, repo_path="corpus/fixtures/pktbuf")
```

## Verified, and not

The runner is tested against real `gcc` (AddressSanitizer crash, plain SIGSEGV, build failure, timeout, clean run, path refusal, scratch cleanup). The launcher is tested with Docker mocked, including the exact isolation flags. **The Docker image itself has not been built or run end to end** where this was written (no Docker daemon); run `make sandbox-image` and one job on a machine with Docker before relying on it. Valgrind output is parsed but only lightly tested.
