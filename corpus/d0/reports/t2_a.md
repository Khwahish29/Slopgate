# Stack overflow in curl_easy_parse_header()

**Severity:** Critical
**CWE:** CWE-121
**Affected file:** lib/http_chunks.c
**Affected function:** curl_easy_parse_header
**Affected line:** 12
**Version:** minihttp-1_0

## Summary

The header helper `curl_easy_parse_header()` is reachable from `chunk_decode()` and writes past its destination.

## Proof of concept

Oversized header value.
