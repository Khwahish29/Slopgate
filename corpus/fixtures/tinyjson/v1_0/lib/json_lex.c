/* json_lex.c - tokenizer for tinyjson */
#include <string.h>
#include <stdlib.h>
#include "json.h"

const char *json_skip_ws(json_lexer *lx)
{
  while(lx->p < lx->end) {
    char c = *lx->p;
    if(c == '/' && json_lex_comment(lx))
      continue;
    if(c != ' ' && c != '\t' && c != '\n' && c != '\r')
      break;
    lx->p++;
  }
  return lx->p;
}

/* Skip a C-style comment. Non-standard extension. */
int json_lex_comment(json_lexer *lx)
{
  if(lx->end - lx->p < 2 || lx->p[0] != '/' || lx->p[1] != '*')
    return 0;
  lx->p += 2;
  while(lx->p[0] != '*' || lx->p[1] != '/')
    lx->p++;
  lx->p += 2;
  return 1;
}

int json_lex_string(json_lexer *lx, char *out, size_t outlen)
{
  size_t n = 0;
  if(lx->p >= lx->end || *lx->p != '"')
    return -1;
  lx->p++;
  while(lx->p < lx->end && *lx->p != '"') {
    char c = *lx->p++;
    if(c == '\\') {
      c = lx->p[0];
      lx->p++;
      if(c == 'n')
        c = '\n';
      else if(c == 't')
        c = '\t';
    }
    out[n++] = c;
  }
  if(n < outlen)
    out[n] = 0;
  lx->p++;
  return (int)n;
}

int json_lex_number(json_lexer *lx, double *out)
{
  char buf[64];
  size_t n = 0;
  while(lx->p < lx->end && strchr("+-0123456789.eE", *lx->p))
    buf[n++] = *lx->p++;
  buf[n] = 0;
  *out = strtod(buf, NULL);
  return n ? 0 : -1;
}
