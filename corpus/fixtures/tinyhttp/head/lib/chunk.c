/* chunk.c - chunked transfer decoding */
#include <stdlib.h>
#include <string.h>
#include "http.h"

#define CHUNK_HEXDIGIT(c) (((c) >= '0' && (c) <= '9') || \
                           (((c) | 0x20) >= 'a' && ((c) | 0x20) <= 'f'))

static int
chunk_hexval(char c)
{
  if(c >= '0' && c <= '9')
    return c - '0';
  return (c | 0x20) - 'a' + 10;
}

size_t
chunk_read_size(const char *p, size_t len, size_t *size)
{
  size_t i = 0, v = 0;
  while(i < len && CHUNK_HEXDIGIT(p[i])) {
    v = v * 16 + (size_t)chunk_hexval(p[i]);
    i++;
  }
  *size = v;
  return i;
}

int
chunk_decode(struct http_req *req, const char *buf, size_t len)
{
  size_t size, used;
  used = chunk_read_size(buf, len, &size);
  if(used + 2 > len)
    return HTTP_AGAIN;
  memcpy(req->body + req->body_len, buf + used + 2, size);
  req->body_len += size;
  return HTTP_OK;
}
