#!/usr/bin/env python3
"""Сборка практикума (сборника заданий) из ноутбуков seminars/N.ipynb и notes/N.ipynb.

Запуск из корня репозитория:  python3 book/build.py
Результат: book/practicum.tex и book/practicum.pdf (pdflatex, три прохода).
"""
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / 'book'
N_SEMINARS = 8
YEAR = 2026

# ---------------------------------------------------------------- фильтры ячеек
ANSWER_STUBS = {'{Введите ваш ответ здесь}', '**Ответ:**', 'Ваш ответ здесь', 'Ваши ответы здесь', ''}
SETUP_HEADINGS = ('Подготовка окружения', 'Импорт библиотек')
SETUP_LINE = re.compile(r'^\s*(import |from \S+ import |%|!pip|plt\.rcParams)')


def cell_text(c):
    return ''.join(c['source'])


def is_answer_stub(md):
    s = md.strip()
    if s in ANSWER_STUBS:
        return True
    # шаблоны ответа с пропусками: «Период дискретизации равен {}. ...»
    return '{}' in s and not s.startswith('#') and len(s) < 300


def given_code(src):
    """Код условия задачи или None, если ячейка – пустая заготовка или только настройка окружения."""
    lines = [l for l in src.splitlines() if not l.lstrip().startswith('!pip')]
    meaningful = [l for l in lines if l.strip() and not l.strip().startswith('#')]
    if not meaningful:
        return None
    if all(SETUP_LINE.match(l) for l in meaningful):
        return None
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines)


# ---------------------------------------------------------------- разметка
def tidy_inline_math(t):
    """'$ x $' -> '$x$' вне блоков кода (иначе pandoc не распознаёт формулу)."""
    out, fence = [], False
    for line in t.split('\n'):
        if line.lstrip().startswith('```'):
            fence = not fence
            out.append(line)
            continue
        if fence or '$$' in line:
            out.append(line)
            continue
        parts = line.split('$')
        if len(parts) % 2 == 1:
            for j in range(1, len(parts), 2):
                parts[j] = cyrillic_in_math(parts[j].strip(' '))
            line = '$'.join(parts)
        out.append(line)
    return '\n'.join(out)


CYR_RUN = re.compile(r'[А-Яа-яЁё][А-Яа-яЁё.]*(?:\s+[А-Яа-яЁё][А-Яа-яЁё.]*)*')


def cyrillic_in_math(m):
    """Кириллица внутри формулы (например, $-3 дБ$) оборачивается в \\text{}."""
    if '\\text' in m or '\\mathrm' in m or '\\operatorname' in m:
        return m
    return CYR_RUN.sub(lambda r: '\\text{' + r.group(0) + '}', m)


def heading(level, title):
    return f'\n{"#" * level} {title.strip()} {{-}}\n'


def split_headings(md):
    """Разбивает markdown на элементы ('h', уровень, текст) и ('t', текст) с учётом блоков кода."""
    items, buf, fence = [], [], False
    for line in md.split('\n'):
        if line.lstrip().startswith('```'):
            fence = not fence
        m = None if fence else re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            if buf:
                items.append(('t', '\n'.join(buf)))
                buf = []
            items.append(('h', len(m.group(1)), m.group(2)))
        else:
            buf.append(line)
    if buf:
        items.append(('t', '\n'.join(buf)))
    return items


def verbatim(code, frame=True):
    opts = 'fontsize=\\small, breaklines, breakanywhere' + (', frame=single, framesep=2mm' if frame else '')
    return f'\n```{{=latex}}\n\\begin{{Verbatim}}[{opts}]\n{code}\n\\end{{Verbatim}}\n```\n'


# ---------------------------------------------------------------- главы
def notes_markdown(n):
    nb = json.loads((ROOT / f'notes/{n}.ipynb').read_text(encoding='utf-8'))
    parts = [heading(2, 'Краткие сведения')]
    for c in nb['cells']:
        t = cell_text(c)
        if c['cell_type'] != 'markdown' or 'colab-badge' in t:
            continue
        for it in split_headings(tidy_inline_math(t)):
            if it[0] == 't':
                parts.append(it[1])
            elif it[1] == 1:
                continue                                   # заголовок занятия
            else:
                parts.append(heading(min(it[1] + 1, 4), it[2]))
    return '\n'.join(parts)


