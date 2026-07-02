# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-07-02

### Changed
- **True zero-cost while gaming**: rendering now also pauses when the app loses input focus
  (fullscreen game over the window), not just when minimized — starfield, controller preview,
  and battery drawing all sleep; the engine keeps driving the real lightbar.
- Engine hardening: unknown mode from a hand-edited config can no longer busy-spin a CPU core;
  Manual keep-alive relaxed to 0.25s; Sequence skips duplicate HID sends.
- Config writes throttled to ≤1/sec during picker/slider drags (was ~100 writes/sec).
- Language switch polish: modern dark style for the language selector, shell-color list and
  status line now switch language correctly, profile load syncs the mode display.
- PS5-only view: PS4 hardware still fully controlled, drawing is always the DualSense render.

[2.3.0]: https://github.com/u2n4/ps5-led/releases/tag/v2.3.0

## [2.2.0] - 2026-07-02

### Changed
- **App renamed to "PS5 LED"** (window title, tray, shortcut, EXE, repository).
- Picking any color (embedded picker or quick colors) now **switches to Manual mode
  automatically** — the color you pick is what you get, even if an animated mode was running.

[2.2.0]: https://github.com/u2n4/ps5-led/releases/tag/v2.2.0

## [2.1.0] - 2026-07-02

### Added
- **System-tray icon** (pure Win32, zero extra dependencies): left-click opens the app;
  right-click shows a quick menu — your profiles (one click to apply), lightbar off, and quit.
- **Embedded live color picker**: the HSV picker now lives inside the main window next to
  the sliders — no popup, color applies to the controller while you drag.

### Changed
- Smaller portable EXE (14.9 → 12.8 MB): unused standard-library modules excluded.
- Dropped the unused `psutil` dependency (battery reading comes from the controller itself).

[2.1.0]: https://github.com/u2n4/ps5-led/releases/tag/v2.1.0

## [2.0.0] - 2026-07-02

### Added
- **Accurate DualSense view**: the PS5 controller is now rendered from a licensed SVG asset
  (`assets/dualsense-svgrepo.svg`), with the light bar drawn where it really is — two strips
  hugging the touchpad edges plus the diffusion line under its bottom edge, all synced 100%
  with the physical lightbar. Player LEDs, mic-mute button, and monochrome face-button glyphs included.
- **Live color picker**: built-in HSV picker that applies to the controller *while you drag* —
  no OK button needed (Cancel restores the previous color).
- **Battery mode**: new lighting mode that colors the lightbar by charge level
  (green ≥60%, amber ≥30%, red below — pulsing while charging).
- **Shell colors**: render the controller in the five official colorways —
  White, Midnight Black, Cosmic Red, Starlight Blue, Galactic Purple.
- **Game profiles**: three ready-made game profiles (Fortnite / COD / FIFA) and profile names
  are now free-text, so you can name profiles after your games.
- **Portable single-file EXE** (PyInstaller): no Python required at all.
  `install.ps1` now prefers the portable EXE and falls back to a *minimal* Python install
  (no docs/tests/IDLE, pip without cache) only when the EXE is unavailable.

### Changed
- **Near-zero idle cost while gaming**: the starfield and the controller preview stop
  rendering entirely while the window is hidden/minimized; the engine writes to the
  controller only on color changes (plus a 2s keep-alive) instead of 30 HID writes/sec.

### Removed
- The generic pseudo-3D gamepad drawing for PS5 (replaced by the accurate SVG view;
  PS4 keeps the classic top-strip drawing that matches the DS4's real lightbar position).

[2.0.0]: https://github.com/u2n4/ps5-led/releases/tag/v2.0.0

## [1.0.0] - 2026-06-29

### Added
- Initial public release of **PS5 LED**.
- 10 lighting modes: Manual, Rainbow, Pulse, Flash, Breathing, Heartbeat, Wave, Gradient, Sequence, Random.
- Live 3D controller view that mirrors the real lightbar color in sync.
- Automatic PS5 (DualSense) / PS4 (DualShock 4) detection.
- Battery monitor with low / plugged / full alerts.
- Named color/effect profiles.
- Bilingual UI (English / Arabic), switchable at runtime.
- Fullscreen mode and minimize-to-tray.
- Animated starfield background (toggleable).
- Headless background mode via CLI (`--background`, `--stop-after`, `--off-on-exit`).

[1.0.0]: https://github.com/u2n4/ps5-led/releases/tag/v1.0.0
