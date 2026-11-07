# Use-after-free in http_state_release()

**Severity:** High
**CWE:** CWE-416
**Affected file:** lib/http_chunks.c
**Affected function:** http_state_release
**Affected line:** 88
**Version:** minihttp-1_0

## Summary

`http_state_release()` frees the chunk state and then reads `st->used` from the freed allocation.

## Proof of concept

Trigger two consecutive releases.
