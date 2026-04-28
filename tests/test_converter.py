"""Tests for the Draw.io to Ipe convert."""

import base64
import tempfile
import zlib
from pathlib import Path

import pytest
import sys

# Add parent directory to path so we can import converter
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

import convert # noqa: E402


class TestParseStyle:
    """Tests for parse_style function."""

    def test_simple_style(self):
        style = "rectangle;fillColor=#ffffff;strokeColor=#000000;strokeWidth=2"
        result = convert.parse_style(style)
        # rectangle is stored as a flag with value "1", not key-value pair
        assert result["rectangle"] == "1"
        assert result["fillColor"] == "#ffffff"
        assert result["strokeColor"] == "#000000"
        assert result["strokeWidth"] == "2"

    def test_empty_style(self):
        result = convert.parse_style("")
        assert result == {}

    def test_style_with_flags(self):
        style = "ellipse;dashed=1;rounded=1"
        result = convert.parse_style(style)
        assert result["ellipse"] == "1"
        assert result["dashed"] == "1"
        assert result["rounded"] == "1"

    def test_style_with_spaces(self):
        style = "rectangle; fillColor=#fff ; strokeColor=#000 "
        result = convert.parse_style(style)
        assert result["fillColor"] == "#fff"
        assert result["strokeColor"] == "#000"


class TestSafeFloat:
    """Tests for safe_float function."""

    def test_valid_number(self):
        assert convert.safe_float("123.45") == 123.45

    def test_integer(self):
        assert convert.safe_float("42") == 42.0

    def test_none_input(self):
        assert convert.safe_float(None) == 0.0

    def test_invalid_string(self):
        assert convert.safe_float("invalid") == 0.0

    def test_custom_default(self):
        assert convert.safe_float(None, default=10.0) == 10.0


class TestParseCssColor:
    """Tests for parse_css_color function."""

    def test_hex_short(self):
        result = convert.parse_css_color("#abc")
        assert result is not None
        assert result[0] == 0xAA / 255.0
        assert result[1] == 0xBB / 255.0
        assert result[2] == 0xCC / 255.0

    def test_hex_long(self):
        result = convert.parse_css_color("#ff8800")
        assert result == (1.0, 0.5333333333333333, 0.0)

    def test_rgb_function(self):
        result = convert.parse_css_color("rgb(255, 128, 64)")
        assert result == (1.0, 128 / 255.0, 64 / 255.0)

    def test_invalid_color(self):
        assert convert.parse_css_color("notacolor") is None

    def test_empty_string(self):
        assert convert.parse_css_color("") is None


class TestDecodeDrawIoDocument:
    """Tests for decode_drawio_document function."""

    def test_raw_mxgraphmodel(self):
        xml_content = (
            '<mxGraphModel pageWidth="800" pageHeight="600"><root/></mxGraphModel>'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write(xml_content)
            f.flush()
            result = convert.decode_drawio_document(Path(f.name))
        assert result.tag == "mxGraphModel"
        assert result.get("pageWidth") == "800"

    def test_mxfile_with_diagram(self):
        # Test with compressed payload (real Draw.io format)
        xml_content = (
            '<mxGraphModel pageWidth="1000" pageHeight="800"><root/></mxGraphModel>'
        )
        import base64
        import zlib

        compressed = zlib.compress(xml_content.encode("utf-8"))
        encoded = base64.b64encode(compressed).decode("utf-8")

        mxfile_content = f"<mxfile><diagram>{encoded}</diagram></mxfile>"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".drawio", delete=False) as f:
            f.write(mxfile_content)
            f.flush()
            result = convert.decode_drawio_document(Path(f.name))
        assert result.tag == "mxGraphModel"
        assert result.get("pageWidth") == "1000"

    def test_url_encoded_file(self):
        xml_content = "%3CmxGraphModel%20pageWidth%3D%22500%22%3E%3Croot%2F%3E%3C%2FmxGraphModel%3E"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".drawio", delete=False) as f:
            f.write(xml_content)
            f.flush()
            result = convert.decode_drawio_document(Path(f.name))
        assert result.tag == "mxGraphModel"
        assert result.get("pageWidth") == "500"

    def test_compressed_payload(self):
        xml_content = '<mxGraphModel pageWidth="600"><root/></mxGraphModel>'
        compressed = zlib.compress(xml_content.encode("utf-8"))
        encoded = base64.b64encode(compressed).decode("utf-8")

        mxfile_content = f"<mxfile><diagram>{encoded}</diagram></mxfile>"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".drawio", delete=False) as f:
            f.write(mxfile_content)
            f.flush()
            result = convert.decode_drawio_document(Path(f.name))
        assert result.tag == "mxGraphModel"
        assert result.get("pageWidth") == "600"

    def test_invalid_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
            f.write("not valid xml")
            f.flush()
            with pytest.raises(Exception):
                convert.decode_drawio_document(Path(f.name))


