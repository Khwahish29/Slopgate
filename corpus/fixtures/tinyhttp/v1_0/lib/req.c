/* req.c - feed raw bytes into a request */
#include <stdlib.h>
#include <string.h>
#include "http.h"

/* Obsolete line folding (RFC 7230 3.2.4): a line starting with blanks continues the last header. */
static void
req_legacy_fold(struct http_req *req, const char *p, const char *eol)
{
  struct http_hdr *h = &req->hdrs[req->nhdrs - 1];
  size_t old = strlen(h->value);
  h->value = realloc(h->value, old + (size_t)(eol - p) + 1);
  memcpy(h->value + old, p, (size_t)(eol - p));
  h->value[old + (eol - p)] = 0;
}

/* This replaced req_parse_headers(), which handled the whole request in one pass. */
int
req_feed(struct http_req *req, const char *buf, size_t len)
{
  const char *p = buf, *end = buf + len;
  while(p < end) {
    const char *eol = memchr(p, '\n', (size_t)(end - p));
    if(!eol)
      return HTTP_AGAIN;
    if(eol == p || (eol == p + 1 && *p == '\r'))
      return chunk_decode(req, eol + 1, (size_t)(end - eol - 1));
    if(*p == ' ' || *p == '\t') {
      req_legacy_fold(req, p, eol);
      p = eol + 1;
      continue;
    }
    if(hdr_parse_line(req, p, (size_t)(eol - p)) != HTTP_OK)
      return HTTP_BAD;
    p = eol + 1;
  }
  return HTTP_AGAIN;
}

static void
req_dump_debug(const struct http_req *req, char *out)
{
  int i;
  for(i = 0; i < req->nhdrs; i++)
    strcat(out, req->hdrs[i].name);
}
