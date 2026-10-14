/* C99 long-double conversion conformance cross-check against native glibc. */
#include <stdio.h>
#include <math.h>
#include <fenv.h>
#include <limits.h>
#pragma STDC FENV_ACCESS ON
int main(void) {
  const int modes[]={FE_TONEAREST, FE_DOWNWARD, FE_UPWARD, FE_TOWARDZERO};
  const long double values[]={0.0L, -0.0L, 0.4L, -0.4L, 0.5L, -0.5L, 1.5L, -1.5L, 2.5L, -2.5L, 3.4L, -3.4L, 0x1p62L, 0x1p62L+0.5L, 0x1p62L+1.5L, -0x1p63L, 0x1p63L-1.0L, 0x1p63L, INFINITY, -INFINITY, NAN};
  for(unsigned m=0;m<sizeof modes/sizeof *modes;m++){
    if(fesetround(modes[m]))return 2;
    for(unsigned i=0;i<sizeof values/sizeof *values;i++){
      if(feclearexcept(FE_ALL_EXCEPT))return 3;
      volatile long double x=values[i];
      long long result=llrintl(x);
      int raised=fetestexcept(FE_INVALID|FE_INEXACT);
      printf("%u %u %lld invalid=%d inexact=%d\n",m,i,result,!!(raised&FE_INVALID),!!(raised&FE_INEXACT));
    }
  }
  return 0;
}
