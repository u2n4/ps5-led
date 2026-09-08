# Build from this checkout: python -m PyInstaller --noconfirm PS5-LED.spec
#
# This file is the build recipe and is TRACKED on purpose. PyInstaller normally
# generates specs, which is why *.spec is gitignored -- but this one is
# hand-written and load-bearing: it names the mesh, the OpenGL hidden imports
# and the hook that make the single-file build work. An untracked copy already
# drifted once, leaving a spec on the default branch that still collected
# pydualsense, a package this app no longer uses.
from pathlib import Path

root = Path(SPECPATH)
app = Analysis(
    [str(root / 'dualled_pro.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'assets' / 'dualsense.mesh.json.gz'), 'assets'),
           (str(root / 'assets' / 'dualsense-svgrepo.svg'), 'assets'),
           (str(root / 'assets' / 'app.ico'), 'assets'),
           (str(root / 'ATTRIBUTION.md'), '.')],
    # PyOpenGL loads its platform and array back-ends by name at runtime, so
    # static analysis cannot see them.
    hiddenimports=['OpenGL.platform.win32', 'OpenGL.arrays.ctypesarrays',
                   'OpenGL.arrays.lists', 'OpenGL.arrays.numbers',
                   'OpenGL.arrays.strings', 'pyopengltk.win32'],
    hookspath=[str(root / 'tools' / 'pyinstaller-hooks')], runtime_hooks=[],
    # Nothing here talks to the network, hashes anything, or touches win32
    # outside ctypes. Excluding these keeps OpenSSL (5.0 MB) and pywin32 out of
    # a build whose whole point is being one small file.
    excludes=['numpy', 'OpenGL_accelerate', 'clr', 'pythonnet', 'clr_loader',
              'ssl', '_ssl', 'hashlib', '_hashlib',
              'win32api', 'win32event', 'win32com', 'pywintypes', 'pythoncom',
              'winerror', 'win32clipboard', 'win32gui',
              'unittest', 'pydoc', 'doctest', 'test', 'pdb',
              'xmlrpc', 'sqlite3', 'asyncio', 'email', 'http', 'html',
              'urllib', 'ftplib', 'smtplib', 'socketserver', 'bz2', 'lzma',
              'curses'],
    noarchive=False,
)
pyz = PYZ(app.pure)
exe = EXE(pyz, app.scripts, app.binaries, app.datas, [],
          name='PS5-LED', debug=False, strip=False, upx=False,
          console=False, icon=str(root / 'assets' / 'app.ico'))
