"""UI strings, served to the page at boot.

Both tables carry the same keys by construction, because a key present in one
language renders as a blank label in the other and only a reader of that
language would ever notice.
"""

import copy

LANGUAGES = ("ar", "en")
DIRECTION = {"ar": "rtl", "en": "ltr"}

_EN = {
    "app_title": "PS5 LED",
    "mode": "Mode",
    "mode_manual": "Solid",
    "mode_rainbow": "Rainbow",
    "mode_wave": "Wave",
    "mode_flash": "Flash",
    "mode_battery": "Battery",
    "colour": "Colour",
    "speed": "Speed",
    "brightness": "Brightness",
    "duty": "Flash ratio",
    "shell": "Shell",
    "shell_white": "White",
    "shell_black": "Midnight Black",
    "shell_red": "Cosmic Red",
    "battery": "Battery",
    "charging": "Charging",
    "connected": "Connected",
    "disconnected": "Disconnected",
    "transport_usb": "USB",
    "transport_bt": "Bluetooth",
    "recentre": "Recentre",
    "about": "About",
    "close": "Close",
    "background": "Run in background",
    "profiles": "Profiles",
    "profile_save": "Save",
    "profile_delete": "Delete",
    "language": "Language",
    "no_controller": "No controller found. Connect it by cable or pair it over Bluetooth.",
    "held_by_another_app": "Another program is holding the controller. Close Steam or DS4Windows and try again.",
}

_AR = {
    "app_title": "PS5 LED",
    "mode": "الوضع",
    "mode_manual": "ثابت",
    "mode_rainbow": "قوس قزح",
    "mode_wave": "موجة",
    "mode_flash": "وميض",
    "mode_battery": "البطارية",
    "colour": "اللون",
    "speed": "السرعة",
    "brightness": "السطوع",
    "duty": "نسبة الوميض",
    "shell": "لون اليد",
    "shell_white": "أبيض",
    "shell_black": "أسود",
    "shell_red": "أحمر",
    "battery": "البطارية",
    "charging": "يشحن",
    "connected": "متصل",
    "disconnected": "غير متصل",
    "transport_usb": "واير",
    "transport_bt": "بلوتوث",
    "recentre": "إعادة المركزة",
    "about": "حول",
    "close": "إغلاق",
    "background": "تشغيل في الخلفية",
    "profiles": "ملفات التعريف",
    "profile_save": "حفظ",
    "profile_delete": "حذف",
    "language": "اللغة",
    "no_controller": "ما لقيت يد. وصّلها بالواير أو اقرنها بلوتوث.",
    "held_by_another_app": "برنامج ثاني ماسك اليد. سكّر Steam أو DS4Windows وجرّب مرة ثانية.",
}

_TABLES = {"en": _EN, "ar": _AR}


def strings(language):
    """The table for one language; unknown languages fall back to English."""
    return copy.deepcopy(_TABLES.get(language, _EN))


def all_strings():
    return {lang: copy.deepcopy(_TABLES[lang]) for lang in LANGUAGES}
