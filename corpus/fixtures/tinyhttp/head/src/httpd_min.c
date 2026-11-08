/* httpd_min - feed stdin through the request parser */
#include <stdio.h>
#include <unistd.h>
#include "../lib/http.h"

static struct http_req req;

int
main(void)
{
  char buf[16384];
  ssize_t n = read(0, buf, sizeof(buf));
  if(n <= 0)
    return 1;
  return req_feed(&req, buf, (size_t)n) == HTTP_BAD;
}
