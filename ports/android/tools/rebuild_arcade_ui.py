#!/usr/bin/env python3
"""Rebuild explicit17-animation UI v4 from original data, no original/Lua execution.
Pinned prior WMN3 identity inventory avoids embedding/materializing the327MB base.
Recipe SHA is an explicit external input, never read from candidate APK or env.
Output receipt is observational until independently reviewed by the parent.
"""
import argparse,hashlib,json,re,os
from pathlib import Path
from original_convert.menu_support import OriginalSupport
from original_convert.ghost_ui import pack_ghost_ui,GHOST_UI_ANIMS,GHOST_UI_LEVEL_IMAGES
from arcade_ui_common import ANIMS,MAIN_SHA,BASE_MENU_SHA,inspect_pack
BASE_INVENTORY_SHA='bc07c4ef9a19a4fe1899524402a12bc523ab8b6c69c3997076e2395a50e12f5b'
def need(v,s):
 if not v:raise ValueError(s)
def build(source_root,base_inventory,expected_recipe_sha256,output_root):
 recipe=Path(__file__).parent/'original_convert/ghost_ui.py';recipe_sha=hashlib.sha256(recipe.read_bytes()).hexdigest();need(recipe_sha==expected_recipe_sha256,'recipe changed from explicit reviewed SHA');need(tuple(GHOST_UI_ANIMS)==tuple(ANIMS),'17-animation recipe contract')
 raw=base_inventory.read_bytes();need(hashlib.sha256(raw).hexdigest()==BASE_INVENTORY_SHA,'base inventory identity');base=json.loads(raw);need(base['menu_sha256']==BASE_MENU_SHA and len(base['sprites'])==10606 and len(base['animations'])==308,'base identity/count')
 root=source_root.resolve(strict=True);support=OriginalSupport.from_main(root/'main');output_root.mkdir(parents=True,exist_ok=False);reads={}
 def read(path,**kw):
  need(re.fullmatch(r'data/(?:anime/[A-Za-z0-9_]+\.anm|sprite/[A-Za-z0-9_]+\.(?:png|tga))',path),'unreviewed original resource namespace: '+path)
  p=(root/path).resolve(strict=True);need(root in p.parents and p.is_file(),'source path');b=p.read_bytes();need(len(b)<=kw.get('max_bytes',32*1024**2),'source byte budget');reads[path]={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()};return b
 r=pack_ghost_ui(read,support,list(map(int,base['sprites'])),base['animations'],output_root/'ghost-ui.bin');r.update(resource_path='ghost-ui.bin',base_menu_sha256=BASE_MENU_SHA,original_read_set=reads,sprite_count=len(r['sprite_ids']),animation_count=len(r['animations']),packer={'path':'source/tools/original_convert/ghost_ui.py','sha256':recipe_sha},reproducible_arguments={'base_inventory_sha256':BASE_INVENTORY_SHA,'main_sha256':MAIN_SHA,'output':'ghost-ui.bin'})
 need(set(sum((list(t) for t in GHOST_UI_LEVEL_IMAGES),[]))-{1} <= set(r['sprite_ids'])|set(r['referenced_base_sprite_ids']),'missing original level replacement sprites')
 data=(output_root/'ghost-ui.bin').read_bytes();stats=inspect_pack(data,r)
 # Observations only; builder approval must be explicitly selected after review.
 for name,obj in [('ghost-ui.provenance.json',r),('ghost-ui.source-output.json',{'files':[{'path':'ghost-ui.bin','size':r['bytes'],'sha256':r['observed_sha256']}]}),('source-proof.json',{'original_main_sha256':MAIN_SHA,'base_inventory_sha256':BASE_INVENTORY_SHA,'recipe_sha256':recipe_sha,'original_read_set':reads,'level_images':[list(x) for x in GHOST_UI_LEVEL_IMAGES],'publication_authority':False,'original_or_lua_executed':False,**stats})]:
  with (output_root/name).open('x') as f:json.dump(obj,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'recipe_sha256':recipe_sha,**stats}
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source-root','base-inventory','output-root'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--expected-recipe-sha256',required=True);a=p.parse_args();print(json.dumps(build(a.source_root,a.base_inventory,a.expected_recipe_sha256,a.output_root),sort_keys=True))
if __name__=='__main__':main()
