"""Загрузка курса из каталога content/: разделы, уроки, практики и тесты.

Содержимое читается один раз при старте и проверяется на целостность, чтобы
ошибка в YAML обнаруживалась сразу, а не на странице у слушателя.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
from pathlib import Path

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.container import container_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from .config import get_settings

QUIZ_SIZE = 15
CHECK_TYPES = {"equal", "approx", "range", "set", "list_approx", "dict_approx"}

# Вид врезки -> заголовок по умолчанию.
CALLOUTS = {
    "note": "Обратите внимание",
    "clinic": "Клинический пример",
    "warning": "Осторожно",
    "summary": "Главное",
}


class ContentError(Exception):
    pass


# --- Markdown ---------------------------------------------------------------

_formatter = HtmlFormatter(nowrap=True)


def _highlight(code: str, lang: str, _attrs: str) -> str:
    if lang == "output":
        return f'<pre class="output"><code>{escape(code)}</code></pre>'
    try:
        lexer = get_lexer_by_name(lang) if lang else None
    except ClassNotFound:
        lexer = None
    body = highlight(code, lexer, _formatter) if lexer else escape(code)
    return f'<pre class="highlight"><code>{body}</code></pre>'


def _callout_renderer(kind: str):
    def render(self, tokens, idx, _options, _env):
        token = tokens[idx]
        if token.nesting != 1:
            return "</div>\n"
        title = token.info.strip()[len(kind):].strip() or CALLOUTS[kind]
        return (
            f'<div class="callout callout-{kind}">'
            f'<div class="callout-title">{escape(title)}</div>\n'
        )

    return render


def _make_markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"highlight": _highlight}).enable("table")
    for kind in CALLOUTS:
        md.use(container_plugin, name=kind, render=_callout_renderer(kind))
    return md


_md = _make_markdown()


def render_markdown(text: str) -> str:
    return _md.render(text)


def render_inline(text: str) -> str:
    return _md.renderInline(str(text))


# --- Модель курса -----------------------------------------------------------


@dataclass
class Check:
    var: str
    type: str
    label: str
    expected: object = None
    tol: float = 1e-6
    min: float | None = None
    max: float | None = None
    hint: str = ""


@dataclass
class Practice:
    statement_html: str
    starter: str
    solution: str
    packages: list[str]
    datasets: list[str]
    checks: list[Check]

    @property
    def var_names(self) -> list[str]:
        return list(dict.fromkeys(check.var for check in self.checks))


@dataclass
class Lesson:
    id: str
    type: str  # theory | practice
    title: str
    minutes: int
    number: int
    section: "Section" = field(repr=False)
    html: str = ""
    practice: Practice | None = None

    @property
    def is_practice(self) -> bool:
        return self.type == "practice"


@dataclass
class Question:
    id: str
    text_html: str
    options_html: list[str]
    correct: frozenset[int]
    explanation_html: str
    lesson_id: str

    @property
    def multiple(self) -> bool:
        return len(self.correct) > 1


@dataclass
class Section:
    id: str
    number: int
    title: str
    description: str
    lessons: list[Lesson] = field(default_factory=list)
    quiz: list[Question] = field(default_factory=list)


@dataclass
class Course:
    title: str
    sections: list[Section]

    def __post_init__(self):
        self._lessons = {lesson.id: lesson for s in self.sections for lesson in s.lessons}
        self._sections = {s.id: s for s in self.sections}

    @property
    def lessons(self) -> list[Lesson]:
        return list(self._lessons.values())

    def lesson(self, lesson_id: str) -> Lesson | None:
        return self._lessons.get(lesson_id)

    def section(self, section_id: str) -> Section | None:
        return self._sections.get(section_id)


# --- Загрузка ---------------------------------------------------------------


def _read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContentError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContentError(f"{path}: ожидался словарь")
    return data


def _load_practice(path: Path) -> Practice:
    data = _read_yaml(path)
    checks = []
    for raw in data.get("checks") or []:
        check = Check(
            var=raw["var"],
            type=raw["type"],
            label=raw.get("label", raw["var"]),
            expected=raw.get("expected"),
            tol=float(raw.get("tol", 1e-6)),
            min=raw.get("min"),
            max=raw.get("max"),
            hint=raw.get("hint", ""),
        )
        if check.type not in CHECK_TYPES:
            raise ContentError(f"{path}: неизвестный тип проверки {check.type!r}")
        if check.type == "range":
            if check.min is None and check.max is None:
                raise ContentError(f"{path}: у проверки {check.var} нет границ")
        elif check.expected is None:
            raise ContentError(f"{path}: у проверки {check.var} нет expected")
        checks.append(check)
    if not checks:
        raise ContentError(f"{path}: нет ни одной проверки")
    for key in ("statement", "starter", "solution"):
        if not str(data.get(key) or "").strip():
            raise ContentError(f"{path}: не заполнено поле {key}")
    return Practice(
        statement_html=render_markdown(data["statement"]),
        starter=data["starter"],
        solution=data["solution"],
        packages=list(data.get("packages") or []),
        datasets=list(data.get("datasets") or []),
        checks=checks,
    )


def _load_quiz(path: Path, section: Section, lesson_ids: set[str]) -> list[Question]:
    questions = []
    for i, raw in enumerate(_read_yaml(path).get("questions") or [], start=1):
        where = f"{path}: вопрос {i}"
        options = raw.get("options") or []
        correct = frozenset(n for n, opt in enumerate(options) if opt.get("correct"))
        if len(options) < 3:
            raise ContentError(f"{where}: нужно не меньше трёх вариантов ответа")
        if not correct or len(correct) == len(options):
            raise ContentError(f"{where}: должен быть хотя бы один верный и один неверный вариант")
        if raw.get("lesson") not in lesson_ids:
            raise ContentError(f"{where}: поле lesson должно указывать на урок этого раздела")
        if not str(raw.get("explanation") or "").strip():
            raise ContentError(f"{where}: нет пояснения")
        questions.append(
            Question(
                id=f"{section.id}-q{i}",
                text_html=render_inline(raw["text"]),
                options_html=[render_inline(opt["text"]) for opt in options],
                correct=correct,
                explanation_html=render_inline(raw["explanation"]),
                lesson_id=raw["lesson"],
            )
        )
    if len(questions) != QUIZ_SIZE:
        raise ContentError(f"{path}: в тесте должно быть {QUIZ_SIZE} вопросов, найдено {len(questions)}")
    return questions


def load_course(content_dir: Path) -> Course:
    data = _read_yaml(content_dir / "course.yaml")
    sections: list[Section] = []
    seen: set[str] = set()
    for s_num, s_raw in enumerate(data.get("sections") or [], start=1):
        section = Section(
            id=s_raw["id"], number=s_num, title=s_raw["title"], description=s_raw.get("description", "")
        )
        section_dir = content_dir / s_raw["dir"]
        for l_num, l_raw in enumerate(s_raw.get("lessons") or [], start=1):
            lesson = Lesson(
                id=l_raw["id"],
                type=l_raw["type"],
                title=l_raw["title"],
                minutes=int(l_raw.get("minutes", 10)),
                number=l_num,
                section=section,
            )
            if lesson.id in seen:
                raise ContentError(f"Повторяющийся id урока: {lesson.id}")
            seen.add(lesson.id)
            path = section_dir / l_raw["file"]
            if lesson.type == "theory":
                try:
                    lesson.html = render_markdown(path.read_text(encoding="utf-8"))
                except OSError as exc:
                    raise ContentError(f"{path}: {exc}") from exc
            elif lesson.type == "practice":
                lesson.practice = _load_practice(path)
            else:
                raise ContentError(f"{lesson.id}: неизвестный тип урока {lesson.type!r}")
            section.lessons.append(lesson)
        section.quiz = _load_quiz(section_dir / "quiz.yaml", section, {l.id for l in section.lessons})
        sections.append(section)
    if not sections:
        raise ContentError("В course.yaml нет разделов")
    return Course(title=data.get("title", "CardioAI"), sections=sections)


@lru_cache
def get_course() -> Course:
    return load_course(get_settings().content_dir)
