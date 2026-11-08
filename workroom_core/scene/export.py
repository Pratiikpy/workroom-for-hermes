"""Static exports of a scene that need no code to read: SVG here, native PowerPoint through the builder process."""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape, quoteattr


def _f(v: float) -> str:
    return f"{float(v):.2f}".rstrip("0").rstrip(".")


def _paint(n: dict[str, Any]) -> str:
    fill = f"#{n['fill']}" if "fill" in n else "none"
    parts = [f"fill={quoteattr(fill)}"]
    if "stroke" in n:
        parts.append(f"stroke={quoteattr('#' + n['stroke'])} stroke-width={quoteattr(_f(n.get('stroke_w', 1)))}")
    if "opacity" in n:
        parts.append(f"opacity={quoteattr(_f(n['opacity']))}")
    return " ".join(parts)


def _transform(n: dict[str, Any]) -> str:
    if not n.get("rotate"):
        return ""
    cx, cy = n["x"] + n["w"] / 2, n["y"] + n["h"] / 2
    angle = _f(n["rotate"])
    return " transform=" + quoteattr("rotate(" + angle + " " + _f(cx) + " " + _f(cy) + ")")


def export_svg(scene: dict[str, Any]) -> str:
    """A self-contained SVG: shapes and text only. Every value is escaped; no links, no scripts, no event attributes."""
    c = scene["canvas"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_f(c["w"])} {_f(c["h"])}" width="{_f(c["w"])}" height="{_f(c["h"])}">']
    for n in scene["nodes"]:
        nid = quoteattr(n["id"])
        tr = _transform(n)
        t = n["type"]
        if t == "rect":
            r = f' rx={quoteattr(_f(n["radius"]))}' if n.get("radius") else ""
            out.append(f'<rect id={nid} x="{_f(n["x"])}" y="{_f(n["y"])}" width="{_f(n["w"])}" height="{_f(n["h"])}"{r} {_paint(n)}{tr}/>')
        elif t == "ellipse":
            out.append(f'<ellipse id={nid} cx="{_f(n["x"] + n["w"] / 2)}" cy="{_f(n["y"] + n["h"] / 2)}" rx="{_f(n["w"] / 2)}" ry="{_f(n["h"] / 2)}" {_paint(n)}{tr}/>')
        elif t == "line":
            out.append(f'<line id={nid} x1="{_f(n["x"])}" y1="{_f(n["y"])}" x2="{_f(n["x"] + n["w"])}" y2="{_f(n["y"] + n["h"])}" {_paint({k: v for k, v in n.items() if k != "fill"})}{tr}/>')
        else:
            size = n.get("size", 24)
            anchor = {"left": "start", "center": "middle", "right": "end"}[n.get("align", "left")]
            x = n["x"] + (0 if anchor == "start" else n["w"] / 2 if anchor == "middle" else n["w"])
            weight = "700" if n.get("bold") else "400"
            color = f"#{n.get('color', '1F2937')}"
            out.append(f'<text id={nid} x="{_f(x)}" y="{_f(n["y"] + size)}" font-size="{_f(size)}" font-weight="{weight}" font-family="Calibri, Arial, sans-serif" '
                       f'text-anchor="{anchor}" fill={quoteattr(color)}{tr}>{escape(n.get("text", ""))}</text>')
    out.append("</svg>")
    return "\n".join(out)


def export_html(scene: dict[str, Any], title: str = "Workroom page") -> str:
    """One self-contained HTML file around the SVG. A strict CSP forbids scripts, network and forms, so the file is a picture that can be opened anywhere."""
    csp = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{csp}\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{escape(title)}</title>"
            "<style>html,body{margin:0;background:#f3f4f6}body{display:flex;justify-content:center;padding:16px}svg{max-width:100%;height:auto;background:#fff;box-shadow:0 1px 6px rgba(0,0,0,.25)}</style>"
            "</head><body>\n" + export_svg(scene) + "\n</body></html>\n")
