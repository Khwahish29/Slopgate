# Truncation in url_parse_host()

**Severity:** Low
**CWE:** CWE-197
**Affected file:** lib/url.c
**Affected function:** url_parse_host
**Affected line:** 10
**Version:** minihttp-1_0

## Summary

`url_parse_host()` rejects long hosts but callers may ignore the return value.

## Proof of concept

Supply a 300-character host.
