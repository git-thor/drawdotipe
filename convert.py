"""drawdotipe/convert.py

Best-effort Draw.io (mxGraphModel) -> Ipe XML converter.

This converter focuses on the most common Draw.io primitives that matter for
LaTeX workflows:
  - rectangles / rounded rectangles
  - ellipses
  - text labels (including basic HTML line breaks and $$math$$ -> $math$)
  - simple edges / lines with optional arrowheads

It preserves page geometry by mapping Draw.io's top-left pixel coordinates into
Ipe's point-based coordinate system with a Y flip.

Usage:
  python convert.py input.drawio.xml output.ipe
  python convert.py input.mxGraphModel.xml output.ipe --scale 0.75

Notes:
  - Draw.io can store diagrams either as a raw <mxGraphModel> or wrapped in an
    <mxfile>. This script supports both, including the common compressed diagram
    payload used by Draw.io export.
  - The built-in Ipe style block included below is intentionally small. Ipe can
    still use its defaults, but if you need more symbols/colors you can extend
    BASIC_IPESTYLE.
  - For exotic Draw.io shapes, add a new handler in shape_to_ipe().
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import html
import math
import re
import textwrap
import urllib.parse
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple


IPE_DTD = '<!DOCTYPE ipe SYSTEM "ipe.dtd">'
IPE_VERSION = "70218"

# A deliberately compact baseline style. Extend if you want more of Ipe's stock
# symbols/colors available inside the output document.
BASIC_IPESTYLE = """<ipestyle name="basic">
<color name="black" value="0 0 0"/>
<color name="white" value="1 1 1"/>
<color name="red" value="1 0 0"/>
<color name="green" value="0 1 0"/>
<color name="blue" value="0 0 1"/>
<color name="gray" value="0.5"/>
<color name="darkgray" value="0.25"/>
<color name="lightgray" value="0.75"/>
<color name="orange" value="1 0.647 0"/>
<color name="yellow" value="1 1 0"/>
<color name="brown" value="0.647 0.165 0.165"/>
<color name="purple" value="0.627 0.125 0.941"/>
<pen name="normal" value="0.4"/>
<pen name="fat" value="1.2"/>
<pen name="heavier" value="0.8"/>
<pen name="ultrafat" value="2"/>
<dashstyle name="dashed" value="[4] 0"/>
<dashstyle name="dotted" value="[1 3] 0"/>
<dashstyle name="dash dotted" value="[4 2 1 2] 0"/>
<dashstyle name="dash dot dotted" value="[4 2 1 2 1 2] 0"/>
</ipestyle>"""


@dataclasses.dataclass
class DrawIoNode:
    cell_id: str
    value: str
    style: Dict[str, str]
    parent: str
    vertex: bool
    edge: bool
    geometry: Optional[ET.Element]
    raw: ET.Element
    group_offset: Tuple[float, float] = (0.0, 0.0)
    group_size: Tuple[float, float] = (0.0, 0.0)


@dataclasses.dataclass
class IpeColorRegistry:
    colors: Dict[str, str] = dataclasses.field(default_factory=dict)
    counter: int = 0

    def register(self, color: str) -> str:
        """Return an Ipe color name for a CSS hex or named color.

        Args:
            color: CSS color value (hex like #FF0000, rgb(), or named color).

        Returns:
            An Ipe color name. Returns empty string for 'none', preserves
            valid Ipe names as-is, registers new colors with generated names
            (c1, c2, ...), or falls back to 'black' for invalid colors.
        """
        color = color.strip()
        if not color or color.lower() == "none":
            return ""
        if color in self.colors:
            return self.colors[color]

        # Preserve common Ipe names as-is.
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-/]*", color):
            self.colors[color] = color
            return color

        rgb = parse_css_color(color)
        if rgb is None:
            # Fall back to black instead of breaking the file.
            self.colors[color] = "black"
            return "black"

        self.counter += 1
        name = f"c{self.counter}"
        self.colors[color] = name
        return name

    def style_block(self) -> str:
        """Generate an Ipe <color> definition block for registered colors.

        Returns:
            A string containing <color> XML elements for all custom colors
            that were registered and are not already valid Ipe color names.
            Returns empty string if no custom colors were registered.
        """
        if not self.colors:
            return ""
        lines = []
        for original, name in self.colors.items():
            if name == original and re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-/]*", name):
                continue
            rgb = parse_css_color(original)
            if rgb is None:
                continue
            r, g, b = rgb
            lines.append(f'<color name="{name}" value="{r:g} {g:g} {b:g}"/>')
        return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="convert.py",
        description="Convert Draw.io diagrams to Ipe XML format for LaTeX workflows.",
        epilog="Example: python convert.py diagram.drawio output.ipe --scale 0.75",
    )
    p.add_argument(
        "input",
        type=Path,
        help="Input Draw.io XML file (.drawio or .xml export from Draw.io)",
    )
    p.add_argument(
        "output",
        type=Path,
        help="Output Ipe XML file (.ipe)",
    )
    p.add_argument(
        "--scale",
        type=float,
        default=0.75,
        metavar="SCALE",
        help="Scale factor to convert Draw.io pixels to Ipe points (default: 0.75). "
        "Adjust if your diagram appears too large or small.",
    )
    p.add_argument(
        "--margin",
        type=float,
        default=0.0,
        metavar="MARGIN",
        help="Extra margin in Ipe points added around the page (default: 0.0)",
    )
    p.add_argument(
        "--creator",
        type=str,
        default="drawdotipe",
        metavar="NAME",
        help="Creator string stored in Ipe metadata (default: drawdotipe)",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output showing conversion progress",
    )
    return p.parse_args()


def parse_css_color(value: str) -> Optional[Tuple[float, float, float]]:
    """Parse a CSS color string into RGB tuple.

    Args:
        value: CSS color value. Supports:
            - Hex colors: #RGB or #RRGGBB
            - RGB functional: rgb(r,g,b) where r,g,b are 0-255

    Returns:
        Tuple of (r, g, b) with each component as float in range [0.0, 1.0],
        or None if the input cannot be parsed as a valid color.

    Examples:
        >>> parse_css_color("#FF0000")
        (1.0, 0.0, 0.0)
        >>> parse_css_color("#F00")
        (1.0, 0.0, 0.0)
        >>> parse_css_color("rgb(255,128,0)")
        (1.0, 0.502, 0.0)
    """
    value = value.strip()
    if not value:
        return None
    if value.startswith("#") and len(value) in (4, 7):
        if len(value) == 4:
            r = int(value[1] * 2, 16)
            g = int(value[2] * 2, 16)
            b = int(value[3] * 2, 16)
        else:
            r = int(value[1:3], 16)
            g = int(value[3:5], 16)
            b = int(value[5:7], 16)
        return (r / 255.0, g / 255.0, b / 255.0)
    # CSS rgb(r,g,b)
    m = re.fullmatch(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", value)
    if m:
        r, g, b = map(int, m.groups())
        return (r / 255.0, g / 255.0, b / 255.0)
    return None


def safe_float(s: Optional[str], default: float = 0.0) -> float:
    """Safely convert a string to float with fallback default.

    Args:
        s: String to convert, or None.
        default: Default value if conversion fails or input is None.

    Returns:
        The converted float value, or the default if conversion fails.
    """
    try:
        return float(s) if s is not None else default
    except ValueError:
        return default


def decode_drawio_document(path: Path) -> ET.Element:
    """Load a Draw.io XML document.

    Supports:
      - raw <mxGraphModel>
      - <mxfile><diagram>...</diagram></mxfile>
      - compressed diagram payloads (base64 + deflate)
      - URL-encoded mxGraphModel content
    """
    raw = path.read_text(encoding="utf-8")

    # Handle URL-encoded files that aren't valid XML yet
    if raw.strip().startswith("%3C"):
        raw = urllib.parse.unquote(raw)

    root = ET.fromstring(raw)

    if root.tag == "mxfile":
        diagrams = root.findall("diagram")
        if not diagrams:
            raise ValueError("mxfile contains no <diagram> elements")
        # Concatenate all diagrams into a synthetic document by returning the first.
        # Extend this if you need multi-page exports.
        diag = diagrams[0]
        text = (diag.text or "").strip()
        if text.startswith("<mxGraphModel"):
            return ET.fromstring(text)
        decoded = decode_drawio_diagram_payload(text)
        return ET.fromstring(decoded)

    if root.tag == "mxGraphModel":
        return root

    # Sometimes users paste the <mxGraphModel> fragment into a wrapper element.
    graph = root.find(".//mxGraphModel")
    if graph is None:
        raise ValueError("Could not find an mxGraphModel in the input XML")
    return graph


def decode_drawio_diagram_payload(payload: str) -> str:
    payload = payload.strip()
    if not payload:
        raise ValueError("Empty Draw.io diagram payload")

    # Case 0: already XML
    if payload.lstrip().startswith("<mxGraphModel"):
        return payload

    # --- Attempt 1: base64 → zlib (most common for .drawio files) ---
    try:
        data = base64.b64decode(payload)
        try:
            decoded = zlib.decompress(data, -15).decode("utf-8")  # raw deflate
            # Check if result is URL-encoded and decode it
            if decoded.startswith("%3C"):
                return urllib.parse.unquote(decoded)
            return decoded
        except zlib.error:
            decoded = zlib.decompress(data).decode("utf-8")  # zlib header
            if decoded.startswith("%3C"):
                return urllib.parse.unquote(decoded)
            return decoded
    except Exception:
        pass

    # --- Attempt 2: URL → base64 → zlib ---
    try:
        u = urllib.parse.unquote(payload)
        data = base64.b64decode(u)
        try:
            decoded = zlib.decompress(data, -15).decode("utf-8")
            if decoded.startswith("%3C"):
                return urllib.parse.unquote(decoded)
            return decoded
        except zlib.error:
            decoded = zlib.decompress(data).decode("utf-8")
            if decoded.startswith("%3C"):
                return urllib.parse.unquote(decoded)
            return decoded
    except Exception:
        pass

    # --- Attempt 3: plain base64 (no compression) ---
    try:
        decoded = base64.b64decode(payload).decode("utf-8")
        if decoded.startswith("%3C"):
            return urllib.parse.unquote(decoded)
        return decoded
    except Exception:
        pass

    # --- Attempt 4: URL-decoded plain XML ---
    try:
        u = urllib.parse.unquote(payload)
        if u.lstrip().startswith("<mxGraphModel"):
            return u
    except Exception:
        pass

    raise ValueError(
        "Could not decode Draw.io payload.\nFirst 100 chars:\n" + payload[:100]
    )


def parse_style(style: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in style.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[part] = "1"
    return out


def collect_nodes(graph_model: ET.Element) -> List[DrawIoNode]:
    root = graph_model.find("root")
    if root is None:
        raise ValueError("mxGraphModel has no <root>")

    # First pass: collect all cells and identify groups
    cells_by_id: Dict[str, ET.Element] = {}
    for cell in root.findall("mxCell"):
        cells_by_id[cell.get("id", "")] = cell

    # Build parent offset map for groups
    group_offsets: Dict[str, Tuple[float, float]] = {}
    for cell_id, cell in cells_by_id.items():
        style = parse_style(cell.get("style", ""))
        if style.get("group") == "1":
            geom = cell.find("mxGeometry")
            if geom is not None:
                x = safe_float(geom.get("x"), 0.0)
                y = safe_float(geom.get("y"), 0.0)
                group_offsets[cell_id] = (x, y)

    def get_group_info(
        parent_id: str,
    ) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Recursively accumulate group offset and size. Returns (offset, size)."""
        if parent_id not in cells_by_id:
            return ((0.0, 0.0), (0.0, 0.0))
        parent_cell = cells_by_id[parent_id]
        parent_style = parse_style(parent_cell.get("style", ""))
        if parent_style.get("group") != "1":
            return ((0.0, 0.0), (0.0, 0.0))

        geom = parent_cell.find("mxGeometry")
        if geom is None:
            return ((0.0, 0.0), (0.0, 0.0))

        x = safe_float(geom.get("x"), 0.0)
        y = safe_float(geom.get("y"), 0.0)
        w = safe_float(geom.get("width"), 0.0)
        h = safe_float(geom.get("height"), 0.0)

        # Add grandparent offset if exists
        grandparent_id = parent_cell.get("parent", "")
        if grandparent_id:
            gp_offset, _ = get_group_info(grandparent_id)
            x += gp_offset[0]
            y += gp_offset[1]

        return ((x, y), (w, h))

    nodes: List[DrawIoNode] = []
    for cell in root.findall("mxCell"):
        cell_id = cell.get("id", "")
        style = parse_style(cell.get("style", ""))
        value = cell.get("value", "") or ""
        parent_id = cell.get("parent", "")

        # Get accumulated group offset and size
        group_offset, group_size = (
            get_group_info(parent_id) if parent_id else ((0.0, 0.0), (0.0, 0.0))
        )

        nodes.append(
            DrawIoNode(
                cell_id=cell_id,
                value=value,
                style=style,
                parent=parent_id,
                vertex=cell.get("vertex") == "1",
                edge=cell.get("edge") == "1",
                geometry=cell.find("mxGeometry"),
                raw=cell,
                group_offset=group_offset,
                group_size=group_size,
            )
        )
    return nodes


def escape_ipe_text(text: str) -> Tuple[str, bool]:
    """Return (escaped text, is_math_mode).

    Preserves LaTeX math and normalizes Draw.io's $$...$$ into raw math mode.
    """
    # Replace HTML line breaks with real newlines.
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    # Strip any other tags.
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)

    # Check if content is math mode ($$...$$ or single $...$)
    is_math = False
    if text.startswith("$$") and text.endswith("$$"):
        text = text[2:-2]
        is_math = True
    elif text.startswith("$") and text.endswith("$"):
        text = text[1:-1]
        is_math = True

    # Escape special XML chars but keep LaTeX backslashes
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text, is_math


