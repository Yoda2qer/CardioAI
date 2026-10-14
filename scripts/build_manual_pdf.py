"""Собирает PDF-версию инструкции по установке: INSTALL.md → docs/INSTALL.pdf.

    python scripts/build_manual_pdf.py

Нужна библиотека fpdf2 (есть в requirements-dev.txt) и шрифты с кириллицей:
в Windows используются Segoe UI и Consolas, в Linux и macOS — DejaVu или Arial.
"""

import logging
import re
import sys
from datetime import date
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace, TextStyle
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "INSTALL.md"
TARGET = ROOT / "docs" / "INSTALL.pdf"

VIOLET = (90, 47, 194)
BLUE = (36, 67, 196)
INK = (23, 22, 58)
MUTED = (98, 98, 139)

# Наборы шрифтов: обычный, жирный, курсив, моноширинный, моноширинный жирный.
FONT_SETS = [
    ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeuii.ttf",
     "C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/consolab.ttf"],
    ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"],
    ["/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf", "/System/Library/Fonts/Supplemental/Courier New.ttf",
     "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"],
]


def find_fonts() -> list[str]:
    for fonts in FONT_SETS:
        if all(Path(f).exists() for f in fonts):
            return fonts
    raise SystemExit("Не найдены шрифты с кириллицей (Segoe UI, DejaVu или Arial). Укажите их в FONT_SETS.")


def markdown_to_html(text: str) -> str:
    # Оглавление со ссылками на якоря в PDF не нужно: страницы и так идут по порядку.
    text = re.sub(r"\[([^\]]+)\]\(#[^)]+\)", r"\1", text)
    # Врезки GitHub (> [!NOTE]) превращаются в обычные цитаты с жирным заголовком.
    text = re.sub(r"^> \[!(NOTE|WARNING|TIP|IMPORTANT|CAUTION)\]\n", "", text, flags=re.M)
    html = MarkdownIt("commonmark").enable("table").render(text)
    # fpdf2 не поддерживает теги внутри ячеек таблиц: оставляем в ячейках только текст.
    def plain_cell(match: re.Match) -> str:
        tag, body = match.group(1), match.group(2)
        # Выравнивание по ширине в узких ячейках даёт огромные пробелы, поэтому — по левому краю.
        return f'<{tag} align="left">{re.sub(r"<[^>]+>", "", body) or " "}</{tag}>'

    return re.sub(r"<(td|th)>(.*?)</\1>", plain_cell, html, flags=re.S)


class Manual(FPDF):
    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_font("Body", size=8.5)
        self.set_text_color(*MUTED)
        self.cell(0, 8, f"CardioAI · установка и запуск · стр. {self.page_no()}", align="C")


def build() -> Path:
    regular, bold, italic, mono, mono_bold = find_fonts()
    pdf = Manual(format="A4")
    pdf.set_title("CardioAI: установка и запуск")
    pdf.set_author("CardioAI")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_font("Body", "", regular)
    pdf.add_font("Body", "B", bold)
    pdf.add_font("Body", "I", italic)
    pdf.add_font("Body", "BI", bold)
    pdf.add_font("Mono", "", mono)
    pdf.add_font("Mono", "B", mono_bold)

    # Титульная страница.
    pdf.add_page()
    pdf.set_fill_color(*VIOLET)
    pdf.rect(0, 0, 210, 70, style="F")
    pdf.set_fill_color(47, 85, 230)
    pdf.rect(0, 70, 210, 4, style="F")
    pdf.set_xy(18, 24)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Body", "B", 30)
    pdf.cell(0, 14, "CardioAI")
    pdf.set_xy(18, 42)
    pdf.set_font("Body", size=14)
    pdf.cell(0, 8, "Аналитика данных и машинное обучение")
    pdf.set_xy(18, 92)
    pdf.set_text_color(*INK)
    pdf.set_font("Body", "B", 22)
    pdf.multi_cell(0, 11, "Установка и запуск\nобразовательной платформы")
    pdf.set_x(18)
    pdf.set_font("Body", size=11)
    pdf.set_text_color(*MUTED)
    pdf.ln(4)
    pdf.multi_cell(0, 6, "Руководство для администратора курса: установка на компьютер или сервер, "
                         "первый запуск, приглашение слушателей, настройки, резервное копирование и решение проблем.")
    pdf.ln(4)
    pdf.set_x(18)
    pdf.cell(0, 6, f"Версия от {date.today():%d.%m.%Y} · github.com/Toster1012/CardioAI")

    html = markdown_to_html(SOURCE.read_text(encoding="utf-8"))
    # Заголовок первого уровня уже на титульной странице.
    html = re.sub(r"<h1>.*?</h1>", "", html, count=1, flags=re.S)

    pdf.add_page()
    pdf.set_text_color(*INK)
    # Таблицы fpdf2 заливает текущим цветом заливки — после титульной страницы он синий.
    pdf.set_fill_color(244, 240, 255)
    pdf.set_draw_color(224, 226, 244)
    html = html.replace("<table>", '<table width="100%" cellpadding="2">')
    pdf.write_html(
        html,
        font_family="Body",
        table_line_separators=True,
        li_prefix_color=VIOLET,
        tag_styles={
            "h2": TextStyle(font_family="Body", font_style="B", font_size_pt=15, color=VIOLET, t_margin=6, b_margin=2),
            "h3": TextStyle(font_family="Body", font_style="B", font_size_pt=12, color=BLUE, t_margin=4, b_margin=1),
            "p": TextStyle(font_family="Body", font_size_pt=10.5, color=INK, b_margin=2),
            "li": TextStyle(font_family="Body", font_size_pt=10.5, color=INK),
            "code": FontFace(family="Mono", size_pt=9.5, color=VIOLET),
            "pre": TextStyle(font_family="Mono", font_size_pt=9, color=INK, fill_color=(244, 240, 255), t_margin=1, b_margin=3, l_margin=4),
            "blockquote": TextStyle(font_family="Body", font_size_pt=10, color=(54, 53, 95), l_margin=6, t_margin=1, b_margin=3),
            "a": FontFace(color=BLUE),
        },
    )
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(TARGET))
    return TARGET


if __name__ == "__main__":
    # fontTools сообщает о каждой таблице шрифта, которую не умеет урезать; на результат это не влияет.
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    path = build()
    print(f"Готово: {path.relative_to(ROOT)}")
    sys.exit(0)
