/* pktd - read framed packets from stdin and echo handler output */
#include <stdio.h>
#include <unistd.h>
#include "../lib/pkt.h"

int main(void)
{
  pkt_buf in, out;
  uint8_t chunk[4096];
  ssize_t n;
  if(buf_init(&in, 4096) || buf_init(&out, 4096))
    return 1;
  while((n = read(0, chunk, sizeof(chunk))) > 0) {
    if(buf_append(&in, chunk, (size_t)n))
      break;
  }
  if(dispatch_packet(&in, &out) < 0)
    fprintf(stderr, "dispatch failed\n");
  fwrite(out.data, 1, out.len, stdout);
  buf_free(&in);
  buf_free(&out);
  return 0;
}