def seminar_markdown(n):
    nb = json.loads((ROOT / f'seminars/{n}.ipynb').read_text(encoding='utf-8'))
    title, body = None, []
    has_parts = any(re.search(r'^#+\s+Часть \d', cell_text(c), re.M) for c in nb['cells'])
    tasks_opened = False
    pending_setup = None
    for c in nb['cells']:
        t = cell_text(c)
        if c['cell_type'] == 'code':
            code = given_code(t)
            if code is None:
                continue
            if pending_setup:
                body.append(heading(2, 'Подготовка рабочей среды'))
                if 'def ' in code:
                    body.append('Во всех заданиях занятия используется вспомогательная функция:')
                else:
                    body.append('Используемые в заданиях аудиофайлы загружаются из репозитория командами:')
                pending_setup = None
            body.append(verbatim(code))
            continue
        if 'colab-badge' in t or is_answer_stub(t):
            continue
        for it in split_headings(tidy_inline_math(t)):
            if it[0] == 't':
                body.append(it[1])
                continue
            level, text = it[1], it[2].strip()
            if level == 1:
                m = re.match(r'Практическое занятие №\d+:\s*(.*)', text)
                title = m.group(1) if m else text
                continue
            if level == 2 and any(text.startswith(s) for s in SETUP_HEADINGS):
                pending_setup = text
                continue
            pending_setup = None
            if re.match(r'Часть \d', text):
                body.append(heading(2, text))
            elif re.match(r'Задание \d', text):
                if not has_parts and not tasks_opened:
                    body.append(heading(2, 'Задания'))
                    tasks_opened = True
                body.append(heading(3, text.rstrip('.')))
            else:
                body.append(heading(4, text))
    return title, '\n'.join(body)


BREAK_AFTER = re.compile(r'(\\_|\\textquotesingle\{\}|[.,(=/:])')


def breakable_texttt(tex):
    """Разрешает перенос строки внутри \\texttt{...} после . , ( = / : _ и кавычек (длинные фрагменты кода в тексте)."""
    out, i, key = [], 0, '\\texttt{'
    while True:
        j = tex.find(key, i)
        if j < 0:
            out.append(tex[i:])
            return ''.join(out)
        k, depth = j + len(key), 1
        while depth:
            depth += {'{': 1, '}': -1}.get(tex[k], 0)
            k += 1
        inner = tex[j + len(key):k - 1]
        out.append(tex[i:j] + key + BREAK_AFTER.sub(lambda m: m.group(1) + '\\allowbreak{}', inner) + '}')
        i = k


def chapter_latex(n):
    title, sem = seminar_markdown(n)
    md = f'# {title}\n\n' + notes_markdown(n) + '\n\n' + sem
    tex = subprocess.run(
        ['pandoc', '-f', 'markdown+tex_math_single_backslash+lists_without_preceding_blankline-auto_identifiers',
         '-t', 'latex', '--no-highlight',
         '--top-level-division=chapter', '--wrap=preserve'],
        input=md, capture_output=True, text=True, check=True).stdout
    tex = breakable_texttt(tex)
    # для печати: адрес ссылки выводится явно
    tex = re.sub(r'\\href\{([^}]*)\}\{([^}]*)\}',
                 lambda m: f'\\url{{{m.group(1)}}}' if m.group(2).startswith(('http', '\\url'))
                 else f'{m.group(2)} (\\url{{{m.group(1)}}})', tex)
    # блоки кода из заметок
    tex = tex.replace('\\begin{verbatim}', '\\begin{Verbatim}[fontsize=\\small, breaklines, breakanywhere]') \
             .replace('\\end{verbatim}', '\\end{Verbatim}')
    # главы нумеруются; разделы внутри – с номерами из самих ноутбуков
    tex = re.sub(r'\\chapter\*\{(.*?)\}\n\\addcontentsline\{toc\}\{chapter\}\{.*?\}\n',
                 r'\\chapter{\1}\n', tex, count=1, flags=re.S)
    return tex


# ---------------------------------------------------------------- шаблон книги
PREAMBLE = r'''\documentclass[12pt,a4paper,openany]{book}

\usepackage{graphicx} % Required for inserting images
\usepackage{amssymb,amsmath}
\usepackage{indentfirst} % отступ первых абзацев в разделе

% для поддержки русского языка
\usepackage{cmap} % для кодировки шрифтов в pdf
\usepackage[T2A]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[russian]{babel}

\pagestyle{plain}
\usepackage{geometry}
\geometry{a4paper,
    left=20mm,
    top=20mm,
    right=20mm,
    bottom=20mm
}

% для содержимого, перенесённого из ноутбуков
\usepackage{longtable,booktabs,array,calc}
\usepackage{fvextra}
\usepackage{lastpage}
\usepackage[hidelinks]{hyperref}
\usepackage{xurl}
\setlength{\emergencystretch}{3em}
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\addto\captionsrussian{\renewcommand{\chaptername}{Занятие}}
\setcounter{tocdepth}{1}
\newcommand{\todo}[1]{\fbox{\small #1}}

%UNICODE%
'''

