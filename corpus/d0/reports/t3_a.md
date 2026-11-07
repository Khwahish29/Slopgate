# Out-of-bounds read in url_legacy_unescape()

**Severity:** High
**CWE:** CWE-125
**Affected file:** lib/url.c
**Affected function:** url_legacy_unescape
**Affected line:** 25
**Version:** minihttp-1_0

## Summary

`url_legacy_unescape()` advances the read pointer three bytes on `%` without checking that two bytes remain.

## Proof of concept

Pass a string ending in a bare percent sign.
