/* tlv.c - type-length-value records */
#include <stdio.h>
#include <string.h>
#include "pkt.h"

uint16_t tlv_read_u16(const uint8_t *p)
{
  return (uint16_t)((p[0] << 8) | p[1]);
}

int tlv_next(pkt_buf *b, pkt_tlv *t)
{
  const uint8_t *p;
  if(b->len - b->off < 4)
    return 0;
  p = b->data + b->off;
  t->type = tlv_read_u16(p);
  t->len = tlv_read_u16(p + 2);
  t->value = p + 4;
  b->off += 4 + t->len;
  return 1;
}

/* Debug helper. Not wired into any code path. */
void tlv_dump_hex(const pkt_tlv *t, char *out)
{
  uint16_t i;
  for(i = 0; i < t->len; i++)
    sprintf(out + i * 2, "%02x", t->value[i]);
}
