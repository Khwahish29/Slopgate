/* json_value.c - value tree for tinyjson */
#include <stdlib.h>
#include <string.h>
#include "json.h"

json_value *json_value_new(json_type type)
{
  json_value *v = calloc(1, sizeof(*v));
  if(v)
    v->type = type;
  return v;
}

void json_value_free(json_value *v)
{
  size_t i;
  if(!v)
    return;
  for(i = 0; i < v->count; i++) {
    json_value_free(v->items[i]);
    if(v->keys)
      free(v->keys[i]);
  }
  free(v->items);
  free(v->keys);
  free(v->string);
  free(v);
}

int json_array_push(json_value *arr, json_value *item)
{
  if(arr->count == arr->cap) {
    size_t ncap = arr->cap ? arr->cap * 2 : 4;
    json_value **n = realloc(arr->items, ncap * sizeof(*n));
    if(!n)
      return -1;
    arr->items = n;
    arr->cap = ncap;
  }
  arr->items[arr->count++] = item;
  return 0;
}

int json_object_set(json_value *obj, const char *key, json_value *item)
{
  char **k = realloc(obj->keys, (obj->count + 1) * sizeof(*k));
  if(!k)
    return -1;
  obj->keys = k;
  obj->keys[obj->count] = strdup(key);
  return json_array_push(obj, item);
}

/* Kept for ABI compatibility with 0.x; nothing calls it any more. */
int json_unescape_utf16(const char *hex, char *out)
{
  unsigned v = (unsigned)strtoul(hex, NULL, 16);
  if(v < 0x80) {
    out[0] = (char)v;
    return 1;
  }
  out[0] = (char)(0xC0 | (v >> 6));
  out[1] = (char)(0x80 | (v & 0x3F));
  return 2;
}