def drawio_to_ipe_coords(
    x: float,
    y: float,
    w: float,
    h: float,
    page_height: float,
    scale: float,
    margin: float = 0.0,
) -> Tuple[float, float, float, float]:
    """Convert top-left Draw.io coordinates to Ipe bottom-left coordinates."""
    ix = x * scale + margin
    iy = (page_height - (y + h)) * scale + margin
    iw = w * scale
    ih = h * scale
    return ix, iy, iw, ih


def get_geometry(node: DrawIoNode) -> Tuple[float, float, float, float]:
    g = node.geometry
    if g is None:
        return (0.0, 0.0, 0.0, 0.0)
    gx = safe_float(g.get("x"), 0.0) + node.group_offset[0]
    gy = safe_float(g.get("y"), 0.0) + node.group_offset[1]
    return (
        gx,
        gy,
        safe_float(g.get("width")),
        safe_float(g.get("height")),
    )


def ipe_path_rect(ix: float, iy: float, iw: float, ih: float) -> str:
    # Ipe path syntax uses a bottom-left origin.
    x0, y0 = ix, iy
    x1, y1 = ix + iw, iy + ih
    return textwrap.dedent(
        f"""\
        {x0:g} {y0:g} m
        {x0:g} {y1:g} l
        {x1:g} {y1:g} l
        {x1:g} {y0:g} l
        h"""
    ).strip()


