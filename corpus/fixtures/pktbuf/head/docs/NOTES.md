# pktbuf notes

- 1.1 dropped the one-byte legacy framing (tlv_read_legacy_len).
- pkt_set_mtu() is planned for 1.2 so callers can cap record sizes.
