# CWE-787 in hexval()

**Severity:** Critical
**CWE:** CWE-787
**Affected file:** src/main.c
**Affected function:** hexval
**Affected line:** 6
**Version:** minihttp-1_0

## Summary

`hexval()` writes past the end of its destination buffer. The defect is in the copy loop at src/main.c:6, which trusts a length the caller never validates.

## Proof of concept

Drive hexval() with an oversized input.