FRONT = r'''
\begin{document}

\fontsize{14}{18}\selectfont

\thispagestyle{empty}

\begin{center}
    МИНИСТЕРСТВО НАУКИ И ВЫСШЕГО ОБРАЗОВАНИЯ РОССИЙСКОЙ ФЕДЕРАЦИИ

    \medskip

    Национальный исследовательский Нижегородский государственный университет им. Н.И. Лобачевского

    \vfill

    \textbf{А.В. Коржиманов}

    \vspace{28pt}

    \textbf{ЦИФРОВАЯ ОБРАБОТКА СИГНАЛОВ\\ ПРАКТИКУМ}

    \vspace{28pt}

    Учебно-методическое пособие

    \vspace{42pt}

    Рекомендовано \todo{[орган, рекомендующий издание]} для студентов ННГУ, обучающихся по направлению подготовки \todo{[код и название направления]}

    \vfill

    Нижний Новгород

    %YEAR%
\end{center}

\newpage
\thispagestyle{empty}

УДК \todo{[указать]}\par
ББК \todo{[указать]}\par
\hspace{10mm}К-66

\vfill

\begin{center}
    Рецензенты:\\
    \todo{[учёная степень, звание]} \textbf{\todo{[И.О. Фамилия]}}\\
    \todo{[учёная степень, звание]} \textbf{\todo{[И.О. Фамилия]}}
\end{center}

\vspace{28pt}

К-66 Коржиманов А.В. ЦИФРОВАЯ ОБРАБОТКА СИГНАЛОВ. ПРАКТИКУМ: Учебно-методическое пособие. – Нижний Новгород: Нижегородский госуниверситет, %YEAR%. – \pageref*{LastPage}~с.

\vspace{28pt}

Пособие содержит задания восьми практических занятий по цифровой обработке сигналов: дискретизация и спектральный анализ, модуляция, свёртка и корреляция, Z-преобразование, случайные сигналы и спектральная плотность мощности, анализ и синтез цифровых фильтров, нелинейная и адаптивная фильтрация, частотно-временной анализ и вейвлет-преобразования. Каждое занятие открывается краткими сведениями, необходимыми для выполнения заданий: формулами, описанием функций библиотек языка Python и перечнем типичных ошибок. Задания выполняются в среде Jupyter или Google Colab и сопровождаются контрольными вопросами.

Для студентов радиофизического факультета ННГУ, изучающих курс «Цифровая обработка сигналов».

\vspace{28pt}

\begin{center}
    Ответственный за выпуск:\\
    \todo{[должность]} \textbf{\todo{[И.О. Фамилия]}}
\end{center}

\vfill

\begin{flushright}
УДК \todo{[указать]}

ББК \todo{[указать]}

© Национальный исследовательский\\
Нижегородский государственный\\
университет им. Н.И. Лобачевского, %YEAR%
\end{flushright}


\tableofcontents

\newpage

\chapter*{Введение}
\addcontentsline{toc}{chapter}{\protect\numberline{}Введение}

Практикум составлен на основе практических занятий, сопровождающих курс лекций «Цифровая обработка сигналов», который автор читает студентам радиофизического факультета Нижегородского государственного университета имени Н.И. Лобачевского. Восемь занятий практикума следуют за восемью лекциями курса: от дискретизации сигналов и дискретного преобразования Фурье через свёртку, корреляционный и спектральный анализ к анализу и синтезу цифровых фильтров, адаптивной фильтрации, частотно-временному анализу и вейвлет-преобразованиям.

Цель практикума --- научить применять методы цифровой обработки сигналов на практике: генерировать и анализировать сигналы, проектировать фильтры, оценивать спектры, сравнивать между собой различные методы и делать обоснованные выводы о том, какой из них лучше подходит для конкретной задачи. Большинство заданий построено как численный эксперимент: требуется не только получить результат, но и исследовать его зависимость от параметров и объяснить наблюдаемое поведение.

Задания выполняются на языке Python с использованием библиотек NumPy, SciPy и Matplotlib, а в последнем занятии --- библиотеки PyWavelets. Для каждого занятия подготовлен ноутбук Jupyter, который можно открыть в сервисе Google Colab, не устанавливая ничего на свой компьютер. Ноутбуки, пояснительные заметки и необходимые аудиофайлы размещены в открытом репозитории \url{https://github.com/korzhimanov/dsp-seminars}: задания находятся в каталоге \texttt{seminars}, заметки --- в каталоге \texttt{notes}, данные --- в каталоге \texttt{data}. Порядок работы с репозиторием и Google Colab описан в кратких сведениях к первому занятию.

Каждая глава соответствует одному занятию и состоит из двух частей. Раздел <<Краткие сведения>> содержит формулы, описание используемых функций библиотек и перечень типичных ошибок; он не заменяет лекций, а служит справочником при выполнении заданий. Далее следуют сами задания, сгруппированные по темам. Фрагменты программного кода, приведённые в условиях, входят в условие задачи: это вспомогательные функции и заготовки, в которых строки с комментарием <<Ваш код здесь>> отмечают места, требующие доработки.

Результатом выполнения каждого задания являются программный код, графики и ответы на контрольные вопросы, записанные непосредственно в ноутбуке. Все графики должны иметь подписи осей с единицами измерения, заголовки и легенды. Ответы на вопросы следует давать в виде кратких, но полных выводов, опирающихся на полученные результаты и теорию, изложенную в лекциях.

Автор надеется, что практикум поможет читателям почувствовать, как теоретические понятия цифровой обработки сигналов превращаются в работающие алгоритмы, и научиться выбирать подходящий инструмент для решения реальных задач.
'''

