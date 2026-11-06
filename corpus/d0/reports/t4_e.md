# Bad API contract in chunk_decode()

**Severity:** Medium
**CWE:** CWE-787
**Affected file:** lib/http_chunks.h
**Affected function:** chunk_decode
**Affected line:** 10
**Version:** minihttp-1_0

## Summary

The prototype for `chunk_decode()` takes a length the implementation ignores.

## Proof of concept

See summary.
