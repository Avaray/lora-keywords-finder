"""
icons_loader.py — SVG icons for LoRA Keywords Finder buttons.

Icons are NOT placed in button HTML (Gradio 4 escapes it).
Instead, CSS mask-image is used via ::before pseudo-elements.
Each button wrapper must include "lkf-btn-<icon_name>" in elem_classes.
"""
import os
import base64

_ICON_FILES = {
    "reload":        "HumbleiconsRefresh.svg",
    "copy":          "FluentCopy28Filled.svg",
    "send":          "SolarPlayBoldDuotone.svg",
    "open-browser":  "BoxiconsLink.svg",
    "clear":         "BiDatabaseFillX.svg",
    "download":      "BiDatabaseFillDown.svg",
}

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")


def load_icons_from_dir(icons_dir: str = None) -> dict:
    """Read SVG files. Returns {name: svg_string}."""
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


ICONS: dict = load_icons_from_dir()


def svg_btn_label(icon_name: str, text: str = "") -> str:
    """
    Returns the plain-text label for a gr.Button.
    Icon-only buttons return "" (Gradio 4 renders HTML-escaped text,
    so the SVG is applied purely via CSS on the wrapper class).
    Text+icon buttons return the display text; the icon is added
    via ::before CSS on the lkf-btn-<icon_name> wrapper class.
    """
    return text


def generate_icon_css() -> str:
    """
    Build a CSS block that injects SVG icons into button ::before
    pseudo-elements using CSS mask-image + base64 data URIs.
    This works in Gradio 4 where button values are HTML-escaped.
    Icons adapt to the current text colour (currentColor).
    """
    lines = [
        "/* LoRA Keywords Finder — SVG icon buttons */",
    ]
    for name, svg in ICONS.items():
        if not svg:
            continue
        b64       = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        data_uri  = f"data:image/svg+xml;base64,{b64}"
        cls       = f"lkf-btn-{name}"
        lines.append(f"""\
.{cls} button {{
    display: inline-flex !important;
    align-items: center;
    justify-content: center;
    gap: 6px;
}}
.{cls} button::before {{
    content: '';
    display: inline-block;
    width: 16px;
    height: 16px;
    min-width: 16px;
    flex-shrink: 0;
    -webkit-mask: url('{data_uri}') center / contain no-repeat;
    mask: url('{data_uri}') center / contain no-repeat;
    background-color: currentColor;
}}""")
    return "\n".join(lines)