def ipe_path_ellipse(
    ix: float, iy: float, iw: float, ih: float, segments: int = 32
) -> str:
    # Polygon approximation: robust and valid without relying on arc syntax.
    cx = ix + iw / 2.0
    cy = iy + ih / 2.0
    rx = iw / 2.0
    ry = ih / 2.0
    pts = []
    for i in range(segments):
        t = 2.0 * math.pi * i / segments
        px = cx + rx * math.cos(t)
        py = cy + ry * math.sin(t)
        pts.append((px, py))
    lines = [f"{pts[0][0]:g} {pts[0][1]:g} m"]
    for px, py in pts[1:]:
        lines.append(f"{px:g} {py:g} l")
    lines.append("h")
    return "\n".join(lines)


def estimate_text_box(text: str, font_size_pt: float) -> Tuple[float, float, float]:
    lines = text.splitlines() or [text]
    max_chars = max((len(line) for line in lines), default=1)
    width = max(1.0, max_chars * font_size_pt * 0.55)
    height = max(1.0, len(lines) * font_size_pt * 1.2)
    depth = 0.0
    return width, height, depth


def shape_to_ipe(
    node: DrawIoNode,
    page_height: float,
    scale: float,
    colors: IpeColorRegistry,
    margin: float,
) -> List[str]:
    if node.geometry is None:
        return []

    x, y, w, h = get_geometry(node)
    if w == 0 and h == 0 and not node.edge:
        return []

    style = node.style
    shape = style.get("shape", "rectangle")
    stroke_color = style.get("strokeColor", "black")
    fill_color = style.get("fillColor", "none")
    stroke_width = style.get("strokeWidth", "1")

    ix, iy, iw, ih = drawio_to_ipe_coords(x, y, w, h, page_height, scale, margin)

    attrs = ['layer="alpha"']
    if stroke_color and stroke_color.lower() != "none":
        attrs.append(f'stroke="{colors.register(stroke_color)}"')
    if fill_color and fill_color.lower() != "none":
        attrs.append(f'fill="{colors.register(fill_color)}"')
    if stroke_width:
        try:
            pen = max(0.1, float(stroke_width) * scale * 0.5)
            attrs.append(f'pen="{pen:g}"')
        except ValueError:
            pass

    # Handle dashed lines
    if style.get("dashed") == "1":
        dash_style = style.get("dashStyle", "dashed")
        if dash_style:
            attrs.append(f'dash="{dash_style}"')

    # Common Draw.io shapes.
    if node.edge:
        return [drawio_edge_to_ipe(node, page_height, scale, colors, margin)]

    if shape in {"ellipse", "doubleEllipse"}:
        path = ipe_path_ellipse(ix, iy, iw, ih)
    else:
        # Default rectangle. Rounded rectangles are approximated as rectangles.
        path = ipe_path_rect(ix, iy, iw, ih)

    attr_str = " ".join(attrs)
    return [f"<path {attr_str}>{xml_escape(path)}</path>"]


