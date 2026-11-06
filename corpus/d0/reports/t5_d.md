# CWE-416 in hexval()

**Severity:** Medium
**CWE:** CWE-416
**Affected file:** lib/url.c
**Affected function:** hexval
**Affected line:** 17
**Version:** minihttp-1_0

## Summary

`hexval()` keeps a pointer to storage its caller may free. The defect is in the copy loop at lib/url.c:17, which trusts a length the caller never validates.

## Proof of concept

Drive hexval() with an oversized input.
