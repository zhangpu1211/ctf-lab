"""README 是持续状态入口；docs 目录不再入库。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
GITIGNORE = ROOT / ".gitignore"
PACKAGING = ROOT / "PACKAGING.md"


class CurrentReadmeTests(unittest.TestCase):
    def test_readme_tracks_completed_and_open_work(self) -> None:
        text = README.read_text(encoding="utf-8")
        for heading in ("## 快速开始", "## 项目进度", "### ✅ 已完成",
                        "### 🚧 未完成", "## 安全边界", "## 许可证"):
            self.assertIn(heading, text)
        self.assertIn("v0.1.4-preview.20261102-spice-client-hotfix", text)
        self.assertIn("v0.1.4-preview.20261101", text)
        self.assertIn("G0/G1", text)
        self.assertIn("Windows 11 x64", text)

    def test_docs_directory_is_removed_and_ignored(self) -> None:
        self.assertFalse((ROOT / "docs").exists())
        self.assertIn("/docs/", GITIGNORE.read_text(encoding="utf-8"))
        self.assertNotIn("](docs/", README.read_text(encoding="utf-8"))

    def test_packaging_gate_remains_available(self) -> None:
        text = PACKAGING.read_text(encoding="utf-8")
        self.assertIn("开工前门禁", text)
        self.assertIn("发布前最终门禁", text)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`PACKAGING.md`", agents)

    def test_relative_markdown_links_resolve(self) -> None:
        text = README.read_text(encoding="utf-8")
        for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^\s)]+)\)", text):
            if ":" in target or target.startswith(("/", "#")):
                continue
            self.assertTrue(
                (README.parent / target.split("#", 1)[0]).exists(),
                target,
            )


if __name__ == "__main__":
    unittest.main()
