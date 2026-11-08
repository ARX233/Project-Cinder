"""Host tests extract production HUD logic; no device or saves are accessed."""
import importlib.util
import pathlib
import re
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('finish_pack', ROOT/'tools/finish_pack.py')
pack = importlib.util.module_from_spec(spec); spec.loader.exec_module(pack)

class FinishTest(unittest.TestCase):
    def test_production_decision(self):
        text = (ROOT/'src/hud.c').read_text()
        fn = re.search(r'int hud_finish_result\(.*?\n\}', text, re.S).group()
        program = '''#include <math.h>\n#include <assert.h>\n#include "car.h"\n'''+fn+'''\nstatic int legacy(const car_race *r,int s,int n,int t,int v) { int behind; int m=hud_finish_result(r,s,n,0,t,v,0,&behind); return m<0 ? -1 : behind ? -2 : m; }
static int masked(const car_race *r,int n,unsigned mask) { int behind; int m=hud_finish_result(r,1,n,mask,0,0,0,&behind); return m<0 ? -1 : behind ? -2 : m; }
int main(void) {
          car_race r={0}; r.play_state=2; r.remain_valid=1; r.remain=600;
          assert(hud_finish_result(&r,0,0,0,0)==600);
          r.remain=600.01f; assert(hud_finish_result(&r,0,0,0,0)==-1);
          r.remain=700; r.story_on[0]=1; r.story_gap_valid[0]=1; r.story_gap[0]=-100;
          assert(hud_finish_result(&r,1,1,0,0)==-2);
          r.story_gap[0]=-99.99f; assert(hud_finish_result(&r,1,1,0,0)==-1);
          r.story_gap[0]=-1000; assert(hud_finish_result(&r,1,1,0,0)==-2);
          r.remain=599; r.story_gap[0]=0; assert(hud_finish_result(&r,1,1,0,0)==599);
          r.story_gap[0]=1; assert(hud_finish_result(&r,1,1,0,0)==599);
          r.story_on[1]=1; r.story_gap_valid[1]=1; r.story_gap[1]=-1; assert(hud_finish_result(&r,1,2,0,0)==-2);
          r.story_on[1]=0; assert(hud_finish_result(&r,1,2,0,0)==-2); /* hidden competitor remains ranked */
          r.story_gap_valid[1]=0; assert(hud_finish_result(&r,1,2,0,0)==-1); /* truly unavailable */
          assert(masked(&r,2,2)==599); /* non-ranking second NPC must not block */
          r.story_gap_valid[1]=1; r.story_gap[1]=NAN; assert(hud_finish_result(&r,1,2,0,0)==-1);
          assert(masked(&r,2,2)==599); /* excluded NPC's invalid data cannot block */
          assert(hud_finish_result(&r,0,0,1,0)==-1);
          r.ten_gap_valid=1; r.ten_gap=-1; assert(hud_finish_result(&r,0,0,1,0)==-2);
          r.ten_gap=0; assert(hud_finish_result(&r,0,0,1,0)==599);
          r.ten_gap=NAN; assert(hud_finish_result(&r,0,0,1,0)==-1);
          assert(hud_finish_result(&r,0,1,0,1)==-1);
          r.vs_fresh[0]=1; r.vs_gap[0]=0; assert(hud_finish_result(&r,0,1,0,1)==599);
          r.vs_gap[0]=-1; assert(hud_finish_result(&r,0,1,0,1)==-2);
          r.vs_fresh[1]=1; r.vs_gap[1]=-10; assert(hud_finish_result(&r,0,2,0,1)==-2);
          r.vs_fresh[1]=0; assert(hud_finish_result(&r,0,2,0,1)==-1);
          r.vs_fresh[1]=1; r.vs_gap[1]=INFINITY; assert(hud_finish_result(&r,0,2,0,1)==-1);
          r.remain=700; r.vs_gap[0]=-100; r.vs_gap[1]=2;
          assert(hud_finish_result(&r,0,2,0,1)==-2);
          r.vs_gap[0]=-99; assert(hud_finish_result(&r,0,2,0,1)==-1);
          r.remain=-1; assert(hud_finish_result(&r,0,0,0,0)==-1);
          r.remain=NAN; assert(hud_finish_result(&r,0,0,0,0)==-1);
          r.remain=INFINITY; assert(hud_finish_result(&r,0,0,0,0)==-1);
          r.remain=0; assert(hud_finish_result(&r,0,0,0,0)==0);
          r.remain_valid=0; assert(hud_finish_result(&r,0,0,0,0)==-1);
          r.remain_valid=1; for(int i=0;i<=10;i++) if(i!=2) {r.play_state=i; assert(hud_finish_result(&r,0,0,0,0)==-1);}
          return 0; }'''
        program = program.replace('hud_finish_result(&r,', 'legacy(&r,')
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/'test.c'; exe=pathlib.Path(d)/'test'; src.write_text(program)
            subprocess.run(['cc','-std=c99','-I',str(ROOT/'src'),str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_packet_freshness_lifecycle(self):
        text=(ROOT/'src/car.c').read_text()
        fns='\n'.join(re.search(p,text,re.S).group() for p in (
            r'int car_link_time_fresh\(.*?\n\}', r'void car_link_fresh\(.*?\n\}',
            r'int car_link_observation_fresh\(.*?\n\}'))
        program='''#include <math.h>\n#include <assert.h>\n#define CAR_LINK_MACHINES 4
static struct { double vs_received[4]; } P;
static double now; static double link_now(void) { return now; }
'''+fns+'''
int main(void) {
 now=100; assert(!car_link_observation_fresh(1,0)); car_link_fresh(1,1);
 assert(car_link_observation_fresh(1,100)); assert(!car_link_observation_fresh(2,100));
 now=101; assert(car_link_observation_fresh(1,100)); now=101.001; assert(!car_link_observation_fresh(1,100));
 now=102; car_link_fresh(1,1); assert(car_link_observation_fresh(1,102));
 assert(!car_link_observation_fresh(1,100));
 car_link_fresh(1,0); assert(!car_link_observation_fresh(1,102));
 car_link_fresh(-1,1); car_link_fresh(4,1); assert(!car_link_observation_fresh(4,102));
 assert(!car_link_time_fresh(1,2)); assert(!car_link_time_fresh(NAN,1));
 assert(!car_link_time_fresh(10,INFINITY)); return 0; }
'''
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/'fresh.c'; exe=pathlib.Path(d)/'fresh'; src.write_text(program)
            subprocess.run(['cc','-std=c99',str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_production_draw(self):
        text=(ROOT/'src/hud.c').read_text()
        decision=re.search(r'int hud_finish_result\(.*?\n\}',text,re.S).group()
        draw=re.search(r'static void draw_finish_remaining\(.*?\n\}',text,re.S).group()
        program='''#include <math.h>\n#include <assert.h>\n#include <string.h>\n#include "car.h"
typedef struct { int from,to; } anm_swap;
static int ta_story,story_n,story_sel=-1,story_series=-1,story_ranking_slots_valid=1,story_chara[3],ten_level=-1,vs_n,live=1,prompt,number,label,available=1,last_digits;
static struct { int bound; float gap_mm; } ghost_rival;
int car_link_observation_fresh(int pcb,double observed) { return live; }
int anm_find(const char *s) { if(!available)return -1; return strstr(s,"tonikaku")?3:strstr(s,"000m")?1:2; }
int anm_frames(int a) { return a==1?200:60; }
int anm_sprite(int s) { return available?s:-1; }
void anm_draw(int a,int f,float x) { assert(f==30); if(a==3)prompt++; else {assert(a==2);label++;} }
void anm_draw_ex(int a,int f,float x,float y,float z,const anm_swap *sw,int n) { assert(a==1 && f==150 && n==4); assert(sw[0].from==0x10fc && sw[1].from==0x10fb && sw[2].from==0x10fa && sw[3].to==0x272); last_digits=(sw[0].to-0x268)*100+(sw[1].to-0x268)*10+sw[2].to-0x268; number++; }
'''+decision+'\n'+draw+'''\nint main(void) {
 car_race r={0}; r.play_state=2; r.remain_valid=1; r.remain=600;
 draw_finish_remaining(&r); assert(number==1 && label==1 && !prompt && last_digits==600);
 vs_n=2; r.vs_fresh[0]=r.vs_fresh[1]=1; r.remain=700; r.vs_gap[0]=-100; r.vs_gap[1]=-101;
 draw_finish_remaining(&r); assert(prompt==1 && number==2 && last_digits==599);
 r.vs_gap[1]=0; draw_finish_remaining(&r); assert(prompt==2 && number==3 && last_digits==600);
 r.vs_gap[0]=-99; draw_finish_remaining(&r); assert(prompt==2 && number==3);
 r.remain=599; r.vs_gap[0]=1; draw_finish_remaining(&r); assert(label==2 && number==4 && last_digits==599);
 r.vs_gap[0]=-700; draw_finish_remaining(&r); assert(prompt==3 && number==5 && last_digits==0);
 r.vs_fresh[1]=0; draw_finish_remaining(&r); assert(number==5); r.vs_fresh[1]=1;
 live=0; draw_finish_remaining(&r); assert(number==5);
 live=1; available=0; draw_finish_remaining(&r); assert(number==5);
 available=1; r.play_state=8; draw_finish_remaining(&r); assert(number==5);
 vs_n=0; r.play_state=2; ta_story=1; story_n=3; r.remain=720;
 r.story_on[0]=r.story_on[1]=r.story_on[2]=1;
 r.story_gap_valid[0]=r.story_gap_valid[1]=r.story_gap_valid[2]=1;
 r.story_gap[0]=-120; r.story_gap[1]=-121; r.story_gap[2]=10;
 draw_finish_remaining(&r); assert(prompt==4 && number==6 && last_digits==599);
 r.story_on[1]=0; draw_finish_remaining(&r); assert(prompt==5 && number==7 && last_digits==599);
 r.story_gap_valid[1]=0; draw_finish_remaining(&r); assert(number==7);
 /* User's first episode: character 40 is non-ranking, even with a negative
  * or unavailable gap; active character 39 is over 2 km behind. */
 story_sel=0; story_series=25; story_n=2; story_chara[0]=39; story_chara[1]=40;
 r.remain=599.596f; r.story_gap[0]=2351.252f; r.story_gap_valid[0]=1;
 r.story_gap[1]=-979.434f; r.story_gap_valid[1]=0;
 story_ranking_slots_valid=0; draw_finish_remaining(&r); assert(number==7);
 story_ranking_slots_valid=1; draw_finish_remaining(&r); assert(label==3 && number==8 && last_digits==599);
 /* If the genuine opponent leads, show its 600m distance and warning. */
 r.remain=650; r.story_gap[0]=-50; draw_finish_remaining(&r);
 assert(prompt==6 && number==9 && last_digits==600);
 r.story_gap_valid[0]=0; draw_finish_remaining(&r); assert(number==9);
 r.story_gap_valid[0]=1;
 /* All eleven unconditional character IDs ignore even a missing gap. */
 { const int ids[]={40,95,124,165,168,183,185,196,205,207,212};
   story_sel=0; story_series=25; r.remain=599; r.story_gap[0]=1;
   for(unsigned i=0;i<sizeof ids/sizeof ids[0];++i) {
     story_chara[1]=ids[i]; draw_finish_remaining(&r);
     assert(label==4+(int)i && number==10+(int)i && last_digits==599);
   }
 }
 /* The original period-3 character exceptions map to series 62 only. */
 story_sel=34; story_series=62; story_n=3;
 story_chara[0]=101; story_chara[1]=102; story_chara[2]=103;
 r.remain=599; r.story_gap_valid[0]=r.story_gap_valid[1]=0;
 r.story_gap_valid[2]=1; r.story_gap[2]=10; draw_finish_remaining(&r);
 assert(label==15 && number==21 && last_digits==599);
 story_series=61; draw_finish_remaining(&r); assert(number==21);
 ta_story=0; ten_level=0; r.remain=720; r.ten_gap_valid=1; r.ten_gap=-120;
 draw_finish_remaining(&r); assert(prompt==7 && number==22 && last_digits==600);
 ta_story=1; ten_level=-1; story_ranking_slots_valid=0; ghost_rival.bound=1;
 ghost_rival.gap_mm=-120000.0f;
 draw_finish_remaining(&r); assert(prompt==8 && number==23 && last_digits==600);
 ghost_rival.gap_mm=1000.0f;
 draw_finish_remaining(&r); assert(number==23);
 r.remain=599.0f;
 draw_finish_remaining(&r); assert(label==16 && number==24 && last_digits==599);
 ghost_rival.gap_mm=NAN;
 draw_finish_remaining(&r); assert(number==24);
 return 0; }
'''
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/'draw.c'; exe=pathlib.Path(d)/'draw'; src.write_text(program)
            subprocess.run(['cc','-std=c99','-I',str(ROOT/'src'),str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_vs_engine_sampling(self):
        text=(ROOT/'src/car.c').read_text()
        block=re.search(r'  if \(P.vs_race\) \{\n    /\* yt::CSeq::Get2DInfoBattle.*?\n  \}',text,re.S).group()
        fresh=re.search(r'int car_link_time_fresh\(.*?\n\}',text,re.S).group()
        program='''#include <math.h>\n#include <stdint.h>\n#include <string.h>\n#include <assert.h>\n#include "car.h"
#define MACHINE_PTR 4
#define LX_RIVALS 16
static unsigned char mem[4096];
static uint32_t rd(uint32_t p) { uint32_t v; memcpy(&v,mem+p,4); return v; }
static float rf(uint32_t p) { float v; memcpy(&v,mem+p,4); return v; }
static void wd(uint32_t p,uint32_t v) { memcpy(mem+p,&v,4); }
static void wf(uint32_t p,float v) { memcpy(mem+p,&v,4); }
#define M32(p) rd(p)
#define M8(p) mem[p]
#define MF(p) rf(p)
static struct { int vs_race; car_link_car vs[3]; double vs_received[4]; } P;
static double now=100; static double link_now(void) { return now; }
'''+fresh+'''\nstatic void sample(car_race *r) {\n'''+block+'''\n}
int main(void) {
 car_race r={0}; P.vs_race=2; P.vs[0].pcb=3; P.vs[1].pcb=1;
 wd(MACHINE_PTR,100); wf(100+0x970,1000000);
 wd(LX_RIVALS,200); wd(LX_RIVALS+4,220);
 wd(200+0x240,300); wd(220+0x240,400);
 wf(300+0x30,1100000); wf(400+0x30,900000);
 mem[208]=mem[228]=1; sample(&r); assert(!r.vs_fresh[0]);
 P.vs_received[3]=100; P.vs_received[1]=100; sample(&r);
 assert(r.vs_fresh[0] && r.vs_fresh[1]); assert(r.vs_pcb[0]==3 && r.vs_pcb[1]==1);
 assert(r.vs_gap[0] < -99 && r.vs_gap[1] > 99 && r.vs_rank==1);
 mem[208]=0; sample(&r); assert(!r.vs_fresh[0]); mem[208]=1;
 now=101.1; sample(&r); assert(!r.vs_fresh[0] && !r.vs_fresh[1]);
 P.vs_received[3]=P.vs_received[1]=101.1; sample(&r); assert(r.vs_fresh[0]);
 wf(300+0x30,NAN); sample(&r); assert(!r.vs_fresh[0]);
 return 0; }
'''
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/'sampling.c'; exe=pathlib.Path(d)/'sampling'; src.write_text(program)
            subprocess.run(['cc','-std=c99','-I',str(ROOT/'src'),str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_wcp_validation_and_collision(self):
        sprite=struct.pack('<iHHI',123,1,1,0)+bytes(4)
        rec=pack.RECORD.pack(123,0,1,0,0,1,0,0,*([256]*4),*([0]*4))
        anim=struct.pack('<48sII',b'test',1,1)+struct.pack('<II',0,1)+rec
        data=struct.pack('<4sIII',b'WCP1',1,1,1)+sprite+anim
        ids,names,sprites,anims=pack.bank(data,True)
        self.assertEqual((ids,names,sprites,anims),({123},{'test'},[sprite],[anim]))
        with self.assertRaises(ValueError): pack.bank(data,True,{123})
        with self.assertRaises(ValueError): pack.bank(data[:-1],True)
        with self.assertRaises(ValueError): pack.bank(data,True,set(),{'test'})
        with self.assertRaises(ValueError): pack.bank(data+b'x',True)

    def test_art_and_draw_contract(self):
        s=(ROOT/'src/hud.c').read_text()
        self.assertIn('cons_g_last_tonikaku',pack.ANIMS)
        self.assertIn('"cons_g_last_tonikaku" : "cons_g_last_saigo"',s)
        self.assertIn('anm_frames(label) <= 30',s)
        self.assertIn('anm_frames(number) <= 150',s)
        self.assertIn('draw_finish_remaining(&car->race)',s)
        path=ROOT.parents[2]/'Fulldata/Wangan Midnight 3DX+[banwu]/Wangan Midnight 3DX+/data/anime/cons_g_last_tonikaku.anm'
        if path.exists():
            frames,records=pack.animation(path)
            self.assertGreater(len(frames),30)
            self.assertGreater(frames[30][1],0)

if __name__ == '__main__': unittest.main()
