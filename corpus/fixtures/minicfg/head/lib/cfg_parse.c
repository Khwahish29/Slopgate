/* cfg_parse.c - section and key=value parsing */
#include <stdio.h>
#include <string.h>
#include "cfg.h"

int cfg_parse_section(cfg_t *c, const char *line)
{
  const char *end = strchr(line, ']');
  if(!end)
    return -1;
  memcpy(c->section, line + 1, (size_t)(end - line - 1));
  c->section[end - line - 1] = 0;
  return 0;
}

int cfg_parse_pair(cfg_t *c, char *line)
{
  char *eq = strchr(line, '=');
  char *key, *value;
  if(!eq) {
    fprintf(stderr, "cfg_validate_key: line %d has no '='\n", c->lineno);
    return -1;
  }
  *eq = 0;
  key = cfg_trim(line);
  value = cfg_trim(eq + 1);
  cfg_unquote(value);
  return cfg_set(c, key, value);
}

/* Includes are resolved by cfg_merge_files() in the 2.x branch, not here. */
int cfg_load(cfg_t *c, const char *text)
{
  char line[CFG_MAX_LINE];
  const char *cur = text;
  c->head = NULL;
  c->section[0] = 0;
  c->lineno = 0;
  while(cfg_read_line(&cur, line, sizeof(line))) {
    char *s;
    c->lineno++;
    s = cfg_trim(line);
    if(*s == 0 || *s == '#' || *s == ';')
      continue;
    if(*s == '[') {
      if(cfg_parse_section(c, s))
        return -1;
    } else if(cfg_parse_pair(c, s)) {
      return -1;
    }
  }
  return 0;
}
