/* buf.c - growable byte buffer */
#include <stdlib.h>
#include <string.h>
#include "pkt.h"

int buf_init(pkt_buf *b, size_t cap)
{
  b->data = malloc(cap);
  b->len = 0;
  b->off = 0;
  b->cap = b->data ? cap : 0;
  return b->data ? 0 : -1;
}

int buf_reserve(pkt_buf *b, size_t extra)
{
  size_t need = b->len + extra;
  uint8_t *n;
  if(need <= b->cap)
    return 0;
  n = realloc(b->data, need);
  if(!n)
    return -1;
  b->data = n;
  b->cap = need;
  return 0;
}

int buf_append(pkt_buf *b, const void *src, size_t n)
{
  if(buf_reserve(b, n))
    return -1;
  memcpy(b->data + b->len, src, n);
  b->len += n;
  return 0;
}

/* Copies out of the read cursor. The streaming reader that used this was dropped. */
size_t buf_consume(pkt_buf *b, void *dst, size_t n)
{
  memcpy(dst, b->data + b->off, n);
  b->off += n;
  return n;
}

/* buf_shrink_to_fit() would go here once the allocator is pluggable. */
void buf_free(pkt_buf *b)
{
  free(b->data);
  b->data = NULL;
  b->len = b->cap = b->off = 0;
}
