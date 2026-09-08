<div align="center">

# 🎮 PS5 LED

### Real-time RGB lightbar control for PS5 DualSense & PS4 DualShock 4 — with a live 3D controller view

[![Portable](https://img.shields.io/badge/Portable-EXE%20%E2%80%94%20no%20Python-3776AB)](#-easy-install--windows-exe-only)
[![Platform](https://img.shields.io/badge/Platform-Windows%2064--bit-555?logo=windows&logoColor=white)](#-installation)
[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-ff69b4.svg)](CONTRIBUTING.md)
[![Made with Tkinter](https://img.shields.io/badge/UI-Tkinter-FFD43B?logo=python&logoColor=333)](https://docs.python.org/3/library/tkinter.html)

[![GitHub stars](https://img.shields.io/github/stars/u2n4/ps5-led?style=social)](https://github.com/u2n4/ps5-led/stargazers)

**Pick any color, run a lighting effect, watch your battery — and see it mirrored on a 3D model of your actual controller, in real time.**

🇬🇧 English · 🇸🇦 [بالعربي](#-بالعربي)

![PS5 LED — PS5 DualSense with an animated RGB lightbar](assets/hero.png)

</div>

---

## ⚡ Easy install — Windows EXE only

Open **PowerShell** and paste:

```powershell
irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install.ps1 | iex
```

This downloads the latest published **PS5-LED.exe**, checks its mandatory SHA256 manifest, creates a **PS5 LED** desktop shortcut and opens the app. Python, pip, .NET and separate viewer packages are **not required**: the executable bundles its runtime, native HID code, 3D viewer and assets. Windows supplies the HID and graphics drivers.

If the release or checksum cannot be downloaded or verified, installation stops with an error. There is no source or Python fallback, including through the former `PS5LED_ALLOW_PYTHON_INSTALL` variable. Updates preserve your settings and replace only the executable after verification; repeated installs do not accumulate backup files.

The default installation folder is `%LOCALAPPDATA%\DualLED-Pro`. Advanced script parameters: `-InstallDir`, `-Version <release-tag>`, `-NoLaunch`, `-NoShortcut`. You can also download the executable and its checksum from [Releases](https://github.com/u2n4/ps5-led/releases).

**For the complete source/project instead, use the separate [developer download](#-installation) below.**

---

## ✨ Features

- 🎨 **10 lighting modes** — Manual, Rainbow, Pulse, Flash, Breathing, Heartbeat, Wave, Gradient, Sequence, Random.
- 🕹️ **Live controller view** — an accurate DualSense rendering whose light bar mirrors the real one **100% in sync**, in 5 official shell colors.
- 🔍 **Auto-detects your controller** — PS5 DualSense and PS4 DualShock 4 are both driven automatically.
- 🔋 **Battery monitor & alerts** — low-battery, plugged-in, and full-charge notifications.
- 💾 **Profiles** — save and switch named color/effect presets instantly.
- 🌍 **Bilingual UI** — English & Arabic (العربية), switchable at runtime.
- 🪟 **Fullscreen + tray** — runs fullscreen, minimizes to tray instead of quitting.
- 🌌 **Animated starfield background** (toggleable).
- 🎛️ **Headless / background mode** — drive the lightbar with no window via the CLI.
- 🧩 **Original Tkinter app** — settings and profiles stay in `dualled_pro.py`; the embedded OpenGL viewer uses PyOpenGL and pyopengltk. Windows HID uses the standard library only.

> **Scope, honestly:** PS5 LED is focused on **lighting, battery, and presets**. It is *not* a music-reactive / macro / scheduling suite — it does one thing and does it cleanly.

---

## 📸 Screenshots

| 3D sync view | Effects & profiles |
|---|---|
| ![3D view](assets/screenshot-3d.png) | ![Effects](assets/screenshot-effects.png) |

<!-- Add real PNGs to assets/. Placeholders are fine until then. -->

---

## 🚀 Installation

### Download the full source/project — developers only

This **different PowerShell command** downloads all tracked project files, assets, tests, tools, documentation and dotfiles to a new folder under Downloads:

```powershell
irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install-source.ps1 | iex
```

It downloads the complete `main` tree at one resolved commit. It does not install dependencies, launch the program or overwrite existing folders. The archive includes the full project; Git history, generated releases and local/untracked files are not part of a source archive. For Git history, use `git clone https://github.com/u2n4/ps5-led.git` and then `cd ps5-led`.

To choose a branch, tag or commit and output directory:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install-source.ps1))) -Ref main -Destination "$HOME\Downloads\ps5-led-dev"
```

### Run or build the downloaded source

Only source development needs **Windows, Python 3.8+ and Tkinter**. From the downloaded project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install PyOpenGL==3.1.10 pyopengltk==0.0.4
.\.venv\Scripts\python.exe dualled_pro.py
```

The two packages enable the full embedded 3D viewer. Without them the source app uses its Canvas fallback; native controller access still needs no third-party HID package. `requirements.txt` intentionally contains no mandatory packages.

Building a standalone EXE is a separate developer step, using Python 3.13 for the currently verified build:

```powershell
.\.venv\Scripts\python.exe -m pip install PyInstaller==6.21.0
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm PS5-LED.spec
```

The result is `dist\PS5-LED.exe`. End users run that file without installing the development tools above.

### Windows driver note

Keep the controller on the standard Windows HID driver for USB or Bluetooth. No driver replacement is required.

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
│  Controller │ ───────► │  PS5 LED  │ ───────────────► │  Lightbar    │
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

The embedded viewer uses PyOpenGL and pyopengltk; device access uses Windows HID through ctypes. The 3D model is **PS5 Controller by Taohid Animation**, **CC BY 4.0**; see [ATTRIBUTION.md](ATTRIBUTION.md). Not affiliated with or endorsed by Sony. PlayStation, DualSense, and DualShock are trademarks of Sony Interactive Entertainment.

---

<div align="center" dir="rtl">

## 🇸🇦 بالعربي

# 🎮 PS5 LED

### تحكّم لحظي بإضاءة يد PS5 (DualSense) و PS4 (DualShock 4) — مع عرض ثلاثي الأبعاد حي لليد

اختر أي لون، شغّل تأثير إضاءة، راقب البطارية — وشوفها كلها منعكسة على نموذج ثلاثي الأبعاد لليد الفعلية لحظة بلحظة.

### ✨ المزايا

- 🎨 **10 أوضاع إضاءة** — يدوي، قوس قزح، نبض، وميض، تنفّس، نبضة قلب، موجة، تدرّج، تسلسل، عشوائي.
- 🕹️ **عرض حي لليد** — رسم DualSense دقيق تتزامن إضاءته مع اليد الحقيقية 100%، بخمسة ألوان رسمية.
- 🔍 **كشف تلقائي لليد** — تحكم PS5 DualSense و PS4 DualShock 4 يعمل تلقائياً.
- 🔋 **مراقبة بطارية وتنبيهات** — تنبيه عند انخفاض الشحن، التوصيل، والاكتمال.
- 💾 **ملفات تعريف** — احفظ وبدّل بين إعدادات لون/تأثير محفوظة فوراً.
- 🌍 **واجهة ثنائية اللغة** — عربي وإنجليزي، تتبدّل أثناء التشغيل.
- 🪟 **ملء الشاشة + تصغير للشريط** بدلاً من الإغلاق.
- 🌌 **خلفية نجوم متحركة** (قابلة للإيقاف).
- 🎛️ **وضع خلفي بدون واجهة** عبر سطر الأوامر.
- 🧩 **برنامج Tkinter الأصلي** — ملف EXE مستقل للمستخدم، ومصدر المشروع كامل للمطور.

> **بصراحة، نطاق البرنامج:** PS5 LED مركّز على **الإضاءة، البطارية، والإعدادات المحفوظة**. مو برنامج تفاعل مع الموسيقى ولا ماكروهات ولا جدولة — يسوّي شي واحد ويسوّيه نظيف.

---

### 📸 لقطات الشاشة

| عرض ثلاثي الأبعاد متزامن | التأثيرات والإعدادات |
|---|---|
| ![3D view](assets/screenshot-3d.png) | ![Effects](assets/screenshot-effects.png) |

<!-- ضِف صور PNG حقيقية في مجلد assets. -->

---

### ⚡ التثبيت السهل — ملف EXE فقط

افتح **PowerShell** والصق:

```powershell
irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install.ps1 | iex
```

يحمّل آخر إصدار منشور من **PS5-LED.exe**، ويتحقق من ملف SHA256 الإلزامي، ويسوي اختصار **PS5 LED** على سطح المكتب ويفتح البرنامج. **ما يحتاج تثبيت Python أو pip أو .NET أو مكتبات عرض منفصلة**؛ ملف EXE يضم بيئة التشغيل وكود اليد والعارض ثلاثي الأبعاد وملفاته. تعريفات HID والرسوم يوفرها Windows.

إذا تعذر تنزيل الإصدار أو التحقق من بصمته، يتوقف برسالة واضحة. ما فيه تحويل تلقائي إلى Python أو المصدر، حتى لو كان المتغير القديم `PS5LED_ALLOW_PYTHON_INSTALL` مضبوطًا. التحديث يحافظ على إعداداتك ويستبدل ملف EXE فقط بعد التحقق؛ تكرار التثبيت ما يراكم ملفات نسخ احتياطية.

مكان التثبيت الافتراضي `%LOCALAPPDATA%\DualLED-Pro`. خيارات السكربت: `-InstallDir` و`-Version <release-tag>` و`-NoLaunch` و`-NoShortcut`. والتنزيل اليدوي متاح من [صفحة الإصدارات](https://github.com/u2n4/ps5-led/releases).

### 🚀 تحميل المصدر والمشروع كامل — للمطورين

هذا **أمر PowerShell مختلف** يحمّل كل ملفات المشروع المتتبعة، بما فيها الأصول والاختبارات والأدوات والتوثيق والملفات المخفية، داخل مجلد جديد في Downloads:

```powershell
irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install-source.ps1 | iex
```

يحمّل شجرة `main` كاملة عند commit محدد. ما يثبت مكتبات ولا يشغّل البرنامج ولا يستبدل مجلدًا موجودًا. أرشيف المصدر ما يشمل تاريخ Git أو الإصدارات المبنية أو الملفات المحلية غير المتتبعة. إذا تبي تاريخ Git، استخدم `git clone https://github.com/u2n4/ps5-led.git` وبعده `cd ps5-led`.

لاختيار فرع أو tag أو commit ومجلد التنزيل:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/u2n4/ps5-led/main/install-source.ps1))) -Ref main -Destination "$HOME\Downloads\ps5-led-dev"
```

### تشغيل المصدر أو بناء EXE

تطوير المصدر يحتاج **Windows وPython 3.8+ وTkinter**. من مجلد المشروع الذي نزلته:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install PyOpenGL==3.1.10 pyopengltk==0.0.4
.\.venv\Scripts\python.exe dualled_pro.py
```

المكتبتان تشغّلان العرض ثلاثي الأبعاد الكامل. بدونهما تستخدم نسخة المصدر الرسم البديل Canvas، والاتصال باليد يظل بدون مكتبة HID إضافية. ملف `requirements.txt` متعمد ما فيه مكتبات إلزامية.

لبناء EXE مستقل، استخدم Python 3.13 المطابق للبناء المتحقق منه:

```powershell
.\.venv\Scripts\python.exe -m pip install PyInstaller==6.21.0
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm PS5-LED.spec
```

الناتج `dist\PS5-LED.exe`؛ مستخدم البرنامج ما يحتاج أدوات التطوير هذه.

> **تعريف اليد:** خلّ اليد على Windows HID الأصلي. USB وBluetooth ما يحتاجان تبديل التعريف.

---

### 🎛️ الاستخدام

شغّل الواجهة:

```bash
python dualled_pro.py
```

شغّله **بدون واجهة** (يستخدم آخر إعدادات حفظتها):

```bash
# تشغيل الإضاءة بالخلفية
python dualled_pro.py --background

# يوقف تلقائياً بعد 30 دقيقة، ويطفّي الإضاءة
python dualled_pro.py --background --stop-after 30 --off-on-exit
```

| الأمر | الوظيفة |
|---|---|
| `--background` | يشتغل بدون واجهة، باستخدام آخر لون/وضع محفوظ. |
| `--stop-after N` | يوقف تلقائياً بعد `N` دقيقة (وضع الخلفية). |
| `--off-on-exit` | يطفّي الإضاءة عند الخروج. |

الإعدادات والسجلات تنحفظ في مجلد بيانات النظام (`%APPDATA%\DualLED_Pro` على ويندوز).

---

### 🧩 كيف يشتغل البرنامج

```
┌─────────────┐   HID    ┌───────────────┐   لون/تأثير      ┌──────────────┐
│   اليد       │ ───────► │  PS5 LED  │ ───────────────► │  الإضاءة      │
│  PS5 / PS4  │ ◄─────── │  محرّك + واجهة  │                  │  (RGB فعلي)  │
└─────────────┘  بطارية   └───────┬───────┘                  └──────────────┘
                                 │ انعكاس
                                 ▼
                        ┌──────────────────┐
                        │  نموذج 3D حي      │  نفس اللون، متزامن
                        └──────────────────┘
```

خيط (thread) بالخلفية يحسب اللون الحالي (ثابت أو تأثير متحرّك) ويرسله للإضاءة الفعلية عبر HID، وبنفس الوقت واجهة Tkinter ترسم يد ثلاثية الأبعاد إضاءتها بنفس اللون بالضبط.

---

### 🤝 المساهمة

الـ PRs والـ issues مرحّب فيها — شوف [CONTRIBUTING.md](CONTRIBUTING.md). أفكار للمبتدئين: نماذج يد إضافية في العرض 3D، تأثيرات جديدة، وصفات تغليف (PyInstaller / `.app` / AppImage)، وترجمات.

### 📜 الترخيص

[MIT](LICENSE) © u2n4

### 🙏 شكر

العارض المدمج يستخدم PyOpenGL وpyopengltk، والاتصال باليد يستخدم Windows HID عبر ctypes. نموذج **PS5 Controller** من **Taohid Animation** بترخيص **CC BY 4.0**؛ التفاصيل في [ATTRIBUTION.md](ATTRIBUTION.md). غير تابع لشركة Sony ولا معتمد منها. PlayStation و DualSense و DualShock علامات تجارية لـ Sony Interactive Entertainment.

</div>


### Embedded 3D branch and packaging

This branch extends the original Tkinter window. Drag the model with the mouse or use the right analog stick to orbit it. Gyro mirroring is optional and starts off. The existing five shell palettes and lighting modes remain in the settings panel.

The quick installer installs a published release EXE only. The separate source downloader accepts `-Ref` for the branch, tag or commit you want to inspect. Publishing source changes does not replace release binaries: rebuild, verify and publish `PS5-LED.exe` with `PS5-LED.exe.sha256` together before expecting the quick installer to deliver a new build.

`PS5-LED.spec` packages the Tk app, native HID modules, embedded viewer, preprocessed mesh, SVG fallback, icon and attribution into one Windows executable. PyInstaller is a **build-only** dependency; it is not required to run the Python app. A successful build alone does not verify rendering or controller operation: launch the built executable and check both before publishing it.

### فرع العرض ثلاثي الأبعاد والتغليف

هذا الفرع يطوّر نافذة Tkinter الأصلية. اسحب المجسم بالماوس أو استخدم العصا اليمنى لتدويره. تتبّع الجايرو اختياري ومطفأ عند البداية. ألوان الهيكل الخمسة وأوضاع الإضاءة تبقى ضمن الإعدادات الحالية.

المثبّت السريع يحمّل EXE من إصدار منشور فقط. أمر المصدر المنفصل يقبل `-Ref` لاختيار الفرع أو tag أو commit. نشر المصدر ما يحدّث ملفات الإصدار تلقائيًا؛ لازم بناء وفحص ونشر `PS5-LED.exe` مع `PS5-LED.exe.sha256` سويًا.

ملف `PS5-LED.spec` يضم التطبيق والعارض والملفات المساعدة والمجسم البديل ونَسب النموذج في ملف Windows تنفيذي. PyInstaller مطلوب للبناء فقط. نجاح البناء لا يثبت عمل الرسم أو اليد؛ يلزم تشغيل الملف التنفيذي وفحصهما قبل النشر.
