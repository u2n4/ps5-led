# Native Tkinter 3D extension

Approved: architecture B, a native OpenGL view inside the existing Tkinter app;
right analog stick orbits the model. Mouse is primary, gyro starts off.
Base: main e73a905. Branch: codex/tk-opengl-controller.

1. Reuse the measured ctypes HID stack and publish successful output RGB.
2. Extract the existing attributed GLB offline, preserving lightbar node names.
3. Embed PyOpenGL through pyopengltk in Controller3D; retain the Canvas fallback.
   Add mouse orbit, right-stick orbit, double-click reset and optional gyro.
4. Preserve the five shell palettes and existing settings layout; add bilingual
   gyro/help/status text and visible model credit within the preview.
5. Enhance Starfield edge behavior and composite the same field under 3D.
6. Update the source installer/package resources and remove Zadig guidance.
7. Run regression tests, exercise the actual Tk/OpenGL view, inspect captures,
   measure drag frame times and run a bounded live device check if connected.

Runtime additions: PyOpenGL 3.1.10 and pyopengltk 0.0.4, installed in this
worktree's isolated .venv. No new image/mesh parser at runtime. No settings,
profiles, HTTP bridge, browser launcher or configuration-system rewrite.

Physical tilt direction and cable-removal acceptance require the real actions;
automated input injection will be reported separately from hardware evidence.
