/* http.h - tiny HTTP/1.1 request reader */
#ifndef TINYHTTP_H
#define TINYHTTP_H
#include <stddef.h>

#define HTTP_OK 0
#define HTTP_BAD -1
#define HTTP_AGAIN 1
#define HTTP_MAX_HDRS 32

struct http_hdr {
  char name[64];
  char *value;
};

struct http_req {
  struct http_hdr hdrs[HTTP_MAX_HDRS];
  int nhdrs;
  char body[8192];
  size_t body_len;
};

int hdr_parse_line(struct http_req *req, const char *line, size_t len);
size_t chunk_read_size(const char *p, size_t len, size_t *size);
int chunk_decode(struct http_req *req, const char *buf, size_t len);
int req_feed(struct http_req *req, const char *buf, size_t len);

#endif
