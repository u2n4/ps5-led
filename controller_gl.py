"""Native OpenGL preview; model extraction is offline, all UI stays in Tk.

The lightbar pass writes the supplied RGB bytes without lighting, texturing,
blending, tone mapping or sRGB conversion. The shell uses smooth lighting.
"""

import base64
import ctypes
import gzip
import json
import math
import time
from collections import deque
from pathlib import Path

from OpenGL import GL
from pyopengltk import OpenGLFrame


def multiply(a, b):
    x, y, z, w = a
    X, Y, Z, W = b
    return (w*X+x*W+y*Z-z*Y, w*Y-x*Z+y*W+z*X,
            w*Z+x*Y-y*X+z*W, w*W-x*X-y*Y-z*Z)


def normalise(q):
    length = math.sqrt(sum(v*v for v in q)) or 1.0
    return tuple(v/length for v in q)


def conjugate(q):
    return (-q[0], -q[1], -q[2], q[3])


def axis_angle(axis, angle):
    s = math.sin(angle/2)
    return tuple(v*s for v in axis) + (math.cos(angle/2),)


def rotation_matrix(q):
    x, y, z, w = q
    return (1-2*(y*y+z*z), 2*(x*y+z*w), 2*(x*z-y*w), 0,
            2*(x*y-z*w), 1-2*(x*x+z*z), 2*(y*z+x*w), 0,
            2*(x*z+y*w), 2*(y*z-x*w), 1-2*(x*x+y*y), 0,
            0, 0, 0, 1)


class Orientation:
    """Port of the measured Y/Z-permuted filter from orientation.js."""
    def __init__(self):
        self.q = (0.0, 0.0, 0.0, 1.0)

    def update(self, gyro, accel, dt):
        if not 0 < dt <= 0.1:
            return self.q
        gx, gy, gz = (math.radians(gyro[i]) for i in (0, 2, 1))
        self.q = normalise(multiply(self.q, (gx*dt/2, gy*dt/2, gz*dt/2, 1)))
        magnitude = math.sqrt(sum(v*v for v in accel))
        if 0.85 < magnitude < 1.15:
            ax, ay, az = (accel[i]/magnitude for i in (0, 2, 1))
            pitch = math.atan2(-ax, math.hypot(ay, az))
            roll = math.atan2(ay, az)
            cp, sp = math.cos(pitch/2), math.sin(pitch/2)
            cr, sr = math.cos(roll/2), math.sin(roll/2)
            measured = normalise((sr*cp, cr*sp, -sr*sp, cr*cp))
            self.q = normalise(tuple(a*0.98+b*0.02 for a, b in zip(self.q, measured)))
        return self.q


class Orbit:
    """Only explicit mouse/stick input or enabled gyro can change rotation."""
    def __init__(self):
        self.rotation = (0.0, 0.0, 0.0, 1.0)
        self.gyro_enabled = False
        self.dragging = False
        self.filter = Orientation()
        self.last_timestamp = None
        self.last_sample_at = None
        self.last_tick = None

    def reset(self):
        self.rotation = (0.0, 0.0, 0.0, 1.0)
        self.filter = Orientation()
        self.last_timestamp = None

    def rotate(self, dx, dy):
        yaw = axis_angle((0, 1, 0), math.radians(dx))
        pitch = axis_angle((1, 0, 0), math.radians(dy))
        self.rotation = normalise(multiply(pitch, multiply(yaw, self.rotation)))

    @staticmethod
    def deadzone(value):
        value = max(-1.0, min(1.0, value))
        return math.copysign((abs(value)-0.18)/0.82, value) if abs(value) > 0.18 else 0.0

    def update(self, sample, now=None):
        now = time.monotonic() if now is None else now
        dt_tick = min(0.05, max(0, now-self.last_tick)) if self.last_tick is not None else 0
        self.last_tick = now
        if not sample.get("connected"):
            self.last_timestamp = None
            self.last_sample_at = None
            return False
        before = self.rotation
        timestamp = sample.get("sensor_timestamp")
        stick = sample.get("right_stick", (0, 0))
        sx, sy = (self.deadzone(float(v)) for v in stick)
        if timestamp is not None and timestamp != self.last_timestamp:
            previous_ts = self.last_timestamp
            self.last_timestamp = timestamp
            self.last_sample_at = now
            if previous_ts is not None:
                dt_sensor = ((timestamp-previous_ts) & 0xffffffff) / 3_000_000.0
                old_q = self.filter.q
                q = self.filter.update(sample.get("gyro", (0, 0, 0)),
                                       sample.get("accel", (0, 0, 0)), dt_sensor)
                # Consume gyro while dragging/orbiting, so release never jumps.
                if self.gyro_enabled and not self.dragging and not (sx or sy):
                    delta = multiply(q, conjugate(old_q))
                    self.rotation = normalise(multiply(delta, self.rotation))
        fresh = self.last_sample_at is not None and now-self.last_sample_at <= 0.25
        if fresh and not self.dragging and (sx or sy):
            self.rotate(sx*95*dt_tick, sy*95*dt_tick)
        return self.rotation != before


