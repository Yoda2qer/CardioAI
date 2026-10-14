"""Скачивает Pyodide и библиотеки, которые используются в практических уроках,
чтобы платформа работала без доступа к интернету (например, в закрытой сети клиники).

    python scripts/fetch_pyodide.py

После загрузки укажите в файле .env:

    PYODIDE_BASE_URL=/static/vendor/pyodide/

Скачивается около 60 МБ. Целостность каждого пакета проверяется по контрольной
сумме из pyodide-lock.json.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import PYODIDE_VERSION  # noqa: E402

CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
CORE_FILES = [
    "pyodide.js", "pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm",
    "python_stdlib.zip", "pyodide-lock.json", "package.json",
]


def download(url: str, target: Path) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    target.write_bytes(data)
    return data


def course_packages() -> set[str]:
    """Библиотеки, перечисленные в полях packages практических заданий."""
    packages: set[str] = set()
    for path in (ROOT / "content").glob("section-*/*.yaml"):
        task = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        packages.update(task.get("packages") or [])
    return packages


def with_dependencies(names: set[str], lock: dict) -> list[str]:
    known = lock["packages"]
    result: list[str] = []
    stack = sorted(names)
    while stack:
        name = stack.pop().lower()
        if name in result:
            continue
        if name not in known:
            raise SystemExit(f"Пакета {name} нет в сборке Pyodide {PYODIDE_VERSION}")
        result.append(name)
        stack.extend(known[name].get("depends", []))
    return sorted(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка Pyodide для офлайн-режима")
    parser.add_argument("--dest", default=str(ROOT / "app" / "static" / "vendor" / "pyodide"))
    args = parser.parse_args()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    print(f"Pyodide {PYODIDE_VERSION} → {dest}")
    for name in CORE_FILES:
        print(f"  {name}")
        download(CDN + name, dest / name)

    lock = json.loads((dest / "pyodide-lock.json").read_text(encoding="utf-8"))
    packages = with_dependencies(course_packages(), lock)
    print(f"Библиотеки ({len(packages)}): {', '.join(packages)}")
    total = 0
    for name in packages:
        info = lock["packages"][name]
        target = dest / info["file_name"]
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == info["sha256"]:
            total += target.stat().st_size
            continue
        data = download(CDN + info["file_name"], target)
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            target.unlink()
            raise SystemExit(f"Контрольная сумма {info['file_name']} не совпала — загрузка прервана")
        total += len(data)
        print(f"  {info['file_name']} ({len(data) / 1e6:.1f} МБ)")

    print(f"Готово, библиотеки занимают {total / 1e6:.0f} МБ.")
    print("Добавьте в .env строку: PYODIDE_BASE_URL=/static/vendor/pyodide/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
