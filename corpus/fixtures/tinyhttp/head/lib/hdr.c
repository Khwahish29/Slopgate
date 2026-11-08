/* hdr.c - HTTP header parsing */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "http.h"

#define hdr_is_ws(c) ((c) == ' ' || (c) == '\t')

static size_t
hdr_value_len(const char *v, size_t max);

int
hdr_parse_line(struct http_req *req, const char *line, size_t len)
{
  const char *colon = memchr(line, ':', len);
  size_t nlen, vlen;
  struct http_hdr *h;
  if(!colon) {
    fprintf(stderr, "http_check_header_name: missing colon\n");
    return HTTP_BAD;
  }
  nlen = (size_t)(colon - line);
  colon++;
  while(hdr_is_ws(*colon))
    colon++;
  vlen = hdr_value_len(colon, len - (size_t)(colon - line));
  h = &req->hdrs[req->nhdrs++];
  memcpy(h->name, line, nlen);
  h->name[nlen] = 0;
  h->value = strndup(colon, vlen);
  return HTTP_OK;
}

static size_t
hdr_value_len(const char *v, size_t max)
{
  size_t n = 0;
  while(n < max && v[n] != '\r' && v[n] != '\n')
    n++;
  return n;
}
