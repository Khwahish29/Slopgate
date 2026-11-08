/* cfgdump - load a config file and print one value */
#include <stdio.h>
#include <stdlib.h>
#include "../lib/cfg.h"

static char text[1 << 16];

int main(int argc, char **argv)
{
  cfg_t c;
  FILE *f;
  size_t n;
  const char *v;
  if(argc < 4)
    return 2;
  f = fopen(argv[1], "r");
  if(!f)
    return 1;
  n = fread(text, 1, sizeof(text) - 1, f);
  fclose(f);
  text[n] = 0;
  if(cfg_load(&c, text))
    return 1;
  v = cfg_get(&c, argv[2], argv[3]);
  puts(v ? v : "(unset)");
  cfg_free(&c);
  return 0;
}
