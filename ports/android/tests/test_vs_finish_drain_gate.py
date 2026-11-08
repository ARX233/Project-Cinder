#!/usr/bin/env python3
"""Real source extraction; fake UI, saves, clock and transport; not full app."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
source = (root / 'tests/test_vs_result_gate_host.py').read_text()
source = source.replace("root=Path(__file__).resolve().parents[1]", "root=Path(" + repr(str(root)) + ")")
assert source.count('int net_receive_drained(void){return drained;}') == 1
assert source.count('drained=current_valid=1;') == 1
cases = r"""
 setup(0);drained=0;ms=1000;result_frame(&r);empty();
 ms=2999;result_frame(&r);empty();assert(!aborts);
 ms=3000;result_frame(&r);empty();assert(aborts==1);
 setup(0);ms=1000;result_frame(&r);empty();assert(VR.local_finished);
 for(int i=1;i<=180;i++) {ms=1000+i*1000;drained=(i%2==0);result_frame(&r);empty();if(i<180)assert(!aborts);}
 assert(aborts==1&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);
 setup(0);ms=1000;result_frame(&r);empty();
 drained=0;ms=179000;result_frame(&r);empty();
 drained=1;VR.finished|=6;ms=180000;result_frame(&r);assert(!aborts);committed();
 result_frame(&r);committed();
 setup(0);drained=0;ms=1000;result_frame(&r);empty();
 drained=1;ms=2500;result_frame(&r);empty();assert(!aborts);
 drained=0;ms=3000;result_frame(&r);empty();ms=4999;result_frame(&r);empty();assert(!aborts);
 ms=5000;result_frame(&r);empty();assert(aborts==1);
 for(int d=0;d<=1;d++) for(int k=0;k<4;k++) {
   setup(0);drained=0;ms=1000;result_frame(&r);empty();
   drained=d;ms=k==0?NAN:k==1?INFINITY:k==2?-1:999;
   result_frame(&r);empty();assert(aborts==1);
 }
"""
assert source.count('late_abort(&r);') == 1
source = source.replace('late_abort(&r);', cases + '\n late_abort(&r);')
source = source.replace("'-std=gnu11','-Wall'", "'-fsanitize=undefined','-fno-sanitize-recover=all','-std=gnu11','-Wall'")
source = source.replace("'-o',str(exe)],check=True)", "'-o',str(exe)],check=True,timeout=30)")
source = source.replace('subprocess.run([str(exe)],check=True)', 'subprocess.run([str(exe)],check=True,timeout=10)')
exec(compile(source, str(root / 'tests/test_vs_result_gate_host.py'), 'exec'), {'__file__': str(root / 'tests/test_vs_result_gate_host.py'), '__name__': '__main__'})
