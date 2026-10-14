"""Проверка практических заданий и оценка тестов.

Практика: браузер присылает значения переменных, полученные после запуска
кода слушателя; эталоны и допуски есть только на сервере.
"""

from dataclasses import dataclass
from numbers import Real

from .content import Check, Question


@dataclass
class CheckResult:
    label: str
    ok: bool
    message: str = ""


def _is_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


def _same(value: object, expected: object) -> bool:
    if isinstance(expected, bool) or isinstance(value, bool):
        return isinstance(value, bool) and isinstance(expected, bool) and value == expected
    if _is_number(expected):
        return _is_number(value) and abs(value - expected) < 1e-9
    if isinstance(expected, str):
        return isinstance(value, str) and value.strip() == expected
    if isinstance(expected, list):
        return (
            isinstance(value, list)
            and len(value) == len(expected)
            and all(_same(v, e) for v, e in zip(value, expected))
        )
    return value == expected


def _hashable(items: list) -> set | None:
    try:
        return set(items)
    except TypeError:
        return None


def _evaluate(check: Check, value: object) -> str | None:
    """Возвращает None, если проверка пройдена, иначе причину (без подсказки из задания)."""
    var = f"`{check.var}`"
    if check.type == "equal":
        if isinstance(check.expected, list) and not isinstance(value, list):
            return f"Переменная {var} должна быть списком."
        if _is_number(check.expected) and not _is_number(value):
            return f"Переменная {var} должна быть числом."
        return None if _same(value, check.expected) else ""

    if check.type in ("approx", "range"):
        if not _is_number(value):
            return f"Переменная {var} должна быть числом (получено не число или NaN)."
        if check.type == "approx":
            return None if abs(value - check.expected) <= check.tol else ""
        low_ok = check.min is None or value >= check.min
        high_ok = check.max is None or value <= check.max
        return None if low_ok and high_ok else ""

    if check.type == "set":
        if not isinstance(value, list):
            return f"Переменная {var} должна быть списком."
        got = _hashable(value)
        return None if got is not None and got == set(check.expected) else ""

    if check.type == "list_approx":
        if not isinstance(value, list) or not all(_is_number(v) for v in value):
            return f"Переменная {var} должна быть списком чисел."
        if len(value) != len(check.expected):
            return f"В списке {var} должно быть {len(check.expected)} элементов, а не {len(value)}."
        ok = all(abs(v - e) <= check.tol for v, e in zip(value, check.expected))
        return None if ok else ""

    if check.type == "dict_approx":
        if not isinstance(value, dict):
            return f"Переменная {var} должна быть словарём."
        if set(value) != set(check.expected):
            return f"Ключи словаря {var} не совпадают с ожидаемыми."
        ok = all(
            _is_number(value[k]) and abs(value[k] - e) <= check.tol for k, e in check.expected.items()
        )
        return None if ok else ""

    raise ValueError(f"Неизвестный тип проверки: {check.type}")


def evaluate_checks(checks: list[Check], values: dict) -> list[CheckResult]:
    results = []
    for check in checks:
        if check.var not in values:
            message = (
                f"Переменная `{check.var}` не найдена. Проверьте, что она создана "
                "и названа точно так же, как в условии."
            )
            results.append(CheckResult(check.label, False, message))
            continue
        problem = _evaluate(check, values[check.var])
        if problem is None:
            results.append(CheckResult(check.label, True))
        else:
            message = problem or check.hint or f"Значение `{check.var}` не совпадает с ожидаемым."
            results.append(CheckResult(check.label, False, message))
    return results


# --- Тесты ------------------------------------------------------------------


def grade_quiz(questions: list[Question], answers: dict[str, list[int]]) -> tuple[int, list[bool]]:
    """Возвращает число верных ответов и список «верно/неверно» по вопросам.

    Вопрос засчитывается, только если выбранный набор вариантов совпал с верным.
    """
    marks = [frozenset(answers.get(q.id, [])) == q.correct for q in questions]
    return sum(marks), marks
