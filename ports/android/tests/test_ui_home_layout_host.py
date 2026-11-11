#!/usr/bin/env python3
"""Offline production home geometry, draw/hit and removed-info regressions.
Vulkan/GLES share these commands. Synthetic sprite extents only: not GPU/pixels.
"""
from pathlib import Path
import ast, hashlib, json, os, re, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
TEXT=(ROOT/'src/menu.c').read_text()
TMP=Path(os.environ.get('TMPDIR', '/tmp')).resolve()
OUT=Path(tempfile.mkdtemp(prefix='cinder-ui-home-',dir=TMP))
def fun(anchor):
    start=TEXT.index(anchor); opening=TEXT.index('{',start)
    masked=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),TEXT,flags=re.S)
    depth=0
    for i in range(opening,len(TEXT)):
        depth+=(masked[i]=='{')-(masked[i]=='}')
        if not depth:return TEXT[start:i+1]
    raise AssertionError(anchor)
tree=ast.parse((ROOT/'tests/test_ghost_menu_host.py').read_text())
prefix='#include "pre_race_tune.h"\n'+next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PREFIX' for t in n.targets))
prefix,part_count=re.subn(r'void anm_draw_part\(int id,const float src\[4\],const float dst\[4\],float a\)\{[^}]*\}', 'void anm_draw_part(int id,const float src[4],const float dst[4],float a){assert(src[0]>=0&&src[1]>=0&&src[2]>src[0]&&src[3]>src[1]);assert(src[2]<=anm_sprite_width(id)+.01f&&src[3]<=anm_sprite_height(id)+.01f);record(2,id,dst[0],dst[1],dst[2]-dst[0],dst[3]-dst[1],a);}',prefix)
assert part_count==1
prefix += r'''
#define TITLE_GLYPH7 114000
int title_glyph_index(unsigned codepoint){return (int)(codepoint % 1000);}
int anm_sprite_content_rect(int sprite,float r[4]){
 if(sprite!=2317)return 0;
 r[0]=10;r[1]=10;r[2]=200;r[3]=30;return 1;
}
void anm_draw_xy(int anim,int frame,float alpha,float dx,float dy,float sx,float sy,const anm_swap *sw,int n){
 assert(anim==ID.bottom&&frame==0&&dx==0&&sx==1&&sw==NULL&&n==0);
 record(8,anim,dx,dy+sy*398,640,sy*54,alpha);
}
'''
desc=TEXT[TEXT.index('#define GAME_SLOTS '):TEXT.index('static int game_slot(')]
source=prefix+'\n'+desc+'\n'+'\n'.join(fun(a) for a in (
 'static int game_slot(', 'static int game_rects(', 'static int game_hit(',
 'static void game_sprite(', 'static void game_picture(', 'static void game_mode_label(', 'static void game_mode_japanese(',
 'static void draw_game_modes(', 'static void draw_bottombar(', 'static void draw_footer_hint('))