def load_mesh(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        model = json.load(stream)
    if model.get("version") != 1:
        raise ValueError("unsupported native mesh version")
    lightbars = set()
    for mesh in model["meshes"]:
        vertices, normals, indices = mesh["vertices"], mesh["normals"], mesh["indices"]
        if not vertices or len(vertices) % 3 or len(normals) != len(vertices):
            raise ValueError("invalid mesh vertex/normal data: " + mesh["name"])
        if not indices or len(indices) % 3 or min(indices) < 0 or max(indices) >= len(vertices)//3:
            raise ValueError("invalid mesh indices: " + mesh["name"])
        if mesh["name"] in ("Object_18", "Object_47"):
            lightbars.add(mesh["name"])
    if lightbars != {"Object_18", "Object_47"}:
        raise ValueError("model is missing a lightbar")
    return model


class ControllerGL(OpenGLFrame):
    def __init__(self, master, palette, led, on_failure, **kwargs):
        self.model = load_mesh(Path(__file__).resolve().parent / "assets" / "dualsense.mesh.json.gz")
        self.palette = palette
        self.led = tuple(led)
        self.on_failure = on_failure
        self.orbit = Orbit()
        self.meshes = []
        self.textures = []
        self._pending = None
        self._failed = False
        self._closed = False
        self._context = None
        self._dc = None
        self._drag_xy = None
        self.frame_times = deque(maxlen=300)
        self.frame_count = 0
        self.renderer_info = {}
        self.background = None
        self._background_revision = None
        self._bg = (11/255, 15/255, 20/255)
        super().__init__(master, **kwargs)
        self.configure(cursor="fleur")
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", self._reset_event)

    def tkCreateContext(self):
        # Own handles explicitly: pyopengltk 0.0.4 does not release its WGL/DC.
        from ctypes import wintypes
        from OpenGL import WGL
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetDC.argtypes = [wintypes.HWND]
        self._user32.GetDC.restype = wintypes.HDC
        self._user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self._user32.ReleaseDC.restype = ctypes.c_int
        self._dc = self._user32.GetDC(self.winfo_id())
        pfd = WGL.PIXELFORMATDESCRIPTOR()
        pfd.nSize = ctypes.sizeof(pfd)
        pfd.nVersion = 1
        pfd.dwFlags = 0x4 | 0x20 | 0x1  # window, OpenGL, double buffer
        pfd.iPixelType = 0
        pfd.cColorBits = 24
        pfd.cDepthBits = 24
        fmt = WGL.ChoosePixelFormat(self._dc, pfd)
        if not fmt or not WGL.SetPixelFormat(self._dc, fmt, pfd):
            raise RuntimeError("Windows could not create an OpenGL pixel format")
        self._context = WGL.wglCreateContext(self._dc)
        if not self._context or not WGL.wglMakeCurrent(self._dc, self._context):
            raise RuntimeError("Windows could not activate the OpenGL context")

    def tkMakeCurrent(self):
        from OpenGL import WGL
        if self._context:
            if not WGL.wglMakeCurrent(self._dc, self._context):
                raise RuntimeError("OpenGL context activation failed")

    def tkSwapBuffers(self):
        from OpenGL import WGL
        if not WGL.SwapBuffers(self._dc):
            raise RuntimeError("OpenGL buffer swap failed")

    def tkMap(self, event):
        if self._closed or self._failed:
            return
        try:
            if not self.context_created:
                self.tkCreateContext()
                self.initgl()
                self.context_created = True
            self.request_draw()
        except Exception as exc:
            self._fail(exc)

    def tkResize(self, event):
        self.width, self.height = max(1, event.width), max(1, event.height)
        self.request_draw()

    def tkExpose(self, event):
        self.request_draw()

    def initgl(self):
        self.renderer_info = {key: GL.glGetString(token).decode("utf-8", "replace")
                              for key, token in (("vendor", GL.GL_VENDOR),
                                                 ("renderer", GL.GL_RENDERER),
                                                 ("version", GL.GL_VERSION))}
        GL.glDisable(GL.GL_DITHER)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthFunc(GL.GL_LEQUAL)
        GL.glEnable(GL.GL_NORMALIZE)
        GL.glShadeModel(GL.GL_SMOOTH)
        GL.glLightModelfv(GL.GL_LIGHT_MODEL_AMBIENT, (0.32, 0.32, 0.32, 1))
        GL.glLightModeli(GL.GL_LIGHT_MODEL_TWO_SIDE, GL.GL_TRUE)
        GL.glEnable(GL.GL_LIGHT0)
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_DIFFUSE, (0.78, 0.78, 0.78, 1))
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_SPECULAR, (0.38, 0.38, 0.38, 1))
        GL.glEnable(GL.GL_LIGHT1)
        GL.glLightfv(GL.GL_LIGHT1, GL.GL_DIFFUSE, (0.18, 0.21, 0.28, 1))
        GL.glEnable(GL.GL_COLOR_MATERIAL)
        GL.glColorMaterial(GL.GL_FRONT_AND_BACK, GL.GL_AMBIENT_AND_DIFFUSE)
        GL.glMaterialfv(GL.GL_FRONT_AND_BACK, GL.GL_SPECULAR, (0.22, 0.22, 0.22, 1))
        GL.glMaterialf(GL.GL_FRONT_AND_BACK, GL.GL_SHININESS, 48)
        for texture in self.model.get("textures", []):
            texture_id = int(GL.glGenTextures(1))
            self.textures.append(texture_id)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture_id)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
            pixels = base64.b64decode(texture["rgba"])
            if len(pixels) != texture["width"]*texture["height"]*4:
                raise ValueError("invalid texture payload")
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, texture["width"],
                            texture["height"], 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, pixels)
        for mesh in self.model["meshes"]:
            # ctypes arrays retain storage and avoid a NumPy runtime dependency.
            vertices = (ctypes.c_float * len(mesh["vertices"]))(*mesh["vertices"])
            normals = (ctypes.c_float * len(mesh["normals"]))(*mesh["normals"])
            indices = (ctypes.c_uint * len(mesh["indices"]))(*mesh["indices"])
            uv = mesh.get("uvs", [])
            uvs = (ctypes.c_float * len(uv))(*uv) if uv else None
            self.meshes.append((mesh, vertices, normals, indices, uvs))
        # Release decoded JSON arrays once the render buffers own them.
        self.model = {"bounds": self.model.get("bounds")}

    def request_draw(self):
        if not self._closed and not self._failed and self._pending is None:
            self._pending = self.after_idle(self._display)

    def _display(self):
        self._pending = None
        if self._closed or self._failed or not self.context_created or not self.winfo_ismapped():
            return
        try:
            started = time.perf_counter()
            self.tkMakeCurrent()
            self.redraw()
            self.tkSwapBuffers()
            self.frame_times.append((time.perf_counter()-started)*1000)
            self.frame_count += 1
        except Exception as exc:
            self._fail(exc)

    def _fail(self, exc):
        if self._failed:
            return
        self._failed = True
        self.after_idle(lambda: self.on_failure(exc))

    def _background_pass(self, width, height):
        if not self.background:
            return
        GL.glDisable(GL.GL_LIGHTING)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_TEXTURE_2D)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        GL.glOrtho(0, width, height, 0, -1, 1)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        ox, oy = self.winfo_rootx(), self.winfo_rooty()
        GL.glBegin(GL.GL_LINES)
        for x1, y1, x2, y2, color in self.background.get("links", ()):
            GL.glColor3ub(*bytes.fromhex(color[1:]))
            GL.glVertex2f(x1-ox, y1-oy)
            GL.glVertex2f(x2-ox, y2-oy)
        GL.glEnd()
        for x, y, radius, color in self.background.get("points", ()):
            if -4 < x-ox < width+4 and -4 < y-oy < height+4:
                GL.glPointSize(max(1, radius*2))
                GL.glBegin(GL.GL_POINTS)
                GL.glColor3ub(*bytes.fromhex(color[1:]))
                GL.glVertex2f(x-ox, y-oy)
                GL.glEnd()
        GL.glEnable(GL.GL_DEPTH_TEST)

    def redraw(self):
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        GL.glViewport(0, 0, width, height)
        GL.glClearColor(*self._bg, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        self._background_pass(width, height)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        half = max(0.74, 1.12*height/width)
        GL.glOrtho(-half*width/height, half*width/height, -half, half, -8, 8)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_POSITION, (-2, 3, 5, 0))
        GL.glLightfv(GL.GL_LIGHT1, GL.GL_POSITION, (3, -1, -2, 0))
        GL.glMultMatrixf(rotation_matrix(self.orbit.rotation))
        GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
        GL.glEnableClientState(GL.GL_NORMAL_ARRAY)
        for mesh, vertices, normals, indices, uvs in self.meshes:
            lightbar = mesh["name"] in ("Object_18", "Object_47")
            if lightbar:
                GL.glDisable(GL.GL_LIGHTING)
                GL.glDisable(GL.GL_TEXTURE_2D)
                GL.glDisable(GL.GL_BLEND)
                GL.glColor3ub(*self.led)
            else:
                GL.glEnable(GL.GL_LIGHTING)
                GL.glColor3ub(*self.palette[mesh["slot"]])
                texture = mesh.get("texture")
                if uvs is not None and texture is not None:
                    GL.glEnable(GL.GL_TEXTURE_2D)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self.textures[texture])
                    GL.glEnableClientState(GL.GL_TEXTURE_COORD_ARRAY)
                    GL.glTexCoordPointer(2, GL.GL_FLOAT, 0, uvs)
                else:
                    GL.glDisable(GL.GL_TEXTURE_2D)
            GL.glVertexPointer(3, GL.GL_FLOAT, 0, vertices)
            GL.glNormalPointer(GL.GL_FLOAT, 0, normals)
            GL.glDrawElements(GL.GL_TRIANGLES, len(indices), GL.GL_UNSIGNED_INT, indices)
            GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)
        GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
        GL.glDisableClientState(GL.GL_NORMAL_ARRAY)
        GL.glDisable(GL.GL_TEXTURE_2D)
        GL.glDisable(GL.GL_LIGHTING)

    def set_scene(self, palette, led):
        if palette != self.palette or tuple(led) != self.led:
            self.palette, self.led = palette, tuple(led)
            self.request_draw()

    def update_inputs(self, sample, background=None):
        changed = self.orbit.update(sample)
        if background is not None:
            revision = background["revision"]
            changed = changed or revision != self._background_revision
            self._background_revision = revision
            self.background = background
        if changed:
            self.request_draw()

    def _press(self, event):
        self.orbit.dragging = True
        self._drag_xy = (event.x, event.y)
        self.grab_set()

    def _drag(self, event):
        if self._drag_xy is not None:
            x, y = self._drag_xy
            self.orbit.rotate((event.x-x)*0.45, (event.y-y)*0.45)
            self._drag_xy = (event.x, event.y)
            self.request_draw()

    def _release(self, event):
        self.orbit.dragging = False
        self._drag_xy = None
        if self.grab_current() == self:
            self.grab_release()

    def _reset_event(self, event=None):
        self.orbit.reset()
        self.request_draw()
        return "break"

    def destroy(self):
        if self._closed:
            return
        self._closed = True
        if self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None
        self._release(None)
        if self._context:
            from OpenGL import WGL
            self.tkMakeCurrent()
            if self.textures:
                GL.glDeleteTextures(self.textures)
            WGL.wglMakeCurrent(None, None)
            WGL.wglDeleteContext(self._context)
            self._context = None
        if self._dc:
            self._user32.ReleaseDC(self.winfo_id(), self._dc)
            self._dc = None
        super().destroy()