def drawio_edge_to_ipe(
    node: DrawIoNode,
    page_height: float,
    scale: float,
    colors: IpeColorRegistry,
    margin: float,
) -> str:
    """Render a very common Draw.io edge as a simple polyline.

    This uses source/target geometry if available, otherwise falls back to the
    control points stored in mxGeometry/mxPoint.
    """
    style = node.style
    stroke_color = style.get("strokeColor", "black")
    stroke_width = style.get("strokeWidth", "1")

    attrs = ['layer="alpha"']
    if stroke_color and stroke_color.lower() != "none":
        attrs.append(f'stroke="{colors.register(stroke_color)}"')
    if stroke_width:
        try:
            pen = max(0.1, float(stroke_width) * scale * 0.5)
            attrs.append(f'pen="{pen:g}"')
        except ValueError:
            pass

    geom = node.geometry
    points: List[Tuple[float, float]] = []

    # Add group offset to edge points
    gx, gy = node.group_offset
    gw, gh = node.group_size

    if geom is not None:

        def resolve_point_with_group(elem: ET.Element) -> Optional[Tuple[float, float]]:
            """Resolve point, treating None coords as relative to group bounds."""
            x_str = elem.get("x")
            y_str = elem.get("y")

            # If both present, use directly
            if x_str is not None and y_str is not None:
                try:
                    return (float(x_str), float(y_str))
                except ValueError:
                    return None

            # Partial coordinates: None means use group boundary
            x = 0.0
            y = 0.0
            if x_str is not None:
                try:
                    x = float(x_str)
                except ValueError:
                    pass
            # else x stays 0 (left edge)

            if y_str is not None:
                try:
                    y = float(y_str)
                except ValueError:
                    pass
            # else y stays 0 (top edge)

            return (x, y)

        # Get source point
        src = geom.find('mxPoint[@as="sourcePoint"]')
        if src is not None:
            pt = resolve_point_with_group(src)
            if pt is not None:
                points.append((pt[0] + gx, pt[1] + gy))

        # Waypoints
        arr = geom.find("Array[@as='points']")
        if arr is not None:
            for pt_elem in arr.findall("mxPoint"):
                px_str = pt_elem.get("x")
                py_str = pt_elem.get("y")
                if px_str is not None and py_str is not None:
                    try:
                        points.append((float(px_str) + gx, float(py_str) + gy))
                    except ValueError:
                        pass

        # Get target point
        tgt = geom.find('mxPoint[@as="targetPoint"]')
        if tgt is not None:
            pt = resolve_point_with_group(tgt)
            if pt is not None:
                points.append((pt[0] + gx, pt[1] + gy))

    # Fallback: if we have no points, skip this edge
    if len(points) < 2:
        if len(points) == 1:
            points.append((points[0][0] + 20, points[0][1]))
        else:
            # No valid points - return empty path
            return ""

    # Convert points into Ipe space.
    path_lines: List[str] = []
    for i, (px, py) in enumerate(points):
        ix = px * scale + margin
        iy = (page_height - py) * scale + margin
        path_lines.append(f"{ix:g} {iy:g} {'m' if i == 0 else 'l'}")
    # Arrowheads: Ipe uses "normal/normal" format
    # arrow="" is for end arrow, rarrow="" is for start (reverse) arrow
    arrow_start = style.get("startArrow", "none")
    arrow_end = style.get("endArrow", "none")
    if arrow_start != "none" and arrow_end != "none":
        attrs.append('arrow="normal/normal"')
        attrs.append('rarrow="normal/normal"')
    elif arrow_start != "none":
        attrs.append('rarrow="normal/normal"')
    elif arrow_end != "none":
        attrs.append('arrow="normal/normal"')

    # Handle dashed lines for edges
    if style.get("dashed") == "1":
        dash_style = style.get("dashStyle", "dashed")
        if dash_style:
            attrs.append(f'dash="{dash_style}"')

    attr_str = " ".join(attrs)
    return f"<path {attr_str}>\n{chr(10).join(path_lines)}\n</path>"


