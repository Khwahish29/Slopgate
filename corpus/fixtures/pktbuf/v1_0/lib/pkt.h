/* pkt.h - packet buffer and TLV decoding */
#ifndef PKT_H
#define PKT_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
  uint8_t *data;
  size_t len;
  size_t cap;
  size_t off;
} pkt_buf;

typedef struct {
  uint16_t type;
  uint16_t len;
  const uint8_t *value;
} pkt_tlv;

typedef int (*pkt_handler)(pkt_buf *out, const pkt_tlv *t);

int buf_init(pkt_buf *b, size_t cap);
int buf_reserve(pkt_buf *b, size_t extra);
int buf_append(pkt_buf *b, const void *src, size_t n);
size_t buf_consume(pkt_buf *b, void *dst, size_t n);
void buf_free(pkt_buf *b);

uint16_t tlv_read_u16(const uint8_t *p);
int tlv_read_legacy_len(pkt_buf *b, pkt_tlv *t);
int tlv_next(pkt_buf *b, pkt_tlv *t);
void tlv_dump_hex(const pkt_tlv *t, char *out);

int dispatch_packet(pkt_buf *in, pkt_buf *out);

#endif
