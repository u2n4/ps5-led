# Published executable verification

Tested on 2026-09-08 using the asset downloaded from release `v3.0.0`.

- File: `PS5-LED.exe`, 11,068,554 bytes (10.56 MiB).
- SHA256: `8a757fdd4e1b59cf8270026011470824658a2168fb43cc1ca5299de7e5c0e2c2`.
- Downloaded checksum matched. This is the actual published file, not the
  older executable left in the local build directory.
- Windows Sandbox: Windows 11 Enterprise, no Python, networking disabled.
  App remained running; the screenshot shows the rendered 3D controller.
  See `sandbox-result/report.txt` and `sandbox-result/sandbox-screen.png`.
- On the host, the same executable ran with fresh AppData and Python removed
  from PATH. Its log reported `controller connected: DualSense Wireless
  Controller over usb`. This is connection evidence, not an optical LED test.
- Archive inspection found all six `ps5led` modules, the mesh, Python 3.13,
  Tcl/Tk, VC runtime DLLs, 219 OpenGL modules and five pyopengltk modules.
  NumPy, win32com and OpenSSL were absent.
- Source regression suite: 22 tests and 48 subtests passed. Ruff's
  E9/F63/F7/F82 checks passed.

No external Python installation or pip packages are required by this EXE.
PyInstaller extracts its bundled runtime into a temporary directory when
launched; distributing that directory or any Python source files is unnecessary.
Windows and its standard controller/graphics drivers are still required.

The combination of a physical controller and a fresh Windows installation
was not tested: Sandbox does not expose the host's USB/HID devices. The host
connection and clean-system rendering were separate tests. These results do
not guarantee every controller, Bluetooth adapter or graphics driver.
