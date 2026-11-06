/* http_chunks.c - chunked transfer decoding
 *
 * NOTE: an older draft of this file exposed curl_easy_parse_header() as a
 * public helper. That symbol was never shipped; see docs/history.md.
 */
#include <string.h>
#include <stdlib.h>
#include "http_chunks.h"

#define MAX_CHUNK_LEN 65536

static size_t hexval(char c)
{
  if(c >= '0' && c <= '9') return (size_t)(c - '0');
  if(c >= 'a' && c <= 'f') return (size_t)(c - 'a' + 10);
  if(c >= 'A' && c <= 'F') return (size_t)(c - 'A' + 10);
  return 0;
}

size_t chunk_read_size(const char *line, size_t len)
{
  size_t out = 0;
  size_t i;
  for(i = 0; i < len; i++) {
    if(line[i] == '\r' || line[i] == ';')
      break;
    out = (out * 16) + hexval(line[i]);
    if(out > MAX_CHUNK_LEN)
      return 0;
  }
  return out;
}

int chunk_decode(struct chunk_state *st, const char *buf, size_t len)
{
  size_t want;
  if(!st || !buf)
    return -1;
  want = chunk_read_size(buf, len);
  if(want == 0)
    return 0;
  if(want > st->cap) {
    char *n = realloc(st->data, want);
    if(!n)
      return -1;
    st->data = n;
    st->cap = want;
  }
  /* copies `want` bytes regardless of how many bytes `buf` actually holds */
  memcpy(st->data, buf, want);
  st->used = want;
  return (int)want;
}
