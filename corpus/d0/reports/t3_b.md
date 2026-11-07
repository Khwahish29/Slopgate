# Pointer arithmetic overflow in url_legacy_unescape()

**Severity:** Medium
**CWE:** CWE-823
**Affected file:** lib/url.c
**Affected function:** url_legacy_unescape
**Affected line:** 26
**Version:** minihttp-1_0

## Summary

The write pointer can pass the read pointer for malformed input.

## Proof of concept

Malformed escape sequence at end of string.
