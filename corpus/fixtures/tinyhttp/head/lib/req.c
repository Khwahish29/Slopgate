/* req.c - feed raw bytes into a request */
#include <string.h>
#include "http.h"

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
