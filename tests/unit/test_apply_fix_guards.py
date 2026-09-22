from __future__ import annotations

import subprocess
from pathlib import Path

from vulnagent.graph.nodes.apply_fix import _allowed_files, _diff_paths


def test_diff_paths() -> None:
    diff = "--- a/src/A.java\n+++ b/src/A.java\n@@ -1 +1 @@\n-x\n+y\n--- /dev/null\n+++ b/new.txt\n"
    assert _diff_paths(diff) == {"src/A.java", "new.txt"}


async def test_allowed_files_are_only_tracked_sources_named_in_the_error(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/A.java").write_text("class A {}")
    (tmp_path / "pom.xml").write_text("<project/>")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    failure = "[ERROR] /work/src/A.java:[3,9] cannot find symbol\n/work/src/Missing.java:[1,1] x"
    assert await _allowed_files(str(tmp_path), failure, "pom.xml") == ["src/A.java"]
