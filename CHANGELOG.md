# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-04-29

### Added
- Initial release of Draw.io to Ipe converter
- Support for multiple Draw.io file formats:
  - Raw `<mxGraphModel>` XML
  - `<mxfile><diagram>` wrapper format
  - Compressed base64+zlib payloads with URL-encoded XML
- Complete shape conversion:
  - Rectangles, ellipses, triangles, rhombuses
  - Lines, polylines, curves
  - Group containers with coordinate transform handling
- Edge/path conversion with proper waypoint handling
- Arrow support with correct Ipe syntax (`arrow`, `rarrow` attributes)
- Line style support (dashed, dotted patterns via `dash` attribute)
- Text label conversion with LaTeX math mode detection (`$$...$$`)
- Coordinate system transformation (Draw.io top-left origin → Ipe bottom-left origin)
- Command-line interface with argparse:
  - Input/output file arguments
  - Verbose output mode (`-v/--verbose`)
  - Helpful usage examples in `--help`
- CLI entry point: `drawio-to-ipe`
- Comprehensive test suite (50 tests)
- README.md with LaTeX compiler motivation and usage examples
- MIT License
- Type hints and Google-style docstrings throughout codebase

### Fixed
- URL-decoding of compressed Draw.io payloads after zlib decompression
- Edge path newline formatting (literal `\n` strings → actual newlines)
- Ipe arrow attribute syntax (separate `arrow` and `rarrow` for end/start heads)
- Group container coordinate offset accumulation with recursive transforms
- Invalid edge point handling (partial `None` coordinates resolved to group boundaries)
- Prevention of group container rendering as shapes

### Technical
- Python 3.13+ compatibility
- Package metadata in `pyproject.toml`
- Dev dependencies: pytest, ruff, mypy
