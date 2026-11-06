# Heap overflow in curl_easy_parse_header()

**Severity:** Critical
**CWE:** CWE-122
**Affected file:** lib/http_chunks.c
**Affected function:** curl_easy_parse_header
**Affected line:** 214
**Version:** minihttp-1_0

## Summary

`curl_easy_parse_header()` copies an attacker-controlled header into a fixed 256-byte stack buffer without bounds checking.

## Proof of concept

Return a header longer than 256 bytes.
