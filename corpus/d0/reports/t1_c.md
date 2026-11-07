# Integer overflow in url_normalize_percent()

**Severity:** High
**CWE:** CWE-190
**Affected file:** lib/url.c
**Affected function:** url_normalize_percent
**Affected line:** 140
**Version:** minihttp-1_0

## Summary

`url_normalize_percent()` multiplies the escape count by 3 without an overflow guard.

## Proof of concept

Supply 2^30 escape sequences.
