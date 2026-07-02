from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

project = "copilot-box"
author = "Copilot Box Maintainers"
copyright = f"{datetime.now(UTC).year}, {author}"

extensions = [
    "myst_parser",
    "sphinx_rtd_theme",
]

source_suffix = {
    ".md": "markdown",
    ".rst": "restructuredtext",
}

master_doc = "index"
language = "zh_CN"
html_theme = "sphinx_rtd_theme"
html_title = "copilot-box 文档"
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 4,
}
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

myst_heading_anchors = 3
