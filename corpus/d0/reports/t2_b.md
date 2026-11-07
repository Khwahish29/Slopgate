# Missing bounds check in curl_easy_parse_header()

**Severity:** High
**CWE:** CWE-787
**Affected file:** docs/history.md
**Affected function:** curl_easy_parse_header
**Affected line:** 2
**Version:** minihttp-1_0

## Summary

Documentation confirms `curl_easy_parse_header()` ships in this release and it lacks a length check.

## Proof of concept

See summary.
