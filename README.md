<div align="center">

# 🎮 DualLED Pro

### Real-time RGB lightbar control for PS5 DualSense & PS4 DualShock 4 — with a live 3D controller view

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-555?logo=windows&logoColor=white)](#-installation)
[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-ff69b4.svg)](CONTRIBUTING.md)
[![Made with Tkinter](https://img.shields.io/badge/UI-Tkinter-FFD43B?logo=python&logoColor=333)](https://docs.python.org/3/library/tkinter.html)

<!-- Once you push: replace USER/REPO and add a real GIF to assets/demo.gif -->
[![GitHub stars](https://img.shields.io/github/stars/u2n4/dualled-pro?style=social)](https://github.com/u2n4/dualled-pro/stargazers)

**Pick any color, run a lighting effect, watch your battery — and see it mirrored on a 3D model of your actual controller, in real time.**

🇬🇧 English · 🇸🇦 [بالعربي](#-بالعربي)

<!-- Drop a real screen recording here. ~10s, shows color change + 3D sync + an effect. -->
![DualLED Pro demo](assets/demo.gif)

</div>

---

## ✨ Features

- 🎨 **10 lighting modes** — Manual, Rainbow, Pulse, Flash, Breathing, Heartbeat, Wave, Gradient, Sequence, Random.
- 🕹️ **Live 3D controller view** — a 3D PS5/PS4 model whose lightbar mirrors the real one **100% in sync**.
- 🔍 **Auto-detects your controller** — picks the correct PS5 (DualSense) or PS4 (DualShock 4) model automatically.
- 🔋 **Battery monitor & alerts** — low-battery, plugged-in, and full-charge notifications.
- 💾 **Profiles** — save and switch named color/effect presets instantly.
- 🌍 **Bilingual UI** — English & Arabic (العربية), switchable at runtime.
- 🪟 **Fullscreen + tray** — runs fullscreen, minimizes to tray instead of quitting.
- 🌌 **Animated starfield background** (toggleable).
- 🎛️ **Headless / background mode** — drive the lightbar with no window via the CLI.
- 🧩 **Single file, zero build step** — one `dualled_pro.py`, pure Python + Tkinter.

> **Scope, honestly:** DualLED Pro is focused on **lighting, battery, and presets**. It is *not* a music-reactive / macro / scheduling suite — it does one thing and does it cleanly.

---

## 📸 Screenshots

| 3D sync view | Effects & profiles |
|---|---|
| ![3D view](assets/screenshot-3d.png) | ![Effects](assets/screenshot-effects.png) |

<!-- Add real PNGs to assets/. Placeholders are fine until then. -->

---

## 🚀 Installation

> **Requires Python 3.8+** and a controller connected over **USB** (Bluetooth works too on most setups).

```bash
# 1. Clone
git clone https://github.com/u2n4/dualled-pro.git
cd dualled-pro

# 2. (recommended) virtual env
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python dualled_pro.py
```

**Minimal install** (just enough to run):

```bash
pip install -U pydualsense hidapi psutil
python dualled_pro.py
```

### Windows driver note (PS5 DualSense)

For `pydualsense` to talk to a DualSense, Windows needs the **WinUSB/libusb** driver bound to the controller. The simplest path is [Zadig](https://zadig.akeo.ie/): select the DualSense device → install **WinUSB**. (PS4 / generic HID controllers usually work without this.)

---

## 🎛️ Usage

Launch the GUI:

```bash
python dualled_pro.py
```

Run **headless** (no window — uses your last saved settings):

```bash
# Drive the lightbar in the background
python dualled_pro.py --background

# Auto-stop after 30 minutes, then turn the lightbar off
python dualled_pro.py --background --stop-after 30 --off-on-exit
```

| Flag | Description |
|---|---|
| `--background` | Run without the UI, using the last saved color/mode. |
| `--stop-after N` | Automatically stop after `N` minutes (background mode). |
| `--off-on-exit` | Turn the lightbar off when exiting. |

Config and logs live in your OS app-data folder (`%APPDATA%\DualLED_Pro` on Windows).

---

## 🧩 How it works

```
┌─────────────┐   HID    ┌───────────────┐   color/effect   ┌──────────────┐
│  Controller │ ───────► │  DualLED Pro  │ ───────────────► │  Lightbar    │
│ PS5 / PS4   │ ◄─────── │  engine + UI  │                  │  (real RGB)  │
└─────────────┘  battery └───────┬───────┘                  └──────────────┘
                                 │ mirror
                                 ▼
                        ┌──────────────────┐
                        │  Live 3D model   │  same color, in sync
                        └──────────────────┘
```

A background engine thread computes the current color (solid or animated effect) and pushes it to the physical lightbar over HID, while the Tkinter UI renders a 3D controller whose lightbar is tinted with the exact same value.

---

## 🤝 Contributing

PRs and issues are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Good first contributions: more controller models in the 3D view, extra effects, packaging recipes (PyInstaller spec, `.app`/AppImage), and translations.

## 📜 License

[MIT](LICENSE) © u2n4

## 🙏 Acknowledgements

Built on [`pydualsense`](https://github.com/flok/pydualsense), [`hidapi`](https://github.com/trezor/cython-hidapi), and [`psutil`](https://github.com/giampaolo/psutil). Not affiliated with or endorsed by Sony. PlayStation, DualSense, and DualShock are trademarks of Sony Interactive Entertainment.

---

<div align="center" dir="rtl">

## 🇸🇦 بالعربي

# 🎮 DualLED Pro

### تحكّم لحظي بإضاءة يد PS5 (DualSense) و PS4 (DualShock 4) — مع عرض ثلاثي الأبعاد حي لليد

اختر أي لون، شغّل تأثير إضاءة، راقب البطارية — وشوفها كلها منعكسة على نموذج ثلاثي الأبعاد لليد الفعلية لحظة بلحظة.

### ✨ المزايا

- 🎨 **10 أوضاع إضاءة** — يدوي، قوس قزح، نبض، وميض، تنفّس، نبضة قلب، موجة، تدرّج، تسلسل، عشوائي.
- 🕹️ **عرض ثلاثي الأبعاد حي** — نموذج 3D للـ PS5/PS4 إضاءته تتزامن مع اليد الحقيقية 100%.
- 🔍 **كشف تلقائي لنوع اليد** — يعرض النموذج الصحيح (PS5 أو PS4) تلقائياً.
- 🔋 **مراقبة بطارية وتنبيهات** — تنبيه عند انخفاض الشحن، التوصيل، والاكتمال.
- 💾 **ملفات تعريف** — احفظ وبدّل بين إعدادات لون/تأثير محفوظة فوراً.
- 🌍 **واجهة ثنائية اللغة** — عربي وإنجليزي، تتبدّل أثناء التشغيل.
- 🪟 **ملء الشاشة + تصغير للشريط** بدلاً من الإغلاق.
- 🌌 **خلفية نجوم متحركة** (قابلة للإيقاف).
- 🎛️ **وضع خلفي بدون واجهة** عبر سطر الأوامر.

### 🚀 التشغيل (ويندوز)

```bash
pip install -U pydualsense hidapi psutil
python dualled_pro.py
```

> ملاحظة ويندوز: لتشغيل DualSense لازم تثبّت درايفر **WinUSB** على اليد عبر [Zadig](https://zadig.akeo.ie/). يد PS4 غالباً تشتغل بدون هذا.

الترخيص: [MIT](LICENSE). غير تابع لشركة Sony.

</div>