def text_to_ipe(
    node: DrawIoNode,
    page_height: float,
    scale: float,
    colors: IpeColorRegistry,
    margin: float,
) -> List[str]:
    if node.geometry is None:
        return []

    style = node.style
    x, y, w, h = get_geometry(node)
    ix, iy, iw, ih = drawio_to_ipe_coords(x, y, w, h, page_height, scale, margin)

    text, is_math = escape_ipe_text(node.value)
    if not text.strip():
        return []

    font_size = safe_float(style.get("fontSize"), 12.0) * scale
    width, height, depth = estimate_text_box(text, font_size)

    # Draw.io text is typically centered in its box.
    pos_x = ix + iw / 2.0
    pos_y = iy + ih / 2.0

    stroke_color = style.get("fontColor", style.get("strokeColor", "black"))
    attrs = [
        'layer="alpha"',
        'transformations="translations"',
        f'pos="{pos_x:g} {pos_y:g}"',
        f'stroke="{colors.register(stroke_color)}"',
        'type="label"',
        f'width="{width:g}"',
        f'height="{height:g}"',
        f'depth="{depth:g}"',
        'valign="baseline"',
    ]

    # Optional horizontal alignment hint.
    align = style.get("align", "center")
    if align in {"left", "center", "right"}:
        attrs.append(f'halign="{align}"')

    # Add math style for LaTeX content
    if is_math:
        attrs.append('style="math"')

    return [f"<text {' '.join(attrs)}>{text}</text>"]


