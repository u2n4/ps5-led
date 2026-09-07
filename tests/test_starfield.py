"""Exercise background geometry without launching the app or opening HID."""
import ast
import math
from pathlib import Path
import random
import time
import types
import unittest


source = Path(__file__).resolve().parents[1] / 'dualled_pro.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Starfield')
scope = {'tk': types.SimpleNamespace(Canvas=object), 'math': math,
         'random': random, 'time': time,
         'rgb_to_hex': lambda rgb: '#%02x%02x%02x' % tuple(rgb)}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), scope)
Starfield = scope['Starfield']


class StarfieldTests(unittest.TestCase):
    def test_nearest_edge_includes_side_midpoints(self):
        for w,h in [(1000,600), (600,1000), (1,1)]:
            for x,y in [(0,h/2), (w,h/2), (w/2,0), (w/2,h), (0,0), (w,h)]:
                self.assertEqual(Starfield.edge_weight(x,y,w,h), 1)
        self.assertEqual(Starfield.edge_weight(500,300,1000,600), 0)
        weights=[Starfield.edge_weight(x,300,1000,600) for x in (0,20,60,100,120,300)]
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertEqual(weights[-1], 0)

    def test_cursor_force_only_local_and_near_edge(self):
        centre=[500,300,1,0,0]
        self.assertEqual(Starfield._advance(centre,(499,300),1000,600,.04), centre)
        edge=[20,300,1,0,0]
        self.assertEqual(Starfield._advance(edge,(500,300),1000,600,.04), edge)
        self.assertEqual(Starfield._advance(edge,(20,500),1000,600,.04), edge)
        moved=Starfield._advance(edge,(10,300),1000,600,.04)
        self.assertGreater(moved[0], edge[0])
        self.assertEqual(moved[1], edge[1])

    def test_snapshot_positions_share_screen_coordinate_system(self):
        field=object.__new__(Starfield)
        field.winfo_rootx=lambda: 120
        field.winfo_rooty=lambda: 250
        field._revision=4; field._background='#0b0f14'; field._size=(800,600)
        field._points=((10,20,2,'#ffffff'),)
        field._links=((10,20,30,40,'#111111'),)
        data=field.frame_data()
        self.assertEqual(data['points'], ((130,270,2,'#ffffff'),))
        self.assertEqual(data['links'], ((130,270,150,290,'#111111'),))
        self.assertEqual(data['origin'], (120,250))

    def test_idle_tick_does_no_drawing_and_resets_clock(self):
        field=object.__new__(Starfield)
        field.running=True; field._last_tick=0
        field.winfo_exists=lambda: True
        field._idle=lambda: True
        delays=[]; field._schedule=delays.append
        field._tick()
        self.assertEqual(delays, [500])
        self.assertIsNone(field._last_tick)

    def test_canvas_items_are_reused(self):
        field=object.__new__(Starfield)
        field.running=True; field._last_tick=None; field._size=(800,600)
        field.stars=[[10,10,1,0,0], [30,30,2,0,0]]
        field._point_items=[]; field._link_items=[]; field._revision=0
        field._background_rgb=(11,15,20)
        field.winfo_exists=lambda: True
        field._idle=lambda: False
        field.winfo_width=lambda: 800
        field.winfo_height=lambda: 600
        field.winfo_rootx=field.winfo_rooty=lambda: 0
        field.winfo_pointerx=field.winfo_pointery=lambda: 400
        created=[]
        def create(*args,**kwargs):
            created.append((args,kwargs))
            return len(created)
        field.create_oval=field.create_line=create
        field.coords=field.itemconfigure=lambda *args,**kwargs: None
        field.tag_lower=lambda *args: None
        field._schedule=lambda delay: None
        field._tick(); first=len(created)
        field._tick()
        self.assertEqual(first, 3)
        self.assertEqual(len(created), first)
        self.assertEqual(field._revision, 2)


if __name__ == '__main__':
    unittest.main()
