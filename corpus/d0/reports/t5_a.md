# CWE-787 in chunk_decode()

**Severity:** Critical
**CWE:** CWE-787
**Affected file:** lib/url.c
**Affected function:** chunk_decode
**Affected line:** 17
**Version:** minihttp-1_0

## Summary

`chunk_decode()` writes past the end of its destination buffer. The defect is in the copy loop at lib/url.c:17, which trusts a length the caller never validates.

## Proof of concept

Drive chunk_decode() with an oversized input.
