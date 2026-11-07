# CWE-125 in chunk_read_size()

**Severity:** High
**CWE:** CWE-125
**Affected file:** lib/url.c
**Affected function:** chunk_read_size
**Affected line:** 17
**Version:** minihttp-1_0

## Summary

`chunk_read_size()` reads one element beyond the allocation. The defect is in the copy loop at lib/url.c:17, which trusts a length the caller never validates.

## Proof of concept

Drive chunk_read_size() with an oversized input.
