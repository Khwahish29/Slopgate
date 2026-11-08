/* jsoncat - parse a JSON file and print its top-level type */
#include <stdio.h>
#include <stdlib.h>
#include "../lib/json.h"

static char buf[1 << 20];

int main(int argc, char **argv)
{
  FILE *f;
  size_t n;
  json_value *v;
  if(argc < 2)
    return 2;
  f = fopen(argv[1], "rb");
  if(!f)
    return 1;
  n = fread(buf, 1, sizeof(buf), f);
  fclose(f);
  v = json_parse(buf, n);
  if(!v) {
    fprintf(stderr, "parse error\n");
    return 1;
  }
  printf("type %d\n", (int)v->type);
  json_value_free(v);
  return 0;
}
