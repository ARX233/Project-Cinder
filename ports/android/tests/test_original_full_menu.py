import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'tools/original_convert/full_menu.py').is_file():
    ROOT=Path('/Volumes/MacSave/WMMT3 Phone/Re3DXPlus-github-sync/ports/android')
sys.path.insert(0,str(ROOT/'tools'))
from original_convert import full_menu as m
from original_convert.menu_support import MenuConversionError


def complete():
    return {'ANIMS':[(f'anim_{n}',None) for n in range(308)],'DEMO_ANIMS':list(range(57)),
            'STORYSEL_TEXTS':[0]*40,'STTUNE_TEXTS':[0]*326,'WEAR_TEXTS':[0]*41,
            'STEFF_TEXTS':[0]*52,'DEMO_TEXTS':[0]*221}


class FakeRenderer:
    def text(self,font,text):return Image.new('RGBA',(max(1,len(text)*8),16),(255,255,255,255))


class FullMenuTests(unittest.TestCase):
    def test_complete_namespace_counts_and_duplicates(self):
        m._complete_recipe(complete())
        for name in complete():
            recipe=complete();recipe[name].pop()
            with self.subTest(name=name),self.assertRaises(MenuConversionError):m._complete_recipe(recipe)
        recipe=complete();recipe['ANIMS'][1]=recipe['ANIMS'][0]
        with self.assertRaises(MenuConversionError):m._complete_recipe(recipe)

    def test_whole_menu_budget_covers_real_independent_proof(self):
        self.assertGreaterEqual(m.MAX_MENU_FRAMES,72939)
        self.assertGreaterEqual(m.MAX_MENU_RECORDS,547134)
        self.assertGreaterEqual(m.MAX_DECODED_PIXELS_BYTES,760149196)
        self.assertLessEqual(m.MAX_MENU_RECORDS,1000000)

    def test_explicit_runtime_placeholders_not_fake_images(self):
        self.assertEqual(m.EMPTY_SOURCE_SPRITES,{-1,0,1,2,3})
        with self.assertRaises(MenuConversionError):m.pack_full_menu(None,None,'menu.bin',{},scratch_parent='/unused')
        self.assertFalse(hasattr(m,'Ready'));self.assertFalse(hasattr(m,'activate'))

    def test_black_unblend_preserves_alpha_and_colour_semantics(self):
        im=Image.new('RGBA',(2,1));im.putdata([(0,0,0,255),(64,128,32,255)])
        actual=list(m.unblend_black(im).getdata())
        self.assertEqual(actual,[(0,0,0,0),(127,255,63,128)])
        self.assertEqual(list(im.getdata()),[(0,0,0,255),(64,128,32,255)])

    def test_port_artwork_uses_no_system_font_or_game_pixels(self):
        renderer=FakeRenderer()
        with patch('PIL.ImageFont.truetype',side_effect=AssertionError('System font access')):
            self.assertFalse(hasattr(m,'_info_key'))
            self.assertFalse(hasattr(m,'_info_page'))
            for n in range(3):
                self.assertEqual(m._vs_icon(renderer,n).size,(256,256))
                self.assertEqual(m._vs_line(renderer,n).size,(512,64))
            self.assertEqual(m.render_infinity().size,(128,72))

    def test_recipe_has_no_generated_support_or_runtime_execution(self):
        source=(ROOT/'tools/original_convert/menu_recipe.py').read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
                self.assertNotIn(node.func.id,('open','exec','eval','__import__'))
            self.assertFalse(isinstance(node,(ast.Import,ast.ImportFrom)))


if __name__=='__main__':unittest.main()
