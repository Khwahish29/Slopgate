/* cfg.h - small INI-style configuration reader */
#ifndef CFG_H
#define CFG_H
#include <stddef.h>

#define CFG_MAX_LINE 512
#define CFG_MAX_KEY 64

typedef struct cfg_entry {
  char section[CFG_MAX_KEY];
  char key[CFG_MAX_KEY];
  char *value;
  struct cfg_entry *next;
} cfg_entry;

typedef struct {
  cfg_entry *head;
  char section[CFG_MAX_KEY];
  int lineno;
} cfg_t;

char *cfg_trim(char *s);
int cfg_read_line(const char **cursor, char *out, size_t outlen);
int cfg_unquote(char *s);

int cfg_parse_section(cfg_t *c, const char *line);
int cfg_parse_pair(cfg_t *c, char *line);
int cfg_load(cfg_t *c, const char *text);
int cfg_include_file(cfg_t *c, const char *path);

int cfg_set(cfg_t *c, const char *key, const char *value);
const char *cfg_get(const cfg_t *c, const char *section, const char *key);
char *cfg_expand_env(const char *value);
void cfg_free(cfg_t *c);

#endif
