"""Checks the shipped, fully extracted model rather than synthetic geometry."""
import base64
import gzip
import json
import math
from pathlib import Path
import unittest


class MeshAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / "assets" / "dualsense.mesh.json.gz"
        with gzip.open(source, "rt", encoding="utf-8") as stream:
            cls.asset = json.load(stream)

    def test_complete_original_geometry_and_palette_groups(self):
        meshes = self.asset["meshes"]
        self.assertEqual(self.asset["version"], 1)
        self.assertEqual(len(meshes), 48)
        self.assertEqual(len({m["name"] for m in meshes}), 48)
        self.assertEqual(sum(len(m["vertices"]) // 3 for m in meshes), 62476)
        self.assertEqual(sum(len(m["indices"]) // 3 for m in meshes), 104240)
        self.assertEqual({m["slot"] for m in meshes},
                         {"shell", "line", "touch", "dpad", "bump", "btn", "glyph", "inset", "lightbar"})
        lights = {m["name"]: len(m["indices"]) // 3 for m in meshes if m["slot"] == "lightbar"}
        self.assertEqual(lights, {"Object_18": 2640, "Object_47": 428})

    def test_indices_normals_and_world_bounds(self):
        minimum, maximum = self.asset["bounds"]
        self.assertEqual((minimum[0], maximum[0]), (-1, 1))
        for mesh in self.asset["meshes"]:
            with self.subTest(mesh=mesh["name"]):
                vertices, normals, indices = (mesh[k] for k in ("vertices", "normals", "indices"))
                self.assertEqual(len(vertices) % 3, 0)
                self.assertEqual(len(indices) % 3, 0)
                self.assertEqual(len(vertices), len(normals))
                self.assertGreaterEqual(min(indices), 0)
                self.assertLess(max(indices), len(vertices) // 3)
                self.assertTrue(all(isinstance(i, int) for i in indices))
                for offset in range(0, len(vertices), 3):
                    self.assertAlmostEqual(math.hypot(*normals[offset:offset + 3]), 1, places=5)
                    for axis in range(3):
                        coordinate = vertices[offset + axis]
                        self.assertTrue(math.isfinite(coordinate))
                        self.assertGreaterEqual(coordinate, minimum[axis] - 1e-6)
                        self.assertLessEqual(coordinate, maximum[axis] + 1e-6)

    def test_textures_are_self_contained_rgba_and_have_uvs(self):
        textures = self.asset["textures"]
        self.assertEqual(len(textures), 2)
        for texture in textures:
            self.assertEqual(len(base64.b64decode(texture["rgba"], validate=True)),
                             texture["width"] * texture["height"] * 4)
        textured = [mesh for mesh in self.asset["meshes"] if "texture" in mesh]
        self.assertEqual(len(textured), 14)
        for mesh in textured:
            self.assertLess(mesh["texture"], len(textures))
            self.assertEqual(len(mesh["uvs"]) * 3, len(mesh["vertices"]) * 2)
            self.assertTrue(all(math.isfinite(uv) for uv in mesh["uvs"]))
        self.assertEqual(self.asset["attribution"]["author"], "Taohid Animation")
        self.assertEqual(self.asset["attribution"]["license"], "CC BY 4.0")


if __name__ == "__main__":
    unittest.main()
