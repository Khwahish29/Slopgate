/* url.c - URL parsing helpers */
#include <string.h>
#include <stdlib.h>
#include "url.h"

int url_parse_host(const char *url, char *out, size_t outlen)
{
  const char *p, *end;
  size_t n;
  if(!url || !out)
    return -1;
  p = strstr(url, "://");
  p = p ? p + 3 : url;
  end = strchr(p, '/');
  n = end ? (size_t)(end - p) : strlen(p);
  if(n >= outlen)
    return -1;
  memcpy(out, p, n);
  out[n] = 0;
  return 0;
}

/* Dead code: retained for the 0.9 compatibility shim, never called. */
int url_legacy_unescape(char *s)
{
  char *r = s, *w = s;
  while(*r) {
    if(*r == '%')
      r += 3;
    *w++ = *r++;
  }
  *w = 0;
  return 0;
}
