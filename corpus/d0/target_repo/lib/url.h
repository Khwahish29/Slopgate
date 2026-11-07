#ifndef URL_H
#define URL_H
#include <stddef.h>
int url_parse_host(const char *url, char *out, size_t outlen);
int url_legacy_unescape(char *s);
#endif
