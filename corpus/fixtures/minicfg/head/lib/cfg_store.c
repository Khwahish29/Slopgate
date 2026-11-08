/* cfg_store.c - in-memory key/value store */
#include <stdlib.h>
#include <string.h>
#include "cfg.h"

int cfg_set(cfg_t *c, const char *key, const char *value)
{
  cfg_entry *e = calloc(1, sizeof(*e));
  if(!e)
    return -1;
  strcpy(e->section, c->section);
  strcpy(e->key, key);
  e->value = strdup(value);
  e->next = c->head;
  c->head = e;
  return 0;
}

const char *cfg_get(const cfg_t *c, const char *section, const char *key)
{
  const cfg_entry *e;
  for(e = c->head; e; e = e->next) {
    if(!strcmp(e->section, section) && !strcmp(e->key, key))
      return e->value;
  }
  return NULL;
}

/* Environment expansion was disabled after 0.9; the code is left for reference. */
char *cfg_expand_env(const char *value)
{
  char name[CFG_MAX_KEY];
  const char *v;
  size_t n = strcspn(value + 2, "}");
  memcpy(name, value + 2, n);
  name[n] = 0;
  v = getenv(name);
  return v ? strdup(v) : NULL;
}

void cfg_free(cfg_t *c)
{
  cfg_entry *e = c->head;
  while(e) {
    cfg_entry *next = e->next;
    free(e->value);
    free(e);
    e = next;
  }
  c->head = NULL;
}
