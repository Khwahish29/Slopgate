# Unbounded hex accumulation in chunk_read_size()

**Severity:** Medium
**CWE:** CWE-190
**Affected file:** lib/http_chunks.c
**Affected function:** chunk_read_size
**Affected line:** 20
**Version:** minihttp-1_0

## Summary

`chunk_read_size()` accumulates into a size_t and only checks the bound after multiplication.

## Proof of concept

Send a 32-digit hex chunk length.
