# CWE-190 in chunk_read_size()

**Severity:** High
**CWE:** CWE-190
**Affected file:** src/main.c
**Affected function:** chunk_read_size
**Affected line:** 6
**Version:** minihttp-1_0

## Summary

`chunk_read_size()` computes a length that can wrap on 32-bit builds. The defect is in the copy loop at src/main.c:6, which trusts a length the caller never validates.

## Proof of concept

Drive chunk_read_size() with an oversized input.
