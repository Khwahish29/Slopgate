# Missing length guard in chunk_decode()

**Severity:** High
**CWE:** CWE-120
**Affected file:** lib/http_chunks.c
**Affected function:** chunk_decode
**Affected line:** 48
**Version:** minihttp-1_0

## Summary

The memcpy in `chunk_decode()` is bounded by the attacker-declared size rather than the received size.

## Proof of concept

Truncated chunk body.
