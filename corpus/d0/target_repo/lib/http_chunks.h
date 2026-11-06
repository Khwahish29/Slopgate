#ifndef HTTP_CHUNKS_H
#define HTTP_CHUNKS_H
#include <stddef.h>
struct chunk_state {
  char  *data;
  size_t cap;
  size_t used;
};
size_t chunk_read_size(const char *line, size_t len);
int    chunk_decode(struct chunk_state *st, const char *buf, size_t len);
#endif
