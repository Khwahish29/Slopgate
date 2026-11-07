# Format string bug in chunk_log_error()

**Severity:** Medium
**CWE:** CWE-134
**Affected file:** lib/http_chunks.c
**Affected function:** chunk_log_error
**Affected line:** 60
**Version:** minihttp-1_0

## Summary

`chunk_log_error()` passes attacker data as the format argument.

## Proof of concept

Send a chunk header containing %n.
