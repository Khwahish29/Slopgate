#!/usr/bin/env python3
"""Build the git-backed fixture repositories used by D1, D3 and D4.

    python3 corpus/fixtures/build_fixtures.py        # writes corpus/fixtures/out/ (git-ignored)

minihttp-git   the bundled C repo with real history:
    minihttp-0_9   adds lib/compat.c: legacy_parse_header(), url_escape_old()
    minihttp-1_0   removes legacy_parse_header(); renames url_escape_old() -> url_escape()
    minihttp-1_1   (HEAD) adds chunk_trailer_parse()
pytoy-git      a small Python package, one tag (v1.0) and a later commit

Everything is deterministic (fixed dates and identities), so gold labels that depend on
history stay true. Rebuilding replaces out/ completely.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "out")
ENV = dict(os.environ, GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
           GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")


def git(cwd, *args, date=None):
    env = dict(ENV)
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
                   cwd=cwd, env=env, check=True, capture_output=True)


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


COMPAT = '''/* compat.c - 0.9 compatibility helpers */
#include <string.h>
#include "url.h"

int legacy_parse_header(const char *line, char *out, size_t outlen)
{
  const char *colon = strchr(line, ':');
  size_t n;
  if(!colon || !out)
    return -1;
  n = (size_t)(colon - line);
  if(n >= outlen)
    return -1;
  memcpy(out, line, n);
  out[n] = 0;
  return 0;
}

int url_escape_old(const char *in, char *out, size_t outlen)
{
  size_t i = 0, w = 0;
  while(in[i] && w + 3 < outlen) {
    if(in[i] == ' ') {
      out[w++] = '%'; out[w++] = '2'; out[w++] = '0';
    }
    else
      out[w++] = in[i];
    i++;
  }
  out[w] = 0;
  return 0;
}
'''

URL_ESCAPE = '''
int url_escape(const char *in, char *out, size_t outlen)
{
  size_t i = 0, w = 0;
  while(in[i] && w + 3 < outlen) {
    if(in[i] == ' ') {
      out[w++] = '%'; out[w++] = '2'; out[w++] = '0';
    }
    else
      out[w++] = in[i];
    i++;
  }
  out[w] = 0;
  return 0;
}
'''

TRAILER = '''
/* trailer headers follow the last chunk */
int chunk_trailer_parse(const char *buf, size_t len)
{
  size_t i;
  if(!buf)
    return -1;
  for(i = 0; i + 1 < len; i++) {
    if(buf[i] == '\\r' && buf[i + 1] == '\\n')
      return (int)i;
  }
  return -1;
}
'''


def build_c(out):
    src = os.path.join(ROOT, "corpus", "d0", "target_repo")
    dst = os.path.join(out, "minihttp-git")
    shutil.copytree(src, dst)
    git(dst, "init", "-q")
    git(dst, "add", "-A")
    write(dst, "lib/compat.c", COMPAT)
    git(dst, "add", "-A")
    git(dst, "commit", "-qm", "minihttp 0.9", date="2024-01-10T12:00:00Z")
    git(dst, "tag", "minihttp-0_9")
    os.remove(os.path.join(dst, "lib/compat.c"))
    with open(os.path.join(dst, "lib/url.c"), "a") as f:
        f.write(URL_ESCAPE)
    git(dst, "add", "-A")
    git(dst, "commit", "-qm", "1.0: drop legacy_parse_header, rename url_escape_old to url_escape",
        date="2024-06-10T12:00:00Z")
    git(dst, "tag", "minihttp-1_0")
    with open(os.path.join(dst, "lib/http_chunks.c"), "a") as f:
        f.write(TRAILER)
    git(dst, "add", "-A")
    git(dst, "commit", "-qm", "1.1: parse chunk trailers", date="2024-11-10T12:00:00Z")
    git(dst, "tag", "minihttp-1_1")


PY = {
    "pytoy/__init__.py": "",
    "pytoy/parser.py": '''"""HTTP-ish header and chunk parsing."""


def parse_header(line):
    name, _, value = line.partition(":")
    return name.strip(), value.strip()


def decode_chunk(buf, size):
    if size > len(buf):
        raise ValueError("short chunk")
    return buf[:size]


def legacy_split(line):
    # kept for the 0.x shim; never called
    return line.split(":", 1)
''',
    "pytoy/util.py": '''def clamp(n, lo, hi):
    return max(lo, min(n, hi))


def read_exact(stream, n):
    data = stream.read(n)
    if len(data) != n:
        raise EOFError("short read")
    return data
''',
    "pytoy/cli.py": '''import sys

from pytoy.parser import decode_chunk, parse_header
from pytoy.util import read_exact


def main():
    line = sys.stdin.readline()
    name, value = parse_header(line)
    body = decode_chunk(read_exact(sys.stdin.buffer, 4), 4)
    print(name, value, body)


if __name__ == "__main__":
    main()
''',
}

PY_LATER = '''

def parse_trailer(line):
    return parse_header(line)
'''


def build_py(out):
    dst = os.path.join(out, "pytoy-git")
    os.makedirs(dst)
    git(dst, "init", "-q")
    for rel, text in PY.items():
        write(dst, rel, text)
    git(dst, "add", "-A")
    git(dst, "commit", "-qm", "pytoy 1.0", date="2024-03-01T12:00:00Z")
    git(dst, "tag", "v1.0")
    with open(os.path.join(dst, "pytoy/parser.py"), "a") as f:
        f.write(PY_LATER)
    git(dst, "add", "-A")
    git(dst, "commit", "-qm", "add parse_trailer", date="2024-08-01T12:00:00Z")


def build(force=False):
    if os.path.isdir(OUT) and os.listdir(OUT) and not force:
        return OUT
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    build_c(OUT)
    build_py(OUT)
    return OUT


if __name__ == "__main__":
    print("built", build(force=True))
    sys.exit(0)
