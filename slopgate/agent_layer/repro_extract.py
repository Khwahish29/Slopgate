"""Repro-claim extractor: what a report says to RUN and what it says will HAPPEN.

This feeds the sandbox (the REPRODUCIBLE path). It is pure text processing: nothing here runs,
fetches or writes anything. The sandbox decides what, if anything, to execute; this module only
turns the report's reproduction section into structured, checkable data and marks what looks
unsafe or inconsistent.

    repro = extract_repro(clean_text, claims)       # clean_text: output of extract.sanitize

Output (a plain dict, JSON-serialisable):

    has_repro      bool: any step, command, code block or expected outcome was found
    steps          [{text, span}]                prose reproduction steps, in order
    commands       [{cmd, program, span, risky}] shell command lines (from code blocks or `$ ...`)
    code           [{lang, code, kind}]          fenced blocks; kind = shell | source | trace | data
    inputs         [{kind, value, span}]         urls, sizes/lengths, files, hex/byte strings
    build          {flags, configure}            -fsanitize=..., ./configure / cmake options
    expected       {sanitizer, error, signal, frames, crash_in, span}
    target         {symbol, path, line}          the load-bearing claims the repro is about
    consistency    {frames_mention_target, crash_in_target, notes}
    sandbox_ready  bool: at least one command or source block, and an expected outcome to compare

Untrusted input: spans are verbatim from the sanitised text, commands are never interpreted, and
`risky` flags (network fetches to non-local hosts, privilege, deletion, piping into a shell) are
advisory for the sandbox, which must enforce its own isolation regardless.
"""
import re

REPRO_HEADINGS = re.compile(
    r"(?im)^\s*(?:#+\s*|\*\*)?\s*(?:proof[- ]of[- ]concept|poc|steps? to reproduce|reproduc(?:e|tion|ing)|"
    r"how to reproduce|exploit|test ?case|crash(?:ing)? input)\b")
NEXT_HEADING = re.compile(r"(?m)^\s*(?:#+\s+\S|\*\*[^*\n]{2,40}:?\*\*\s*$)")
INLINE_REPRO = re.compile(r"(?im)^\s*(?:\*\*)?(?:steps(?: to reproduce)?|reproduction|to reproduce|repro|poc|"
                          r"proof of concept)(?:\*\*)?\s*:(?:\*\*)?\s*(.+)$")
FENCE = re.compile(r"```[ \t]*([\w+-]*)[^\n]*\n(.*?)```", re.S)
STEP_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+(.+)$", re.M)
PROMPT_CMD = re.compile(r"^\s*[$#>]\s+(.+)$", re.M)          # inside a shell block: $, # (root) or >
DOLLAR_CMD = re.compile(r"^\s*\$\s+(.+)$", re.M)               # in prose only "$ " (# is a heading, > a quote)

SHELL_LANGS = {"sh", "bash", "shell", "console", "zsh", "shell-session", "cmd", "powershell"}
SOURCE_LANGS = {"c", "cpp", "c++", "h", "python", "py", "go", "rust", "js", "javascript"}
KNOWN_PROGRAMS = {"curl", "gcc", "clang", "make", "cmake", "./configure", "python", "python3", "nc",
                  "printf", "echo", "valgrind", "gdb", "./a.out", "bash", "sh", "perl", "xxd",
                  "git", "cc", "ninja", "meson", "openssl", "wget", "timeout"}

SANITIZER_RE = re.compile(r"\b(AddressSanitizer|UndefinedBehaviorSanitizer|MemorySanitizer|ThreadSanitizer|"
                          r"LeakSanitizer|ASan|UBSan|MSan|TSan|Valgrind)\b")
ERROR_RE = re.compile(r"\b(heap-buffer-overflow|stack-buffer-overflow|global-buffer-overflow|"
                      r"heap-use-after-free|stack-use-after-return|double-free|attempting double-free|"
                      r"use-after-poison|SEGV on unknown address|null-pointer-dereference|"
                      r"signed-integer-overflow|memory leak|invalid read|invalid write|"
                      r"stack-overflow|alloc-dealloc-mismatch)\b", re.I)
SIGNAL_RE = re.compile(r"\b(SIGSEGV|SIGABRT|SIGBUS|SIGFPE|SIGILL|segmentation fault|abort(?:ed)?)\b", re.I)
# one-line traces: "heap-use-after-free in replace_existing lib/cookie.c:915, called from Curl_cookie_add ..."
INLINE_FRAME_RE = re.compile(r"\b(?:in|from|at)\s+`?([A-Za-z_]\w*)(?:\(\))?`?\s+\(?`?([\w./-]+\.\w{1,4}):(\d+)")
# ASan / gdb frames: "#1 0x5124f0 in chunk_decode lib/chunk.c:36:5" or "... in main (/path/bin+0x12)"
FRAME_RE = re.compile(r"#\d+\s+0x[0-9a-fA-F]+\s+in\s+([A-Za-z_]\w*)(?:[ \t]+\(?([\w./-]+\.\w{1,4}):(\d+))?")

