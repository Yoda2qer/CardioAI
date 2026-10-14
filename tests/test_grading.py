import importlib.util
from pathlib import Path

import pytest

from app.content import Check, Question
from app.grading import evaluate_checks, grade_quiz

HARNESS_PATH = Path(__file__).resolve().parent.parent / "app" / "static" / "py" / "harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("harness", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verdict(check: Check, values: dict):
    (result,) = evaluate_checks([check], values)
    return result


@pytest.mark.parametrize(
    "check, value, ok",
    [
        (Check("x", "equal", "x", expected=299), 299, True),
        (Check("x", "equal", "x", expected=299), 299.0, True),
        (Check("x", "equal", "x", expected=299), 300, False),
        (Check("x", "equal", "x", expected=299), "299", False),
        (Check("x", "equal", "x", expected=1), True, False),
        (Check("x", "equal", "x", expected=True), True, True),
        (Check("x", "equal", "x", expected=True), 1, False),
        (Check("x", "equal", "x", expected="age"), " age ", True),
        (Check("x", "equal", "x", expected=[1, 2]), [1, 2], True),
        (Check("x", "equal", "x", expected=[1, 2]), [2, 1], False),
        (Check("x", "approx", "x", expected=0.321, tol=0.001), 0.3214, True),
        (Check("x", "approx", "x", expected=0.321, tol=0.001), 0.33, False),
        (Check("x", "approx", "x", expected=0.321, tol=0.001), None, False),
        (Check("x", "approx", "x", expected=0.321, tol=0.001), True, False),
        (Check("x", "range", "x", min=0.7, max=0.9), 0.8, True),
        (Check("x", "range", "x", min=0.7), 0.95, True),
        (Check("x", "range", "x", min=0.7, max=0.9), 0.95, False),
        (Check("x", "set", "x", expected=["ca", "thal"]), ["thal", "ca"], True),
        (Check("x", "set", "x", expected=["ca", "thal"]), ["thal"], False),
        (Check("x", "set", "x", expected=["ca"]), [["ca"]], False),
        (Check("x", "list_approx", "x", expected=[1.0, 2.0], tol=0.01), [1.004, 2.0], True),
        (Check("x", "list_approx", "x", expected=[1.0, 2.0], tol=0.01), [1.0], False),
        (Check("x", "list_approx", "x", expected=[1.0, 2.0], tol=0.01), [1.0, "2"], False),
        (Check("x", "dict_approx", "x", expected={"a": 1.0}, tol=0.01), {"a": 1.001}, True),
        (Check("x", "dict_approx", "x", expected={"a": 1.0}, tol=0.01), {"b": 1.0}, False),
        (Check("x", "dict_approx", "x", expected={"a": 1.0}, tol=0.01), {"a": None}, False),
    ],
)
def test_check_types(check, value, ok):
    assert verdict(check, {"x": value}).ok is ok


def test_missing_variable_and_hint():
    check = Check("answer", "equal", "Ответ", expected=5, hint="Подсказка из задания")
    assert "не найдена" in verdict(check, {}).message
    assert verdict(check, {"answer": 6}).message == "Подсказка из задания"
    assert "должна быть числом" in verdict(check, {"answer": "шесть"}).message
    assert verdict(Check("answer", "equal", "Ответ", expected=5), {"answer": 6}).message.startswith("Значение")


def test_grade_quiz_requires_exact_set():
    questions = [
        Question("q1", "", ["a", "b", "c"], frozenset({0}), "", "l"),
        Question("q2", "", ["a", "b", "c"], frozenset({0, 2}), "", "l"),
        Question("q3", "", ["a", "b", "c"], frozenset({1}), "", "l"),
    ]
    score, marks = grade_quiz(questions, {"q1": [0], "q2": [0], "q3": []})
    assert score == 1 and marks == [True, False, False]
    assert grade_quiz(questions, {"q1": [0], "q2": [2, 0], "q3": [1]})[0] == 3
    assert grade_quiz(questions, {"q2": [0, 1, 2]})[0] == 0


def test_harness_collects_output_values_and_errors():
    harness = load_harness()
    result = harness.run_code("x = 2 + 2\nprint('готово', x)\nitems = (1, 2.5, 'a')", ["x", "items", "nope"])
    assert result["stdout"] == "готово 4\n" and result["error"] is None
    assert result["values"] == {"x": 4, "items": [1, 2.5, "a"]}

    result = harness.run_code("a = 1\nb = a / 0\n", ["a", "b"])
    assert "ZeroDivisionError" in result["error"] and "строка 2: b = a / 0" in result["error"]
    assert result["values"] == {"a": 1}

    assert "Синтаксическая ошибка в строке 1" in harness.run_code("x = (", [])["error"]


def test_harness_converts_numpy_and_pandas_values():
    numpy = pytest.importorskip("numpy")
    pandas = pytest.importorskip("pandas")
    harness = load_harness()
    namespace = {
        "i": numpy.int64(7),
        "f": numpy.float64(0.5),
        "flag": numpy.bool_(True),
        "nan": float("nan"),
        "arr": numpy.array([1.5, 2.5]),
        "series": pandas.Series([1, 2], index=["a", "b"]),
        "index": pandas.Index(["x", "y"]),
        "mapping": {"k": numpy.float64(1.25)},
        "frame": pandas.DataFrame({"a": [1]}),
    }
    plain = {name: harness.to_plain(value) for name, value in namespace.items()}
    assert plain == {
        "i": 7, "f": 0.5, "flag": True, "nan": None, "arr": [1.5, 2.5],
        "series": [1, 2], "index": ["x", "y"], "mapping": {"k": 1.25}, "frame": None,
    }
    assert type(plain["i"]) is int and type(plain["flag"]) is bool


def test_harness_returns_figures():
    pytest.importorskip("matplotlib")
    harness = load_harness()
    code = "import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\nplt.show()\n"
    result = harness.run_code(code, [])
    assert result["error"] is None and len(result["images"]) == 1
    assert "Предупреждение" not in result["stdout"]