BIBLIO = r'''
\chapter*{Список литературы}
\addcontentsline{toc}{chapter}{\protect\numberline{}Список литературы}

\section*{Общие вопросы цифровой обработки сигналов}
[1.1] Оппенгейм А., Шафер Р. Цифровая обработка сигналов. --- М.: Техносфера, 2006.

[1.2] Лайонс Р. Цифровая обработка сигналов. 2-е изд. --- М.: Бином-Пресс, 2006.

[1.3] Сергиенко А.Б. Цифровая обработка сигналов. 3-е изд. --- СПб.: БХВ-Петербург, 2011.

[1.4] Smith S. W. The Scientist and Engineer's Guide to Digital Signal Processing. --- San Diego: California Technical Publishing, 1997.

\section*{Спектральный анализ и синтез фильтров}
[2.1] Welch P. D. The use of fast Fourier transform for the estimation of power spectra: A method based on time averaging over short, modified periodograms // IEEE Transactions on Audio and Electroacoustics. --- 1967. --- V. 15. --- P. 70–73.

[2.2] Savitzky A., Golay M. J. E. Smoothing and Differentiation of Data by Simplified Least Squares Procedures // Analytical Chemistry. --- 1964. --- V. 36. --- P. 1627–1639.

[2.3] Parks T. W., McClellan J. H. Chebyshev Approximation for Nonrecursive Digital Filters with Linear Phase // IEEE Transactions on Circuit Theory. --- 1972. --- V. 19. --- P. 189–194.

\section*{Адаптивная фильтрация}
[3.1] Haykin S. Adaptive Filter Theory. 5th ed. --- Upper Saddle River: Pearson, 2014.

[3.2] Kalman R. E. A New Approach to Linear Filtering and Prediction Problems // Journal of Basic Engineering. --- 1960. --- V. 82. --- P. 35–45.

\section*{Вейвлет-преобразования}
[4.1] Добеши И. Десять лекций по вейвлетам. --- Ижевск: НИЦ <<Регулярная и хаотическая динамика>>, 2001.

[4.2] Mallat S. A Wavelet Tour of Signal Processing: The Sparse Way. 3rd ed. --- Burlington: Academic Press, 2009.

[4.3] Donoho D. L., Johnstone I. M. Ideal spatial adaptation by wavelet shrinkage // Biometrika. --- 1994. --- V. 81. --- P. 425–455.

\section*{Программные средства}
[5.1] Virtanen P. et al. SciPy 1.0: Fundamental Algorithms for Scientific Computing in Python // Nature Methods. --- 2020. --- V. 17. --- P. 261–272.

[5.2] Lee G. R., Gommers R., Waselewski F., Wohlfahrt K., O'Leary A. PyWavelets: A Python package for wavelet analysis // Journal of Open Source Software. --- 2019. --- V. 4. --- Art. no. 1237.

\newpage
\thispagestyle{empty}

\begin{center}
    \vspace*{100mm}

    Артем Владимирович \textbf{Коржиманов}

    \vspace{28pt}

    \textbf{ЦИФРОВАЯ ОБРАБОТКА СИГНАЛОВ\\ ПРАКТИКУМ}

    \vspace{14pt}

    \textit{Учебно-методическое пособие}

    \vspace{28pt}

    Компьютерная верстка – А.В. Коржиманов

    \vspace{14pt}

    Федеральное государственное автономное образовательное\\ учреждение высшего образования\\
    «Национальный исследовательский Нижегородский государственный университет им. Н.И. Лобачевского».\\
    603950, Нижний Новгород, пр. Гагарина, 23.
\end{center}

\end{document}
'''