class TestDecodeDrawIoDiagramPayload:
    """Tests for decode_drawio_diagram_payload function."""

    def test_already_xml(self):
        xml = "<mxGraphModel><root/></mxGraphModel>"
        result = convert.decode_drawio_diagram_payload(xml)
        assert result == xml

    def test_base64_zlib(self):
        xml = "<mxGraphModel><root/></mxGraphModel>"
        compressed = zlib.compress(xml.encode("utf-8"))
        encoded = base64.b64encode(compressed).decode("utf-8")
        result = convert.decode_drawio_diagram_payload(encoded)
        assert result == xml

    def test_url_encoded_after_decompress(self):
        xml = "<mxGraphModel><root/></mxGraphModel>"
        url_encoded = xml.replace("<", "%3C").replace(">", "%3E").replace('"', "%22")
        compressed = zlib.compress(url_encoded.encode("utf-8"))
        encoded = base64.b64encode(compressed).decode("utf-8")
        result = convert.decode_drawio_diagram_payload(encoded)
        assert result == xml

    def test_empty_payload(self):
        with pytest.raises(ValueError, match="Empty Draw.io diagram payload"):
            convert.decode_drawio_diagram_payload("")


class TestEscapeIpeText:
    """Tests for escape_ipe_text function."""

    def test_plain_text(self):
        text, is_math = convert.escape_ipe_text("Hello World")
        assert text == "Hello World"
        assert not is_math

    def test_html_br(self):
        text, is_math = convert.escape_ipe_text("Line1<br/>Line2")
        assert text == "Line1\nLine2"
        assert not is_math

    def test_double_dollar_math(self):
        text, is_math = convert.escape_ipe_text("$$E = mc^2$$")
        assert text == "E = mc^2"
        assert is_math

    def test_single_dollar_math(self):
        text, is_math = convert.escape_ipe_text("$x + y$")
        assert text == "x + y"
        assert is_math

    def test_xml_escaping(self):
        text, is_math = convert.escape_ipe_text("A & B < C")
        assert text == "A &amp; B &lt; C"
        assert not is_math

    def test_html_tags_stripped(self):
        text, is_math = convert.escape_ipe_text("<b>Bold</b> text")
        assert text == "Bold text"
        assert not is_math


class TestdrawdotipeCoords:
    """Tests for drawio_to_ipe_coords function."""

    def test_coordinate_conversion(self):
        ix, iy, iw, ih = convert.drawio_to_ipe_coords(
            x=100, y=100, w=200, h=150, page_height=1100, scale=0.75, margin=0
        )
        assert ix == 75.0
        assert iy == (1100 - 250) * 0.75
        assert iw == 150.0
        assert ih == 112.5

    def test_with_margin(self):
        ix, iy, iw, ih = convert.drawio_to_ipe_coords(
            x=0, y=0, w=100, h=100, page_height=1000, scale=1.0, margin=10
        )
        assert ix == 10.0
        assert iy == 910.0
        assert iw == 100.0
        assert ih == 100.0


class TestIpePathRect:
    """Tests for ipe_path_rect function."""

    def test_rectangle_path(self):
        path = convert.ipe_path_rect(10, 20, 30, 40)
        lines = path.split("\n")
        assert len(lines) == 5
        assert lines[0] == "10 20 m"
        assert lines[1] == "10 60 l"
        assert lines[2] == "40 60 l"
        assert lines[3] == "40 20 l"
        assert lines[4] == "h"


class TestIpePathEllipse:
    """Tests for ipe_path_ellipse function."""

    def test_ellipse_path(self):
        path = convert.ipe_path_ellipse(0, 0, 100, 50, segments=8)
        lines = path.split("\n")
        # 8 segments = 8 points: 1 move + 7 line commands + 1 close = 9 lines
        assert len(lines) == 9
        assert lines[0].endswith(" m")
        assert lines[-1] == "h"


class TestEstimateTextBox:
    """Tests for estimate_text_box function."""

    def test_single_line(self):
        width, height, depth = convert.estimate_text_box("Hello", 12.0)
        assert width > 0
        assert height > 0
        assert depth == 0.0

    def test_multi_line(self):
        text = "Line1\nLine2\nLine3"
        width, height, depth = convert.estimate_text_box(text, 12.0)
        assert height > 12.0


