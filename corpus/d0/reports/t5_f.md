# CWE-125 in url_legacy_unescape()

**Severity:** High
**CWE:** CWE-125
**Affected file:** lib/http_chunks.c
**Affected function:** url_legacy_unescape
**Affected line:** 26
**Version:** minihttp-1_0

## Summary

`url_legacy_unescape()` reads one element beyond the allocation. The defect is in the copy loop at lib/http_chunks.c:26, which trusts a length the caller never validates.

## Proof of concept

Drive url_legacy_unescape() with an oversized input.