URL_RE = re.compile(r"\b(?:https?|ftp|wss?|file)://[^\s`'\"<>)]+")
SIZE_RE = re.compile(r"(?i)\b(\d{2,9})\s*(?:-|\s)?(bytes?|characters?|chars?|kb|kib|mb|mib)\b")
HEXBYTES_RE = re.compile(r"(?:\\x[0-9a-fA-F]{2}){2,}|\b0x[0-9a-fA-F]{4,}\b")
FILE_INPUT_RE = re.compile(r"(?i)\b(?:input|test|crash|poc|payload)[\w.-]*\.(?:txt|bin|json|cfg|conf|raw|dat|http)\b")

LOCAL_HOSTS = re.compile(r"(?i)^(?:[a-z]+://)?(?:localhost|127\.\d+\.\d+\.\d+|\[?::1\]?|0\.0\.0\.0)(?::\d+)?(?:/|$)")
RISK_RULES = [
    ("privilege", re.compile(r"(?:^|[;&|]\s*)(?:sudo|su|doas)\b")),
    ("deletes_files", re.compile(r"\brm\s+-[a-zA-Z]*[rf]|\bmkfs\b|\bdd\s+if=")),
    ("pipe_to_shell", re.compile(r"\|\s*(?:ba|z)?sh\b|\beval\b|\bsource\s+<\(")),
    ("writes_system", re.compile(r">\s*/(?:etc|usr|bin|boot|dev/sd)")),
    ("background_or_persist", re.compile(r"\bnohup\b|\bcrontab\b|\bsystemctl\b|&\s*$")),
]


def _section(text):
    """The reproduction section: from a PoC/steps heading to the next heading."""
    m = REPRO_HEADINGS.search(text)
    if not m:
        return ""
    start = text.find("\n", m.end())
    start = m.end() if start < 0 else start
    nxt = NEXT_HEADING.search(text, start + 1)
    return text[m.start():nxt.start() if nxt else len(text)]


def _program(cmd):
    tok = cmd.strip().split()
    while tok and re.fullmatch(r"[A-Z_][A-Z0-9_]*=\S*", tok[0]):     # FOO=bar cmd
        tok = tok[1:]
    return tok[0] if tok else ""


def _risky(cmd):
    out = [name for name, rx in RISK_RULES if rx.search(cmd)]
    for url in URL_RE.findall(cmd):
        if not LOCAL_HOSTS.match(url):
            out.append("network_non_local")
            break
    return out


def _classify_block(lang, body):
    lang = (lang or "").lower()
    if lang in SHELL_LANGS:
        return "shell"
    if lang in SOURCE_LANGS:
        return "source"
    if FRAME_RE.search(body) or SANITIZER_RE.search(body) or ERROR_RE.search(body):
        return "trace"
    first = body.strip().splitlines()[0] if body.strip() else ""
    if PROMPT_CMD.match(first) or _program(first.lstrip("$# ")) in KNOWN_PROGRAMS:
        return "shell"
    if re.search(r"#include\s*<|\bint\s+main\s*\(|\bdef\s+\w+\(|\bimport\s+\w+", body):
        return "source"
    return "data"


def _commands_from(body, kind):
    cmds = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        while ln.endswith("\\") and i + 1 < len(lines):        # line continuations
            i += 1
            ln = ln[:-1].rstrip() + " " + lines[i].strip()
        i += 1
        s = ln.strip()
        if not s or s.startswith("#!"):
            continue
        pm = PROMPT_CMD.match(s)
        if pm:
            s = pm.group(1).strip()
        elif kind != "shell":
            continue
        if s.startswith("#"):
            continue
        cmds.append(s)
    return cmds


def _expected(text):
    exp = {"sanitizer": None, "error": None, "signal": None, "frames": [], "crash_in": None, "span": None}
    m = SANITIZER_RE.search(text)
    if m:
        exp["sanitizer"] = m.group(1)
    m = ERROR_RE.search(text)
    if m:
        exp["error"] = m.group(1).lower()
        ln_start = text.rfind("\n", 0, m.start()) + 1
        ln_end = text.find("\n", m.end())
        exp["span"] = text[ln_start:ln_end if ln_end >= 0 else len(text)].strip()
    m = SIGNAL_RE.search(text)
    if m:
        exp["signal"] = m.group(1)
    for f in FRAME_RE.finditer(text):
        exp["frames"].append({"function": f.group(1), "file": f.group(2),
                              "line": int(f.group(3)) if f.group(3) else None})
    if not exp["frames"] and exp["span"]:
        for f in INLINE_FRAME_RE.finditer(exp["span"]):
            exp["frames"].append({"function": f.group(1), "file": f.group(2), "line": int(f.group(3))})
    skip = {"__interceptor_memcpy", "__asan_memcpy", "memcpy", "strcpy", "memmove", "strlen", "__libc_start_main",
            "_start", "main", "__interceptor_strcpy", "__interceptor_strlen", "malloc", "free", "realloc"}
    for f in exp["frames"]:
        if f["function"] not in skip and not f["function"].startswith(("__asan", "__interceptor", "__sanitizer")):
            exp["crash_in"] = f["function"]
            break
    return exp


