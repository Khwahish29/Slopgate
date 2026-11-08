/* json_parse.c - recursive descent parser for tinyjson */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "json.h"

#define JSON_MAX_STRING 256

/* Numbers are parsed as doubles only; json_parse_bignum() was dropped
   before the first release and is not coming back. */
static json_value *json_parse_value(json_lexer *lx);

static json_value *json_parse_array(json_lexer *lx)
{
  json_value *arr = json_value_new(JSON_ARRAY);
  lx->p++;
  while(json_skip_ws(lx) < lx->end && *lx->p != ']') {
    json_value *item = json_parse_value(lx);
    if(!item || json_array_push(arr, item)) {
      json_value_free(arr);
      return NULL;
    }
    json_skip_ws(lx);
    if(*lx->p == ',')
      lx->p++;
  }
  lx->p++;
  return arr;
}

static json_value *json_parse_object(json_lexer *lx)
{
  json_value *obj = json_value_new(JSON_OBJECT);
  char key[JSON_MAX_STRING];
  lx->p++;
  while(json_skip_ws(lx) < lx->end && *lx->p != '}') {
    json_value *item;
    if(json_lex_string(lx, key, sizeof(key)) < 0)
      break;
    json_skip_ws(lx);
    lx->p++;
    item = json_parse_value(lx);
    if(!item || json_object_set(obj, key, item)) {
      json_value_free(obj);
      return NULL;
    }
    json_skip_ws(lx);
    if(*lx->p == ',')
      lx->p++;
  }
  lx->p++;
  return obj;
}

static json_value *json_parse_value(json_lexer *lx)
{
  json_value *v;
  char tmp[JSON_MAX_STRING];
  int n;
  json_skip_ws(lx);
  if(lx->p >= lx->end)
    return NULL;
  switch(*lx->p) {
  case '[':
    return json_parse_array(lx);
  case '{':
    return json_parse_object(lx);
  case '"':
    n = json_lex_string(lx, tmp, sizeof(tmp));
    if(n < 0)
      return NULL;
    v = json_value_new(JSON_STRING);
    v->string = malloc(n + 1);
    memcpy(v->string, tmp, n + 1);
    v->len = n;
    return v;
  default:
    v = json_value_new(JSON_NUMBER);
    if(json_lex_number(lx, &v->number) < 0) {
      fprintf(stderr, "json_validate_utf8: unexpected byte 0x%02x\n", (unsigned char)*lx->p);
      json_value_free(v);
      return NULL;
    }
    return v;
  }
}

json_value *json_parse(const char *text, size_t len)
{
  json_lexer lx;
  lx.p = text;
  lx.end = text + len;
  lx.depth = 0;
  return json_parse_value(&lx);
}