class TestCollectNodes:
    """Tests for collect_nodes function."""

    def test_collect_simple_nodes(self):
        xml = """<mxGraphModel>
            <root>
                <mxCell id="1" parent="0"/>
                <mxCell id="2" parent="1" vertex="1" style="rectangle;html=1" value="Test">
                    <mxGeometry x="10" y="20" width="100" height="50"/>
                </mxCell>
            </root>
        </mxGraphModel>"""
        graph = ET.fromstring(xml)
        nodes = convert.collect_nodes(graph)
        assert len(nodes) == 2
        node = nodes[1]
        assert node.cell_id == "2"
        assert node.vertex is True
        # rectangle is stored as flag
        assert "rectangle" in node.style
        assert node.value == "Test"

    def test_collect_with_group(self):
        xml = """<mxGraphModel>
            <root>
                <mxCell id="1" parent="0"/>
                <mxCell id="group1" parent="1" vertex="1" style="group">
                    <mxGeometry x="50" y="50" width="200" height="200"/>
                </mxCell>
                <mxCell id="child1" parent="group1" vertex="1" style="rectangle">
                    <mxGeometry x="10" y="10" width="50" height="50"/>
                </mxCell>
            </root>
        </mxGraphModel>"""
        graph = ET.fromstring(xml)
        nodes = convert.collect_nodes(graph)
        child = [n for n in nodes if n.cell_id == "child1"][0]
        assert child.group_offset == (50.0, 50.0)
        assert child.group_size == (200.0, 200.0)


class TestFindPageSize:
    """Tests for find_page_size function."""

    def test_custom_page_size(self):
        xml = '<mxGraphModel pageWidth="1200" pageHeight="900"><root/></mxGraphModel>'
        graph = ET.fromstring(xml)
        width, height = convert.find_page_size(graph)
        assert width == 1200.0
        assert height == 900.0

    def test_default_page_size(self):
        xml = "<mxGraphModel><root/></mxGraphModel>"
        graph = ET.fromstring(xml)
        width, height = convert.find_page_size(graph)
        assert width == 850.0
        assert height == 1100.0


class TestBuildIpeDocument:
    """Tests for build_ipe_document function."""

    def test_basic_document_structure(self):
        xml = """<mxGraphModel pageWidth="800" pageHeight="600">
            <root>
                <mxCell id="0" parent="0"/>
                <mxCell id="1" parent="0"/>
                <mxCell id="2" parent="1" vertex="1" style="rectangle">
                    <mxGeometry x="100" y="100" width="200" height="100"/>
                </mxCell>
            </root>
        </mxGraphModel>"""
        graph = ET.fromstring(xml)
        doc = convert.build_ipe_document(graph, scale=0.75, margin=0, creator="test")
        assert '<?xml version="1.0"?>' in doc
        assert '<!DOCTYPE ipe SYSTEM "ipe.dtd">' in doc
        assert '<ipe version="70218" creator="test">' in doc
        assert "<page>" in doc
        assert "</page>" in doc
        assert "</ipe>" in doc

    def test_document_with_colors(self):
        xml = """<mxGraphModel pageWidth="800" pageHeight="600">
            <root>
                <mxCell id="0" parent="0"/>
                <mxCell id="1" parent="0"/>
                <mxCell id="2" parent="1" vertex="1" style="rectangle;fillColor=#ff0000">
                    <mxGeometry x="100" y="100" width="200" height="100"/>
                </mxCell>
            </root>
        </mxGraphModel>"""
        graph = ET.fromstring(xml)
        doc = convert.build_ipe_document(graph, scale=0.75, margin=0, creator="test")
        assert '<color name="c1" value="1.0 0.0 0.0"/>' in doc or 'fill="c1"' in doc


class TestIntegration:
    """Integration tests with real .drawio files."""

    def test_convert_hello_drawio(self, tmp_path):
        hello_file = Path(__file__).parent / "data" / "hello.drawio"
        if not hello_file.exists():
            pytest.skip("hello.drawio test file not found")

        output_file = tmp_path / "hello.ipe"
        graph = convert.decode_drawio_document(hello_file)
        doc = convert.build_ipe_document(graph, scale=0.75, margin=0, creator="test")
        output_file.write_text(doc)

        assert output_file.exists()
        assert output_file.stat().st_size > 0
        assert "<?xml" in output_file.read_text()



class TestIColorRegistry:
    """Tests for IpeColorRegistry class."""

    def test_register_hex_color(self):
        registry = convert.IpeColorRegistry()
        name = registry.register("#ff0000")
        assert name in ["c1", "red"]
        assert "#ff0000" in registry.colors

    def test_register_none_color(self):
        registry = convert.IpeColorRegistry()
        name = registry.register("none")
        assert name == ""

    def test_register_duplicate(self):
        registry = convert.IpeColorRegistry()
        name1 = registry.register("#00ff00")
        name2 = registry.register("#00ff00")
        assert name1 == name2

    def test_style_block(self):
        registry = convert.IpeColorRegistry()
        registry.register("#0000ff")
        block = registry.style_block()
        assert '<color name="c1"' in block or block == ""


class TestXmlEscape:
    """Tests for xml_escape function."""

    def test_ampersand(self):
        assert convert.xml_escape("A & B") == "A &amp; B"

    def test_less_than(self):
        assert convert.xml_escape("A < B") == "A &lt; B"

    def test_greater_than(self):
        assert convert.xml_escape("A > B") == "A &gt; B"

    def test_combined(self):
        assert convert.xml_escape("A & B < C > D") == "A &amp; B &lt; C &gt; D"


# Import ET at module level for tests that need it
import xml.etree.ElementTree as ET
