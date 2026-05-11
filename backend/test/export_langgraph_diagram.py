"""Export the current LangGraph graph using LangGraph's official drawing API.

Run from the backend directory:

    uv run python test/export_langgraph_diagram.py

By default, this writes:

    ../docs/diagrams/memomed-langgraph-official.mmd
    ../docs/diagrams/memomed-langgraph-official.png
    ../docs/diagrams/memomed-langgraph-official.md
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agent.graph import graph


def export_langgraph_diagram(output_dir: Path, basename: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    compiled_graph = graph.get_graph()
    mermaid = compiled_graph.draw_mermaid()
    png = compiled_graph.draw_mermaid_png()

    mermaid_path = output_dir / f"{basename}.mmd"
    png_path = output_dir / f"{basename}.png"
    markdown_path = output_dir / f"{basename}.md"

    mermaid_path.write_text(mermaid, encoding="utf-8")
    png_path.write_bytes(png)
    markdown_path.write_text(
        "\n".join(
            [
                "# Memomed LangGraph 官方导出图",
                "",
                "来源：`graph.get_graph().draw_mermaid()` 与 `graph.get_graph().draw_mermaid_png()`。",
                "",
                "## 官方 Mermaid",
                "",
                "```mermaid",
                mermaid.rstrip(),
                "```",
                "",
                "## 官方 PNG",
                "",
                f"![Memomed LangGraph 官方导出图](./{png_path.name})",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Mermaid: {mermaid_path}")
    print(f"PNG: {png_path}")
    print(f"Markdown: {markdown_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Memomed LangGraph diagrams.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../docs/diagrams"),
        help="Directory for generated diagram files.",
    )
    parser.add_argument(
        "--basename",
        default="memomed-langgraph-official",
        help="Base filename without extension.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    export_langgraph_diagram(args.output_dir, args.basename)
