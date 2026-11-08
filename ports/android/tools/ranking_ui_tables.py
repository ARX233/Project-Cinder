#!/usr/bin/env python3
"""Generate private TA presentation metadata from pinned original bytes, not game execution.

No original image/font payloads are emitted. Existing title glyph IDs are reused.
The table source is explicit; output directory must be absent. No private paths.
"""
import argparse, importlib, json, sys
from pathlib import Path
from ranking_ui_v5 import MAIN_SHA, read_regular, sha, require, write_new, json_bytes

def build(source_root, tools_root, output_directory):
 tools=Path(tools_root).resolve(strict=True);sys.path.insert(0,str(tools))
 support_mod=importlib.import_module('original_convert.menu_support')
 model_mod=importlib.import_module('original_convert.menu_car_data')
 car_mod=importlib.import_module('original_convert.car_tables')
 main=read_regular(Path(source_root)/'main',32*1024*1024);require(sha(main)==MAIN_SHA,'main identity')
 s=support_mod.OriginalSupport(main);models=model_mod.decode_car_model_data(s.elf);data=car_mod._decode_main(s.elf)
 modelrows=[]
 for i,row in enumerate(models):
  rawcar=car_mod._model_car(data['model_ranges'],i,True)
  modelrows.append([row[11],model_mod._horsepower(s.elf,rawcar)])
 classes=[list(s.ints(0x93f2300+12*i,3)) for i in range(47)]
 handling=list(s.ints(0x93f1ee8,5));require(handling==[3145,2719,2718,2720,3146],'handling table')
 chars=s.title_chars();cindex={c:i for i,c in enumerate(chars)}
 names=s.name_chars();require(len(names)==256,'original name table')
 # Native GetTitleString0x858dcb4 scans declared ID at+16, FIRST match.
 # Row5149 declares5150 as well:5149 unmapped,5150 must select row5149.
 title_lookup={};declared_ids=[]
 for row in range(5200):
  at=0x9745580+28*row;identity=s.u32(at+16)
  declared_ids.append(identity)
  title_lookup.setdefault(identity,(row,s.wstr(s.u32(at+20),limit=128)))
 title_at=[];title_len=[];glyphs=[];breaks=[]
 for i in range(5200):
  text=title_lookup.get(i,(-1,''))[1]
  split=text.find('/');breaks.append(split)
  title_at.append(len(glyphs));title_len.append(len(text))
  for k,c in enumerate(text):glyphs.append(65535 if k==split else cindex[c])
 require(len(chars)==1573 and len(models)==247,'finite table counts')
 lines=['/* Private source-derived TA presentation tables; regenerate, do not hand edit. */',
        '/* main SHA256 '+MAIN_SHA+'; native get2 splits first U+002F only. */',
        '#ifndef CINDER_TA_RANK_ASSETS_PRIVATE_H','#define CINDER_TA_RANK_ASSETS_PRIVATE_H',
        '#include <stdint.h>',
        'static const uint16_t TA_UI_MODEL[247][2] = {']
 lines += ['  {%d,%d},'%tuple(row) for row in modelrows];lines += ['};','static const uint16_t TA_UI_CLASS[47][3] = {']
 lines += ['  {%d,%d,%d},'%tuple(row) for row in classes];lines += ['};']
 def array(ctype,name,values):
  lines.append('static const '+ctype+' '+name+'['+str(len(values))+'] = {')
  for k in range(0,len(values),16):lines.append('  '+','.join(map(str,values[k:k+16]))+',')
  lines.append('};')
 array('uint16_t','TA_UI_HANDLING',handling)
 array('uint16_t','TA_UI_NAME_WCHAR',[ord(c) for c in names])
 array('uint16_t','TA_UI_TITLE_WCHAR',[ord(c) for c in chars])
 array('uint32_t','TA_UI_TITLE_AT',title_at)
 array('uint16_t','TA_UI_TITLE_LEN',title_len)
 array('uint16_t','TA_UI_TITLE_GLYPHS',glyphs)
 lines += ['#endif',''];header='\n'.join(lines).encode()
 proof={'schema':'ta-ui-private-static-tables-v1','main_sha256':MAIN_SHA,'models':247,'classes':47,
        'handling_ids':handling,'name_entries':256,'title_entries':5200,'title_glyphs':1573,
        'title_split_wchar':s.u32(0x9332970),'title_linebreaks':breaks,
        'title_lookup':'first matching declared ID at native table row+16, not row index',
        'missing_title_ids':sorted(set(range(5200))-set(declared_ids)),
        'duplicate_title_ids':sorted(k for k in set(declared_ids) if declared_ids.count(k)>1),
        'title_id5150_selected_row':title_lookup[5150][0],
        'title_strings_containing_slash':sum(k>=0 for k in breaks),
        'header':{'path':'ta_rank_assets_private.h','bytes':len(header),'sha256':sha(header)},
        'authority':'Static data + bounded get2 assembly; no original or Lua execution; not new art/fonts.'}
 out=Path(output_directory);require(out.parent.is_dir() and not out.exists(),'new output directory required');out.mkdir()
 write_new(out/'ta_rank_assets_private.h',header);write_new(out/'ta-rank-assets-proof.json',json_bytes(proof));return proof['header']

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source-root','tools-root','output-directory'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();print(json.dumps(build(a.source_root,a.tools_root,a.output_directory),sort_keys=True))
if __name__=='__main__':main()
