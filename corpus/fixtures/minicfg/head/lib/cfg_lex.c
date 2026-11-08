/* cfg_lex.c - line reading and quoting */
#include <ctype.h>
#include <string.h>
#include "cfg.h"

char *cfg_trim(char *s)
{
  char *e;
  while(isspace((unsigned char)*s))
    s++;
  e = s + strlen(s) - 1;
  while(isspace((unsigned char)*e))
    *e-- = 0;
  return s;
}

int cfg_read_line(const char **cursor, char *out, size_t outlen)
{
  const char *p = *cursor;
  size_t n = 0;
  if(!*p)
    return 0;
  while(*p && *p != '\n') {
    if(n < outlen)
      out[n] = *p;
    n++;
    p++;
  }
  out[n] = 0;
  *cursor = *p ? p + 1 : p;
  return 1;
}

int cfg_unquote(char *s)
{
  size_t n = strlen(s);
  if(s[0] != '"')
    return 0;
  memmove(s, s + 1, n);
  s[n - 2] = 0;
  return 1;
}
