"""
icons_loader.py — loads SVG icons for LoRA Keywords Finder buttons.
Place SVG files in the icons/ directory at the extension root.
"""
import os

# Canonical icon names → filenames in icons/
_ICON_FILES = {
    "reload":       "HumbleiconsRefresh.svg",
    "copy":         "FluentCopy28Filled.svg",
    "send":         "SolarPlayBoldDuotone.svg",
    "open-browser": "BoxiconsLink.svg",
    "clear":        "BiDatabaseFillX.svg",
    "download":     "BiDatabaseFillDown.svg",
}

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")


def load_icons_from_dir(icons_dir: str = None) -> dict:
    """
    Read every SVG file listed in _ICON_FILES from icons_dir.
    Returns {name: svg_string}.  Missing files are logged and stored as "".
    """
    if icons_dir is None:
        icons_dir = _ICONS_DIR
    result = {}
    for name, filename in _ICON_FILES.items():
        path = os.path.join(icons_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                result[name] = f.read().strip()
        except Exception as e:
            print(f"[LoRA Keywords] Could not load icon '{name}' ({path}): {e}")
            result[name] = ""
    return result


# Module-level cache — loaded once on import
ICONS: dict = load_icons_from_dir()


def svg_btn_label(icon_name: str, text: str = "") -> str:
    """
    Build an HTML label for a gr.Button that contains an SVG icon and
    optional text.  The SVG is wrapped in <span class="lkf-icon"> so it
    can be sized uniformly via CSS without expanding the button.

    Falls back gracefully to plain text when the icon file is missing.
    """
    svg = ICONS.get(icon_name, "")
    if not svg:
        return text if text else icon_name
    icon_span = f'<span class="lkf-icon">{svg}</span>'
    return f"{icon_span}&nbsp;{text}" if text else icon_span
