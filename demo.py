"""Replay the two Codex analyses of the educational pilot."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PILOT = ROOT / "projects" / "pilot"


def main():
    project = Path(tempfile.mkdtemp(prefix="productmind-"))

    def run(*args):
        return json.loads(subprocess.check_output(
            [sys.executable, "-X", "utf8", str(ROOT / "productmind.py"),
             "--project", str(project), *map(str, args)], encoding="utf-8"))

    brief, = run("add", "--brief", PILOT / "BRIEF.md")
    first = run("save", PILOT / "INITIAL.md", "--base", 0, "--sources", brief,
                "--reason", "Первичный разбор учебного брифа")
    evidence, = run("add", PILOT / "pilot.csv")
    second = run("save", PILOT / "REVIEW.md", "--base", first, "--sources", brief, evidence,
                 "--reason", "CSV показал преимущество ручной подготовки в учебном прогоне")
    print(f"Журнал: {project / 'journal.sqlite3'}")
    print(f"Версия {first}: проверить форму.")
    print(f"Версия {second}: закрыть разработку формы при сопоставимых замерах.")


if __name__ == "__main__":
    main()
