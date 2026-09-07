# Attribution

## 3D model

**PS5 Controller** by **Taohid Animation**, licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

- Creator: https://sketchfab.com/taohidanimation
- Original model: https://sketchfab.com/3d-models/ps5-controller-b7bb9c5102a04cb0b1966c6d02bad7d6

The original model was meshopt-compressed with WebP textures in the previous
renderer. This application reuses all 104,240 original triangles, preserving
the scene node names and baking the original world transforms offline.
Geometry is centered and uniformly scaled to width 2, with +X right, +Y up,
and +Z facing the viewer. Vertex positions and normals are rounded to six
decimal places. Base-color WebP images are decoded to raw RGBA; normal and
metallic/roughness maps are not used by the native renderer. Materials are
assigned the application's existing shell palette slots, and the two named
lightbar meshes are colored with the successfully sent device RGB.

This is an independent recreation and is not an official Sony product.

## Rebuilding the packaged model

The application needs only the checked-in `assets/dualsense.mesh.json.gz`.
It does not load glTF or run an image decoder at runtime.

`tools/extract_model.mjs` takes the original GLB and an offline meshopt decoder
module as its first and second arguments. Its defaults point to the sibling
`dualled-pro` checkout's `web/assets/dualsense.glb` and
`web/vendor/three/meshopt_decoder.module.js`. Rebuilding needs Node.js and
Python with Pillow already installed; no dependency is installed by the script.
The extraction tool does not use three.js or launch a browser.

The meshopt decoder is an offline external build tool, used under its MIT
license: https://github.com/zeux/meshoptimizer/blob/master/LICENSE.md