def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def find_page_size(graph_model: ET.Element) -> Tuple[float, float]:
    return (
        safe_float(graph_model.get("pageWidth"), 850.0),
        safe_float(graph_model.get("pageHeight"), 1100.0),
    )


def build_ipe_document(
    graph_model: ET.Element,
    scale: float,
    margin: float,
    creator: str,
) -> str:
    page_width, page_height = find_page_size(graph_model)
    nodes = collect_nodes(graph_model)
    colors = IpeColorRegistry()

    # Keep only content-bearing cells, skipping the synthetic root cells 0/1.
    content_nodes = [
        n for n in nodes if n.cell_id not in {"0", "1"} and (n.vertex or n.edge)
    ]

    page_items: List[str] = []
    for node in content_nodes:
        # Skip group containers - they only provide coordinate transforms
        if node.style.get("group") == "1":
            continue

        if node.edge:
            page_items.append(
                drawio_edge_to_ipe(node, page_height, scale, colors, margin)
            )
            continue
        if (
            node.style.get("shape") == "text"
            or node.style.get("html") == "1"
            or node.value
        ):
            # Prefer text labels for explicit text cells.
            if (
                node.style.get("shape") == "text"
                or node.style.get("strokeColor") == "none"
                or node.style.get("fillColor") == "none"
            ):
                page_items.extend(text_to_ipe(node, page_height, scale, colors, margin))
                continue
            # For label-like cells, output both shape and text when needed.
        page_items.extend(shape_to_ipe(node, page_height, scale, colors, margin))
        # If the cell contains visible text, overlay it.
        if node.value and node.value.strip():
            page_items.extend(text_to_ipe(node, page_height, scale, colors, margin))

    # A single alpha layer keeps the file simple and editable in Ipe.
    layers = '<layer name="alpha"/>'
    view = '<view layers="alpha" active="alpha"/>'

    created = "D:20260428231212"
    modified = created

    style_block = BASIC_IPESTYLE
    extra_colors = colors.style_block()
    if extra_colors:
        style_block = style_block.replace("</ipestyle>", f"{extra_colors}\n</ipestyle>")

    xml = []
    xml.append('<?xml version="1.0"?>')
    xml.append(IPE_DTD)
    xml.append(f'<ipe version="{IPE_VERSION}" creator="{xml_escape(creator)}">')
    xml.append(f'<info created="{created}" modified="{modified}"/>')
    xml.append(style_block)
    xml.append("<page>")
    xml.append(layers)
    xml.append(view)
    xml.extend(page_items)
    xml.append("</page>")
    xml.append("</ipe>")
    return "\n".join(xml) + "\n"


def main() -> int:
    args = parse_args()

    if args.verbose:
        print(f"Reading Draw.io file: {args.input}")

    graph_model = decode_drawio_document(args.input)

    if args.verbose:
        print(f"Converting with scale={args.scale}, margin={args.margin}...")

    ipe = build_ipe_document(
        graph_model=graph_model,
        scale=args.scale,
        margin=args.margin,
        creator=args.creator,
    )

    args.output.write_text(ipe, encoding="utf-8", newline="\n")

    if args.verbose:
        print(f"Successfully wrote Ipe file: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