def _target(claims):
    def lb(t):
        c = [x for x in (claims or []) if x["type"] == t]
        c.sort(key=lambda x: x.get("role") != "load-bearing")
        return c[0]["value"] if c else None
    return {"symbol": lb("symbol"), "path": lb("path"), "line": lb("line")}


def extract_repro(text, claims=None):
    """Structured reproduction claims from sanitised report text. See module docstring."""
    text = text or ""
    section = _section(text)
    steps, commands, code, inputs = [], [], [], []

    scope = section or text
    for m in STEP_LINE.finditer(section):
        steps.append({"text": m.group(1).strip(), "span": m.group(0).strip()})
    if not steps:
        for m in INLINE_REPRO.finditer(text):
            steps.append({"text": m.group(1).strip(), "span": m.group(0).strip()})
    if section and not steps:
        body = [ln.strip() for ln in section.splitlines()
                if ln.strip() and not ln.strip().startswith("```") and not REPRO_HEADINGS.match(ln)]
        if body and not FENCE.search(section):
            steps.append({"text": " ".join(body)[:500], "span": body[0]})

    for m in FENCE.finditer(text):
        lang, body = m.group(1), m.group(2)
        kind = _classify_block(lang, body)
        code.append({"lang": lang or None, "code": body, "kind": kind})
        if kind == "shell":
            for c in _commands_from(body, kind):
                commands.append({"cmd": c, "program": _program(c), "span": c, "risky": _risky(c)})
    outside = FENCE.sub("", scope)
    for m in DOLLAR_CMD.finditer(outside):
        c = m.group(1).strip()
        if _program(c) in KNOWN_PROGRAMS or "/" in _program(c):
            commands.append({"cmd": c, "program": _program(c), "span": m.group(0).strip(), "risky": _risky(c)})
    for m in re.finditer(r"`([^`\n]{3,200})`", outside):          # inline `curl -H ... http://...`
        c = m.group(1).strip()
        if _program(c) in KNOWN_PROGRAMS and " " in c and not any(x["cmd"] == c for x in commands):
            commands.append({"cmd": c, "program": _program(c), "span": m.group(0), "risky": _risky(c)})

    seen = set()
    for kind, rx in (("url", URL_RE), ("size", SIZE_RE), ("bytes", HEXBYTES_RE), ("file", FILE_INPUT_RE)):
        for m in rx.finditer(scope):
            v = m.group(0)
            if kind == "url" and "cwe.mitre.org" in v:
                continue
            if (kind, v) in seen:
                continue
            seen.add((kind, v))
            inputs.append({"kind": kind, "value": v,
                           "span": scope[max(0, m.start() - 40):m.end() + 40].strip()})

    flags = sorted(set(re.findall(r"-fsanitize=[\w,-]+|-g\b|-O[0-3sz]\b|-fno-omit-frame-pointer", text)))
    configure = [c["cmd"] for c in commands if c["program"] in ("./configure", "cmake", "meson")]

    expected = _expected(text)
    target = _target(claims)
    notes = []
    names = [f["function"] for f in expected["frames"]]
    frames_mention = bool(target["symbol"]) and target["symbol"] in names
    crash_in_target = bool(target["symbol"]) and expected["crash_in"] == target["symbol"]
    if names and target["symbol"] and not frames_mention:
        notes.append("stack trace never mentions the claimed function '%s'" % target["symbol"])
    for f in expected["frames"]:
        if f["function"] == target["symbol"] and f["file"] and target["path"] and \
                not f["file"].endswith(target["path"]) and not target["path"].endswith(f["file"]):
            notes.append("trace puts '%s' in %s, the report claims %s" % (f["function"], f["file"], target["path"]))
            break
    if any(c["risky"] for c in commands):
        notes.append("some commands are flagged risky; the sandbox must not run them as written")

    has_repro = bool(steps or commands or code or expected["error"] or expected["signal"])
    runnable = bool(commands or any(c["kind"] == "source" for c in code))
    has_oracle = bool(expected["error"] or expected["signal"] or expected["crash_in"])
    return {"has_repro": has_repro, "steps": steps, "commands": commands, "code": code, "inputs": inputs,
            "build": {"flags": flags, "configure": configure}, "expected": expected, "target": target,
            "consistency": {"frames_mention_target": frames_mention, "crash_in_target": crash_in_target,
                            "notes": notes},
            "sandbox_ready": runnable and has_oracle}
