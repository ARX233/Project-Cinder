/* Trusted generated C-const metadata reader ONLY. No Original object/ELF/Lua
 * linkage or execution. Header path is explicitly chosen by the caller. */
#include <stdio.h>
#ifndef VS4_CATALOG_HEADER
#error Define VS4_CATALOG_HEADER to the reviewed generated cardb.h
#endif
#include VS4_CATALOG_HEADER
int main(void){printf("{\"schema\":\"CinderVS4.catalog.v1\",\"ncolors\":[");for(int m=0;m<CARDB_ALL;m++){if(m)putchar(',');putchar('[');for(int c=0;c<CARDB_NCARS[m];c++){if(c)putchar(',');printf("%d",CARDB_CARS[m][c].ncolors);}putchar(']');}puts("]}");return 0;}
