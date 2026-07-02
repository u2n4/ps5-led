# Contributing to PS5 LED

Thanks for your interest! 🎮 Contributions of all sizes are welcome — bug reports, docs, translations, new effects, and code.

## Quick start

```bash
git clone https://github.com/u2n4/ps5-led.git
cd dualled-pro
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python dualled_pro.py
```

## Ways to help

- 🐛 **Bug reports** — open an issue with your OS, Python version, controller model (PS5/PS4), and the relevant lines from `%APPDATA%\DualLED_Pro\app.log`.
- 🌍 **Translations** — strings live in the `STRINGS`/i18n tables inside `dualled_pro.py`. Add a language by extending those dicts.
- 🎨 **New effects** — effects are computed in the engine loop; add a mode to the mode list and its color function.
- 🕹️ **3D models** — improving or adding controller models in the 3D view is very welcome.
- 📦 **Packaging** — a clean PyInstaller spec, a macOS `.app`, or a Linux AppImage would be great additions.

## Pull request checklist

- [ ] Keep changes focused — one logical change per PR.
- [ ] The app still launches: `python dualled_pro.py`.
- [ ] No hard-coded personal paths or secrets.
- [ ] Update the README if you change behavior or flags.
- [ ] Describe **what** changed and **why** in the PR description.

## Code style

- Python 3.8+ compatible.
- Follow the surrounding style in `dualled_pro.py`.
- Prefer small, readable functions over clever one-liners.

## Code of Conduct

Be respectful. This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
