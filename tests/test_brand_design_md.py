"""A project DESIGN.md is read for colour and font tokens only; brand.json wins; hostile or malformed content yields nothing."""
import json
from pathlib import Path

from pptx import Presentation

from workroom.tests.test_create_flow import SPEC, _svc
from workroom.workroom_core.build.brand import parse_design_md

DESIGN = """# Acme design system

Intro paragraph with **bold** text and a link [x](https://evil.example).

## Colour
- Primary: #7C3AED
- Text: #111827
- Muted text: 6B7280
- Danger: #FF0000

## Type
Font family: "Inter", system-ui, sans-serif
"""


def test_tokens_are_read_by_name_and_everything_else_is_ignored() -> None:
    assert parse_design_md(DESIGN) == {"accent": "7C3AED", "ink": "111827", "muted": "6B7280", "font": "Inter"}


def test_front_matter_style_and_hostile_values() -> None:
    assert parse_design_md("---\naccent: '#0f766e'\nfont: Georgia\n---\nbody") == {"accent": "0F766E", "font": "Georgia"}
    assert parse_design_md("accent: red\nfont: <script>alert(1)</script>\nmuted: #12345") == {}
    assert parse_design_md("") == {} and parse_design_md("x" * 200000) == {}


def test_design_md_themes_created_decks_and_brand_json_wins(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    (root / "DESIGN.md").write_text(DESIGN, encoding="utf-8")
    st = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, st["release_id"], st["digest"])
    rule = next(s for s in Presentation(root / "reports/q2.pptx").slides[0].shapes if s.name == "Title rule")
    assert str(rule.fill.fore_color.rgb) == "7C3AED"
    (root / "brand.json").write_text(json.dumps({"accent": "0F766E"}), encoding="utf-8")
    st2 = svc.create_from_spec(pid, {**SPEC, "path": "reports/two.pptx"})
    svc.approve_and_publish(pid, st2["release_id"], st2["digest"])
    rule2 = next(s for s in Presentation(root / "reports/two.pptx").slides[0].shapes if s.name == "Title rule")
    assert str(rule2.fill.fore_color.rgb) == "0F766E"


AIRBNB = """## 2. Color Palette & Roles
### Primary
- **Rausch** (`#ff385c`): The brand's signature coral-pink.
### Quick Color Reference
- Primary CTA: "Rausch (#ff385c)"
- Page background: "Canvas White (#ffffff)"
- Heading / body text: "Ink Black (#222222)"
- Secondary text: "Ash Gray (#6a6a6a)"
## 3. Typography Rules
### Font Family
- **Airbnb Cereal VF** (primary and only): The proprietary variable-weight sans-serif. Fallbacks: `Circular, -apple-system`
"""

CURSOR = """### Font Family
- **Display/Headlines**: `CursorGothic`, with fallbacks: `CursorGothic Fallback, system-ui`
- **Body/Editorial**: `jjannon`, with fallbacks: `Iowan Old Style`
"""


def test_real_design_system_shapes_are_understood() -> None:
    assert parse_design_md(AIRBNB) == {"accent": "FF385C", "ink": "222222", "muted": "6A6A6A", "font": "Airbnb Cereal VF"}
    assert parse_design_md(CURSOR) == {"font": "CursorGothic"}


def test_unreadable_colours_and_non_brand_fonts_are_dropped() -> None:
    assert parse_design_md("- Primary CTA: \"Pale (#f5f5f5)\"\n- Heading / body text: \"Grey (#999999)\"") == {}
    assert parse_design_md("### Font Family\n- **Body**: `Apple Color Emoji`\n- **Mono**: `Berkeley Mono`") == {}
