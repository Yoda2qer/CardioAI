"""Запускает код слушателя и собирает вывод, графики и значения переменных.

Файл выполняется внутри Pyodide в браузере. Его же импортируют тесты, чтобы
эталонные решения проверялись тем же кодом, что и ответы слушателей.
"""

import base64
import contextlib
import io
import json
import math
import os
import sys
import traceback
import warnings

os.environ.setdefault("MPLBACKEND", "Agg")

USER_FILE = "<решение>"
MAX_ITEMS = 500
MAX_OUTPUT = 20_000
MAX_FIGURES = 6

# Оформление графиков: те же настройки использованы для рисунков в уроках.
# Порядок цветов подобран так, чтобы соседние ряды различались и при нарушениях цветового зрения.
PLOT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
PLOT_STYLE = {
    "figure.figsize": (7.2, 4.2),
    "figure.dpi": 100,
    "lines.linewidth": 2,
    "patch.edgecolor": "white",
    "patch.force_edgecolor": True,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#a5a6c6",
    "axes.labelcolor": "#36355f",
    "axes.titleweight": "bold",
    "axes.titlesize": 12,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#e0e2f4",
    "grid.linewidth": 0.8,
    "xtick.color": "#62628b",
    "ytick.color": "#62628b",
    "legend.frameon": False,
    "font.size": 10.5,
}


def apply_plot_style():
    try:
        import matplotlib
    except ImportError:
        return
    from cycler import cycler

    matplotlib.rcParams.update(PLOT_STYLE)
    matplotlib.rcParams["axes.prop_cycle"] = cycler(color=PLOT_COLORS)


def to_plain(value, depth=0):
    """Приводит значение к типам JSON. Неподдерживаемые значения и NaN становятся None."""
    numpy = sys.modules.get("numpy")
    if value is None or isinstance(value, (bool, str)):
        return value
    if numpy is not None and isinstance(value, numpy.bool_):
        return bool(value)
    if isinstance(value, int):
        return value
    if numpy is not None and isinstance(value, numpy.integer):
        return int(value)
    if isinstance(value, float) or (numpy is not None and isinstance(value, numpy.floating)):
        value = float(value)
        return value if math.isfinite(value) else None
    if depth > 3:
        return None
    if isinstance(value, dict):
        return {str(k): to_plain(v, depth + 1) for k, v in list(value.items())[:MAX_ITEMS]}
    if hasattr(value, "tolist"):  # массивы numpy, Series и Index из pandas
        try:
            value = value.tolist()
        except Exception:
            return None
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_plain(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
    return None


def _format_error(exc, code):
    if isinstance(exc, SyntaxError) and exc.filename == USER_FILE:
        source = (exc.text or "").rstrip()
        return f"Синтаксическая ошибка в строке {exc.lineno}: {exc.msg}\n    {source}"
    lines = code.splitlines()
    report = ["Ошибка при выполнении кода:"]
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == USER_FILE:
            source = lines[frame.lineno - 1].strip() if 0 < frame.lineno <= len(lines) else ""
            report.append(f"  строка {frame.lineno}: {source}")
    report.append(f"{type(exc).__name__}: {exc}")
    return "\n".join(report)


def _collect_figures():
    pyplot = sys.modules.get("matplotlib.pyplot")
    if pyplot is None:
        return []
    images = []
    # Сборка matplotlib для Pyodide предупреждает об устаревших параметрах при сохранении
    # рисунка; к коду слушателя это не относится, поэтому предупреждения здесь скрыты.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for number in pyplot.get_fignums()[:MAX_FIGURES]:
            buffer = io.BytesIO()
            pyplot.figure(number).savefig(buffer, format="png", dpi=110, bbox_inches="tight")
            images.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
    pyplot.close("all")
    return images


def run_code(code, names=()):
    """Выполняет код и возвращает словарь: stdout, error, images, values."""
    apply_plot_style()
    namespace = {"__name__": "__main__"}
    output = io.StringIO()
    error = None

    def show_warning(message, category, *_args, **_kwargs):
        output.write(f"Предупреждение ({category.__name__}): {message}\n")

    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output), warnings.catch_warnings():
        warnings.simplefilter("default")
        for category in (DeprecationWarning, PendingDeprecationWarning, FutureWarning, ImportWarning):
            warnings.simplefilter("ignore", category)
        # plt.show() без окна — не ошибка: график всё равно будет показан под редактором.
        warnings.filterwarnings("ignore", message=".*non-interactive.*")
        warnings.showwarning = show_warning
        try:
            exec(compile(code, USER_FILE, "exec"), namespace)
        except BaseException as exc:  # включая SystemExit и KeyboardInterrupt из кода слушателя
            error = _format_error(exc, code)

    text = output.getvalue()
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n… вывод обрезан"
    return {
        "stdout": text,
        "error": error,
        "images": _collect_figures(),
        "values": {name: to_plain(namespace[name]) for name in names if name in namespace},
    }


def cardio_run(code, names_json="[]"):
    """Точка входа для браузера: принимает и возвращает строки."""
    return json.dumps(run_code(code, json.loads(names_json)), ensure_ascii=False)
