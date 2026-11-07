#include <stdio.h>
#include "../lib/http_chunks.h"
#include "../lib/url.h"

int main(void)
{
  char host[64];
  struct chunk_state st = {0, 0, 0};
  if(url_parse_host("https://example.com/a", host, sizeof(host)) == 0)
    printf("host=%s\n", host);
  chunk_decode(&st, "10\r\nabcdefghijklmnop", 20);
  return 0;
}
