/* json.h - public API of tinyjson */
#ifndef TINYJSON_H
#define TINYJSON_H
#include <stddef.h>

typedef enum {
  JSON_NULL, JSON_BOOL, JSON_NUMBER, JSON_STRING, JSON_ARRAY, JSON_OBJECT
} json_type;

typedef struct json_value {
  json_type type;
  double number;
  char *string;
  size_t len;
  struct json_value **items;
  char **keys;
  size_t count;
  size_t cap;
} json_value;

typedef struct {
  const char *p;
  const char *end;
  int depth;
} json_lexer;

const char *json_skip_ws(json_lexer *lx);
int json_lex_string(json_lexer *lx, char *out, size_t outlen);
int json_lex_number(json_lexer *lx, double *out);
int json_lex_comment(json_lexer *lx);

json_value *json_value_new(json_type type);
void json_value_free(json_value *v);
int json_array_push(json_value *arr, json_value *item);
int json_object_set(json_value *obj, const char *key, json_value *item);
int json_unescape_utf16(const char *hex, char *out);

json_value *json_parse(const char *text, size_t len);

#endif