# Символы вне T2A, встречающиеся в тексте ноутбуков
UNICODE_MAP = {
    'α': r'\ensuremath{\alpha}', 'β': r'\ensuremath{\beta}', 'γ': r'\ensuremath{\gamma}',
    'δ': r'\ensuremath{\delta}', 'Δ': r'\ensuremath{\Delta}', 'ε': r'\ensuremath{\varepsilon}',
    'θ': r'\ensuremath{\theta}', 'λ': r'\ensuremath{\lambda}', 'μ': r'\ensuremath{\mu}',
    'π': r'\ensuremath{\pi}', 'σ': r'\ensuremath{\sigma}', 'τ': r'\ensuremath{\tau}',
    'φ': r'\ensuremath{\varphi}', 'ψ': r'\ensuremath{\psi}', 'ω': r'\ensuremath{\omega}',
    'Ω': r'\ensuremath{\Omega}', '≈': r'\ensuremath{\approx}', '≤': r'\ensuremath{\leq}',
    '≥': r'\ensuremath{\geq}', '≠': r'\ensuremath{\neq}', '±': r'\ensuremath{\pm}',
    '×': r'\ensuremath{\times}', '·': r'\ensuremath{\cdot}', '−': r'\ensuremath{-}',
    '→': r'\ensuremath{\to}', '←': r'\ensuremath{\leftarrow}', '⇒': r'\ensuremath{\Rightarrow}',
    '↔': r'\ensuremath{\leftrightarrow}', '∞': r'\ensuremath{\infty}', '√': r'\ensuremath{\surd}',
    '∑': r'\ensuremath{\sum}', '∫': r'\ensuremath{\int}', '°': r'\ensuremath{^\circ}',
    '²': r'\ensuremath{^2}', '³': r'\ensuremath{^3}', '⁻': r'\ensuremath{^-}', '¹': r'\ensuremath{^1}',
    '½': r'\ensuremath{\tfrac12}', '‑': '-', '…': r'\ldots{}', '✓': r'\ensuremath{\checkmark}',
    '∈': r'\ensuremath{\in}', '∝': r'\ensuremath{\propto}', '≫': r'\ensuremath{\gg}',
    '≪': r'\ensuremath{\ll}', '∼': r'\ensuremath{\sim}', '∂': r'\ensuremath{\partial}',
    '⋅': r'\ensuremath{\cdot}', '₀': r'\ensuremath{_0}', '₁': r'\ensuremath{_1}', '₂': r'\ensuremath{_2}',
}
T2A_OK = set('«»—–№’‘“”„©') | {chr(c) for c in range(0x400, 0x460)}


def unicode_decls(tex):
    used = sorted({ch for ch in tex if ord(ch) > 127 and ch not in T2A_OK})
    missing = [ch for ch in used if ch not in UNICODE_MAP]
    if missing:
        sys.exit('Нет соответствия для символов: ' + ' '.join(f'{c} U+{ord(c):04X} {unicodedata.name(c, "?")}'
                                                         for c in missing))
    return '\n'.join(f'\\DeclareUnicodeCharacter{{{ord(ch):04X}}}{{{UNICODE_MAP[ch]}}}' for ch in used)


def main():
    chapters = '\n\n'.join(chapter_latex(n) for n in range(1, N_SEMINARS + 1))
    body = FRONT + '\n' + chapters + '\n' + BIBLIO
    body = body.replace('%YEAR%', str(YEAR))
    tex = PREAMBLE.replace('%UNICODE%', unicode_decls(body)) + body
    (BOOK / 'practicum.tex').write_text(tex, encoding='utf-8')
    if '--no-pdf' in sys.argv:
        return
    for _ in range(3):
        r = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 'practicum.tex'],
                           cwd=BOOK, capture_output=True, text=True, errors='replace')
        if r.returncode:
            print(r.stdout[-3000:])
            sys.exit('pdflatex завершился с ошибкой')
    if '--keep-aux' in sys.argv:
        return
    for ext in ('aux', 'log', 'out', 'toc'):
        (BOOK / f'practicum.{ext}').unlink(missing_ok=True)
    print('Готово:', BOOK / 'practicum.pdf')


if __name__ == '__main__':
    main()
