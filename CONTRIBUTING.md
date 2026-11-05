# Contributing to PS5 LED

Thanks for your interest! 🎮 Contributions of all sizes are welcome — bug reports, docs, translations, new effects, and code.

## Quick start

```bash
git clone https://github.com/u2n4/ps5-led.git
cd ps5-led
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python dualled_pro.py
```

## Tests

```bash
pip install pytest PyOpenGL==3.1.10 pyopengltk==0.0.4
python -m pytest tests
```

The tests need no controller: the HID layer is replaced with fakes. The PyOpenGL pair is needed because `test_orbit` imports `controller_gl`. The suite runs on Windows, since the installer and single-instance tests use PowerShell and a Windows mutex.

## Ways to help

- 🐛 **Bug reports** — open an issue with your OS, Python version, controller model (PS5/PS4), and the relevant lines from `%APPDATA%\DualLED_Pro\app.log`.
- 🌍 **Translations** — strings live in the `STR` table inside `dualled_pro.py`. Add a language by extending those dicts.
- 🎨 **New effects** — effects are computed in the engine loop; add a mode to the mode list and its color function.
- 🕹️ **3D models** — improving or adding controller models in the 3D view is very welcome.
- 📦 **Packaging** — a clean PyInstaller spec, a macOS `.app`, or a Linux AppImage would be great additions.

## Pull request checklist

- [ ] Keep changes focused — one logical change per PR.
- [ ] The app still launches: `python dualled_pro.py` (and the built EXE when packaging changes).
- [ ] `python -m pytest tests` passes.
- [ ] No hard-coded personal paths or secrets.
- [ ] Update the README if you change behavior or flags.
- [ ] Describe **what** changed and **why** in the PR description.

## Code style

- Python 3.10 or newer; CI runs 3.10 and 3.12.
- Follow the surrounding style in `dualled_pro.py`.
- Prefer small, readable functions over clever one-liners.

## Code of Conduct

Be respectful. This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
