"""Выполняет примеры кода из уроков и обновляет их вывод и рисунки.

    python scripts/sync_lesson_outputs.py            обновить все уроки
    python scripts/sync_lesson_outputs.py --check    только проверить (код возврата 1, если что-то устарело)
    python scripts/sync_lesson_outputs.py content/section-1/03-pandas.md

Правила разметки в уроках:

* блок ```python выполняется; блоки одного урока делят общее пространство имён;
* блок ```output сразу после кода заменяется на то, что код напечатал;
* ```python fig=имя сохраняет график в app/static/img/lessons/имя.png;
* ```python skip не выполняется (иллюстрация или заведомо неполный код).

Так числа и графики в тексте всегда получены тем самым кодом, который видит слушатель.
"""

import argparse
import contextlib
import importlib.util
import io
import os
import re
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
DATA = ROOT / "app" / "static" / "data"
FIGURES = ROOT / "app" / "static" / "img" / "lessons"

FENCE = re.compile(r"^```(.*)$")


def _load_harness():
    spec = importlib.util.spec_from_file_location("harness", ROOT / "app" / "static" / "py" / "harness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse(text: str) -> list[dict]:
    """Делит текст на куски: обычные строки и блоки кода с их info-строкой."""
    chunks, lines, i = [], text.split("\n"), 0
    plain: list[str] = []
    while i < len(lines):
        match = FENCE.match(lines[i])
        if not match:
            plain.append(lines[i])
            i += 1
            continue
        if plain:
            chunks.append({"kind": "text", "lines": plain})
            plain = []
        info, body = match.group(1).strip(), []
        i += 1
        while i < len(lines) and not FENCE.match(lines[i]):
            body.append(lines[i])
            i += 1
        if i == len(lines):
            raise ValueError("незакрытый блок кода")
        i += 1
        chunks.append({"kind": "code", "info": info, "lines": body})
    if plain:
        chunks.append({"kind": "text", "lines": plain})
    return chunks


def render(chunks: list[dict]) -> str:
    out: list[str] = []
    for chunk in chunks:
        if chunk["kind"] == "text":
            out.extend(chunk["lines"])
        else:
            out.extend([f"```{chunk['info']}", *chunk["lines"], "```"])
    return "\n".join(out)


def _next_code(chunks: list[dict], index: int) -> dict | None:
    """Блок кода, идущий сразу за данным (между ними допустимы только пустые строки)."""
    for chunk in chunks[index + 1:]:
        if chunk["kind"] == "code":
            return chunk
        if any(line.strip() for line in chunk["lines"]):
            return None
    return None


def process(path: Path, harness) -> tuple[str, dict[str, bytes]]:
    """Возвращает обновлённый текст урока и рисунки {имя: png}."""
    import matplotlib.pyplot as plt
    import pandas as pd

    chunks = parse(path.read_text(encoding="utf-8"))
    namespace = {"__name__": "__main__"}
    figures: dict[str, bytes] = {}
    harness.apply_plot_style()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pd.reset_option("all")
    pd.set_option("display.width", 100)

    for index, chunk in enumerate(chunks):
        if chunk["kind"] != "code":
            continue
        words = chunk["info"].split()
        if not words or words[0] != "python" or "skip" in words:
            continue
        code = "\n".join(chunk["lines"])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                exec(compile(code, f"{path.name}:блок {index}", "exec"), namespace)
            except Exception as exc:
                raise RuntimeError(f"{path}: блок кода не выполнился ({type(exc).__name__}: {exc})\n{code}") from exc

        figure_name = next((w[4:] for w in words if w.startswith("fig=")), None)
        if figure_name:
            if not plt.get_fignums():
                raise RuntimeError(f"{path}: блок fig={figure_name} не построил график")
            buffer = io.BytesIO()
            plt.gcf().savefig(buffer, format="png", dpi=110, bbox_inches="tight")
            figures[figure_name] = buffer.getvalue()
        plt.close("all")

        follower = _next_code(chunks, index)
        printed = stdout.getvalue().rstrip("\n")
        if follower is not None and follower["info"] == "output":
            if not printed:
                raise RuntimeError(f"{path}: после блока есть ```output, но код ничего не печатает\n{code}")
            follower["lines"] = printed.split("\n")
        elif printed:
            raise RuntimeError(f"{path}: код печатает вывод, но блока ```output после него нет\n{code}")
    return render(chunks), figures


def lesson_files(args: list[str]) -> list[Path]:
    if args:
        return [Path(a).resolve() for a in args]
    return sorted(CONTENT.glob("section-*/*.md"))


def sync(paths: list[Path], check: bool) -> list[str]:
    """Возвращает список устаревших файлов (в режиме check ничего не записывает)."""
    harness = _load_harness()
    stale: list[str] = []
    previous = Path.cwd()
    os.chdir(DATA)  # как в браузере: файлы данных лежат в текущем каталоге
    try:
        for path in paths:
            text, figures = process(path, harness)
            if text != path.read_text(encoding="utf-8"):
                stale.append(str(path.relative_to(ROOT)))
                if not check:
                    path.write_text(text, encoding="utf-8", newline="\n")
            for name, png in figures.items():
                target = FIGURES / f"{name}.png"
                if not target.exists():
                    stale.append(str(target.relative_to(ROOT)))
                if not check:
                    # Содержимое PNG не сравнивается: оно зависит от версии matplotlib и шрифтов.
                    FIGURES.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(png)
    finally:
        os.chdir(previous)
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="*", help="файлы уроков (по умолчанию все)")
    parser.add_argument("--check", action="store_true", help="не изменять файлы, только сообщить об устаревших")
    args = parser.parse_args()
    stale = sync(lesson_files(args.files), args.check)
    for item in stale:
        print(("устарел: " if args.check else "обновлён: ") + item)
    if not stale:
        print("Все уроки актуальны.")
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    os.environ.setdefault("MPLBACKEND", "Agg")
    sys.exit(main())