source+=r'''
static void near(float x,float y){assert(fabsf(x-y)<.02f);}
static void check_draw(menu_state *m){
 menu_mode_rect rect[5];assert(game_rects(m,rect));calls=0;draw_game_modes(m,1);
 int icons=0,vs=0,picture=0,label=0,glyphs=0;
 menu_mode_rect detail=menu_mode_detail(edge640);
 near(detail.x+edge640,24);assert(detail.y>320&&detail.y+detail.h<MENU_FOOTER_TOP);
 for(int i=0;i<calls;i++){
  packet*p=&packets[i];
  if((p->kind==2&&(p->id==2825||p->id==2824||p->id==2826||p->id==2827))||p->kind==3){
   int k=p->kind==3?game_slot(MENU_GAME_VS):game_slot(p->id==2825?MENU_GAME_STORY:p->id==2824?MENU_GAME_TEN:p->id==2826?MENU_GAME_TA:MENU_GAME_GHOST);
   near(p->x,rect[k].x);near(p->y,rect[k].y);near(p->w,rect[k].w);near(p->h,rect[k].h);near(p->w,p->h);icons++;vs+=p->kind==3;
  }
  if(p->id>=3223&&p->id<=3226){
   assert(p->kind==2&&p->id==GAME_MODE[m->sel].picture);near(p->x,-edge640);near(p->y,84);near(p->w,640+2*edge640);near(p->y+p->h,MENU_FOOTER_TOP);picture++;
  }
  if(p->kind==2&&p->id>=2316&&p->id<=2319){
   assert(p->id==(GAME_MODE[m->sel].label?GAME_MODE[m->sel].label:2318));
   if(GAME_MODE[m->sel].label){
    near(p->x,detail.x);near(p->w,detail.w);
   }else{
    near(p->x,detail.x+(label==0?0:.6f*detail.w));
    near(p->w,(label==0?.6f:.4f)*detail.w);
   }
   near(p->y,detail.y);near(p->h,detail.h);label++;
  }
  if(p->kind==2&&p->id>=TITLE_GLYPH7){
   assert(p->x>detail.x&&p->x+p->w<detail.x+detail.w&&p->y>detail.y&&p->y+p->h<detail.y+detail.h);
   glyphs++;
  }
  assert(p->id!=108000&&p->id!=108001);
 }
 assert(icons==5&&vs==1&&picture==1&&label==(GAME_MODE[m->sel].label?1:2));
 assert(GAME_MODE[m->sel].label?glyphs==0:glyphs==22);
}
int main(void){
 assert(MENU_GAME_STORY==0&&MENU_GAME_TEN==1&&MENU_GAME_TA==2&&MENU_GAME_VS==3&&MENU_GAME_GHOST==4);
 const int order[5]={MENU_GAME_STORY,MENU_GAME_GHOST,MENU_GAME_TEN,MENU_GAME_TA,MENU_GAME_VS};
 for(int i=0;i<5;i++){assert(GAME_MODE[i].game==order[i]);assert(game_slot(order[i])==i);}
 assert(GAME_MODE[1].label==2319&&GAME_MODE[1].picture==GAME_MODE[4].picture);
 assert(!memcmp(GAME_MODE[1].picture_crop,GAME_MODE[4].picture_crop,sizeof GAME_MODE[1].picture_crop));
 calls=0;draw_bottombar(0,1);draw_footer_hint(2317,1);
 assert(calls==2&&packets[0].kind==8&&packets[1].kind==2);
 near(packets[0].y,MENU_FOOTER_TOP);near(packets[0].y+packets[0].h,480);
 assert(packets[0].h>54);
 near(packets[1].x+packets[1].w/2,320);near(packets[1].y+packets[1].h/2,MENU_FOOTER_CENTER);
 near(packets[1].h,20*1.22f);
 assert(packets[1].y>MENU_FOOTER_TOP&&packets[1].y+packets[1].h<480);
 const float edges[]={0,106.66667f,160,200,213.33333f,202.44898f,320};unsigned cases=0;
 for(unsigned e=0;e<sizeof edges/sizeof *edges;e++){edge640=edges[e];
  for(int sel=0;sel<5;sel++){
   menu_state m={0};m.screen=MENU_GAME;m.sel=sel;m.from=-1;
   menu_mode_rect rect[5];assert(game_rects(&m,rect));
   float fit=fminf(1.0f,(640.0f+2.0f*edge640)/748.0f);
   assert(rect[0].x>=-edge640&&rect[4].x+rect[4].w<=640.0f+edge640);
   for(int i=0;i<5;i++){
    near(rect[i].w,(i==sel?256:128)*fit);near(rect[i].w,rect[i].h);
    near(rect[i].y+rect[i].h*.5f,192);
   }
   if(sel==0&&fit==1){near(rect[0].x,-45);near(rect[1].x,206);near(rect[4].x,548);}
   for(int t=0;t<60;t++){m.t=t;check_draw(&m);cases++;}
   for(int t=0;t<10;t++){m.t=t;m.deciding=30-t;check_draw(&m);cases++;}m.deciding=0;
   for(int from=sel-1;from<=sel+1;from+=2){if(from<0||from>=5)continue;m.from=from;
    for(int tick=0;tick<=MENU_MODE_SLIDE;tick++){m.t=tick;assert(game_rects(&m,rect));check_draw(&m);cases++;
     for(int i=0;i<5;i++){m.tap_x=rect[i].x+rect[i].w/2;m.tap_y=rect[i].y+rect[i].h/2;assert(game_hit(&m)==i);if(i<4)assert(rect[i].x+rect[i].w*.92f<rect[i+1].x+rect[i+1].w*.08f);}
    }
   }
  }
  const float dims[][2]={{1024,512},{512,1024},{32,32},{4096,256},{256,4096}};
  for(unsigned i=0;i<sizeof dims/sizeof *dims;i++){
   float src[4];menu_mode_rect dst;assert(menu_mode_picture(dims[i][0],dims[i][1],edge640,src,&dst));
   assert(src[0]>=0&&src[1]>=0&&src[2]<=dims[i][0]+.01f&&src[3]<=dims[i][1]+.01f);near(dst.w/(src[2]-src[0]),dst.h/(src[3]-src[1]));
   near(dst.x,-edge640);near(dst.x+dst.w,640+edge640);
  }
 }
 float src[4];menu_mode_rect dst,r[5];assert(!menu_mode_picture(NAN,1,0,src,&dst)&&!menu_mode_picture(1,0,0,src,&dst));
 assert(!menu_mode_layout(-1,-1,0,0,r)&&!menu_mode_layout(4,0,0,0,r)&&!menu_mode_layout(5,-1,0,0,r));
 assert(menu_mode_hit(NULL,0,0)==-1&&menu_mode_hit(r,NAN,0)==-1);assert(menu_mode_edge(NAN)==0&&menu_mode_edge(-1)==0&&menu_mode_edge(1e30f)==4096);
 printf("PASS %u production home draw/hit frames, five modes with original scale and narrow viewport fit, swapped visual IDs, cover crop, left caption and footer geometry; no GPU claim\n",cases);return 0;
}
'''
c=OUT/'home.c';exe=OUT/'home';c.write_text(source)
command=['clang','-std=c11','-O1','-g','-fsanitize=undefined','-fno-sanitize-recover=all','-Wno-unused-function','-I',str(ROOT/'src'),str(c),'-lm','-o',str(exe)]
subprocess.run(command,check=True,timeout=90)
p=subprocess.run([str(exe)],check=True,text=True,capture_output=True,timeout=30);print(p.stdout,end='')
assert 'INFO_KEY_RECT' not in TEXT and 'static void draw_info(' not in TEXT and 'go(m, MENU_INFO)' not in TEXT
assert 'save_enter(m);' in TEXT[TEXT.index('if (m->screen == MENU_INFO)'):TEXT.index('if (m->screen == MENU_SAVE)',TEXT.index('if (m->screen == MENU_INFO)'))]
for name in ('menupack.py','original_convert/full_menu.py','original_convert/menu_recipe.py'):
    body=(ROOT/'tools'/name).read_text();assert 'INFO_PAGE' not in body and 'INFO_KEY' not in body and '_info_page' not in body
print('PASS removed SAVE DATA info key/page/routes and both resource-generation paths')
report={'status':'PASS','authority':'production draw/hit source with synthetic sprite extents, UBSan; NOT GPU','source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('src/menu.c','src/menu_mode_layout.h')},'command':command,'stdout':p.stdout,'out':str(OUT)}
(OUT/'result.json').write_text(json.dumps(report,indent=2)+'\n');print('Evidence:',OUT/'result.json')
