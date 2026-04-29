# Draw.ipe - Draw.io to Ipe Converter

A best-effort converter for transforming Draw.io diagrams into Ipe XML format, enabling seamless integration of diagrams into LaTeX documents.

## Why Convert to Ipe?

While Draw.io is excellent for creating diagrams, **Ipe** offers crucial advantages for academic and technical publishing:

### Full LaTeX Integration

Ipe uses a **complete LaTeX compiler** for all text elements, which means:

- **Perfect font matching**: Your diagram fonts will exactly match your document's font family, size, and style
- **Full preamble support**: Load any LaTeX packages (`amsmath`, `tikz`, `pgf`, custom macros) via the Ipe page preamble
- **Consistent math rendering**: Mathematical formulas use the same LaTeX engine as your document, ensuring identical spacing, symbols, and styling
- **Page-level consistency**: Define colors, pen styles, and layers at the document level that persist across all figures

### Professional Typesetting

- Vector output that integrates natively with PDFLaTeX workflows
- Precise control over label positioning and alignment
- Layers for organizing complex diagrams
- Native support for references and cross-referencing within figures

## Installation

### Prerequisites

1. **Python 3.13+** with `pip` or `uv` (earler Python versions likely work as well)
2. **Ipe** (optional, for viewing/editing output): https://ipe.otfried.org/

### Install Dependencies

Using `uv` (recommended):
```bash
uv sync
```

Or using standard pip:
```bash
pip install .
```

For development purposes, install as editable:
```bash
pip install -e .
```

## Usage

### Basic Conversion

```bash
# Using uv
uv run convert.py input.drawio output.ipe

# Using Python directly
python convert.py input.drawio output.ipe
```

### Options

```bash
uv run convert.py --help

Options:
  --scale SCALE     Scale factor to convert Draw.io pixels to Ipe points
                    (default: 0.75). Adjust if diagram appears too large/small.

  --margin MARGIN   Extra margin in Ipe points added around the page
                    (default: 0.0)

  --creator NAME    Creator string stored in Ipe metadata
                    (default: drawdotipe)

  -v, --verbose     Enable verbose output showing conversion progress
```

### Examples

```bash
# Standard conversion
uv run convert.py diagram.drawio diagram.ipe

# With verbose output
uv run convert.py -v diagram.drawio diagram.ipe

# Adjust scale for different sizing
uv run convert.py diagram.drawio diagram.ipe --scale 0.6

# Add margin around the page
uv run convert.py diagram.drawio diagram.ipe --margin 20
```

## Supported Features

The converter handles the most common Draw.io primitives needed for LaTeX workflows:

- Rectangles and rounded rectangles
- Ellipses and double ellipses
- Text labels with basic HTML formatting
- LaTeX math mode (`$$...$$` → `$...$`)
- Lines and polylines with waypoints
- Edges with arrowheads (start, end, or both)
- Dashed and dotted lines
- Group transformations
- Custom colors (hex and named)
- Stroke width and fill colors

### Limitations

- Complex shapes (actors, clouds, etc.) are approximated as rectangles
- Image exports are not supported (vector shapes only)
- Some Draw.io-specific styling may be simplified
- Multi-page diagrams export the first page only

## Workflow

1. **Create your diagram** in Draw.io as usual
2. **Export** as `.drawio` file (File → Export As → Draw.io)
3. **Convert** using this tool
4. **Open in Ipe** to fine-tune positioning, add LaTeX preamble, or adjust styles
5. **Include in LaTeX** with `\includegraphics{figure.ipe}` (using `graphicx` with Ipe support) or export to PDF

## Setting Up LaTeX Preamble in Ipe

After conversion, open the `.ipe` file in Ipe and edit the document properties:

1. Go to **Document Properties** → **LaTeX Preamble**
2. Add your document's preamble:
   ```latex
   \usepackage{amsmath, amssymb}
   \usepackage{mathpazo}  % Match document font
   \pagestyle{empty}
   ```
3. Save and your diagram now uses the exact same typesetting as your paper

## Technical Structure

```
drawioipe/
├── convert.py          # Main conversion script
├── pyproject.toml      # Project configuration
├── tests/              # Test suite
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Testing

Run the test suite with pytest:

```bash
uv run pytest
```

## Contributing

Contributions are welcome! Feel free to submit issues or pull requests for:
- Support for additional Draw.io shapes
- Better styling preservation
- Multi-page diagram handling
- Performance improvements

## Acknowledgments

- Draw.io (diagrams.net) for the excellent diagramming tool
- Otfried Cheong for creating Ipe
- The LaTeX community for making professional typesetting accessible
