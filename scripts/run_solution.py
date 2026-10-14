"""Запускает эталонное решение практического урока и показывает проверяемые значения.

    python scripts/run_solution.py content/section-1/04-practice-first-look.yaml

Помогает при подготовке заданий: значения из вывода переносятся в поле expected.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.content import Check  # noqa: E402
from app.grading import evaluate_checks  # noqa: E402


def load_harness():
    spec = importlib.util.spec_from_file_location("harness", ROOT / "app" / "static" / "py" / "harness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_solution(path: Path) -> tuple[dict, list]:
    """Возвращает результат запуска решения и итоги его проверки."""
    return run_task(yaml.safe_load(path.read_text(encoding="utf-8")))


def run_task(task: dict) -> tuple[dict, list]:
    """То же для уже прочитанного задания: выполняет код из поля solution."""
    checks = [
        Check(
            var=raw["var"], type=raw["type"], label=raw.get("label", raw["var"]),
            expected=raw.get("expected"), tol=float(raw.get("tol", 1e-6)),
            min=raw.get("min"), max=raw.get("max"), hint=raw.get("hint", ""),
        )
        for raw in task["checks"]
    ]
    names = list(dict.fromkeys(check.var for check in checks))
    previous = Path.cwd()
    os.chdir(ROOT / "app" / "static" / "data")
    try:
        result = load_harness().run_code(task["solution"], names)
    finally:
        os.chdir(previous)
    return result, evaluate_checks(checks, result["values"])


def main() -> int:
    for arg in sys.argv[1:]:
        result, verdicts = run_solution(Path(arg).resolve())
        print(f"=== {arg}")
        if result["stdout"]:
            print(result["stdout"].rstrip())
        if result["error"]:
            print(result["error"])
        print("Значения:", json.dumps(result["values"], ensure_ascii=False, indent=2))
        print(f"Графиков: {len(result['images'])}")
        for verdict in verdicts:
            print(("  верно   " if verdict.ok else "  НЕВЕРНО ") + verdict.label + (f" — {verdict.message}" if verdict.message else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
