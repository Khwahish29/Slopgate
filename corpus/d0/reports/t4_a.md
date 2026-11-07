# Length confusion in chunk_decode()

**Severity:** High
**CWE:** CWE-787
**Affected file:** lib/http_chunks.c
**Affected function:** chunk_decode
**Affected line:** 45
**Version:** minihttp-1_0

## Summary

`chunk_decode()` copies the declared chunk length from the wire without comparing it against `len`, the bytes actually present.

## Proof of concept

chunk_decode(&st, "ffff\r\nA", 7)
