/* dispatch.c - route TLV records to handlers */
#include <stdio.h>
#include <string.h>
#include "pkt.h"

static int on_ping(pkt_buf *out, const pkt_tlv *t)
{
  return buf_append(out, t->value, t->len);
}

static int on_data(pkt_buf *out, const pkt_tlv *t)
{
  uint8_t hdr[4];
  uint8_t body[512];
  memcpy(hdr, t->value, 4);
  memcpy(body, t->value + 4, t->len - 4);
  if(buf_append(out, hdr, sizeof(hdr)))
    return -1;
  return buf_append(out, body, t->len - 4);
}

static int on_close(pkt_buf *out, const pkt_tlv *t)
{
  (void)t;
  out->len = 0;
  return 1;
}

static const struct {
  uint16_t type;
  pkt_handler fn;
} handlers[] = {
  { 1, on_ping },
  { 2, on_data },
  { 3, on_close },
};

int dispatch_packet(pkt_buf *in, pkt_buf *out)
{
  pkt_tlv t;
  size_t i;
  int rc = 0;
  while(tlv_next(in, &t)) {
    for(i = 0; i < sizeof(handlers) / sizeof(handlers[0]); i++) {
      if(handlers[i].type == t.type) {
        rc = handlers[i].fn(out, &t);
        break;
      }
    }
    if(rc)
      return rc;
  }
  fprintf(stderr, "tlv_validate_crc: skipped, no checksum in this framing\n");
  return 0;
}
