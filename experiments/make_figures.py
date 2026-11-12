"""Графики для конкурсной работы и презентации из experiments/results/*_test.json → docs/figures/."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "experiments" / "results"
OUT = ROOT / "docs" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": "#888", "axes.labelcolor": "#333",
                     "xtick.color": "#333", "ytick.color": "#333"})
NAVY, ACCENT, GREY, LIGHT = "#1f3b5c", "#c2410c", "#9aa5b1", "#cbd2d9"


def load(name):
    return json.loads((RES / name).read_text())


def bar_labels(ax, bars):
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.015, f"{b.get_height():.2f}",
                ha="center", va="bottom", fontsize=8.5, color="#222")


def fig_impact():
    m = load("E2_impact_test.json")["methods"]
    keys = [("M1_keyword", "BM25\n(ключевые слова)"), ("M2_rag", "Семантический\nRAG"),
            ("M3_graph_d2", "Только граф\n(глубина 2)"), ("M4_hybrid", "Гибрид\nEIS")]
    comp = [m[k]["micro"]["components"]["f1"] for k, _ in keys]
    docs = [m[k]["micro"]["documents"]["f1"] for k, _ in keys]
    chain = [m[k]["chain_recall_mean"] for k, _ in keys]
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=200)
    x = range(len(keys))
    w = 0.26
    b1 = ax.bar([i - w for i in x], comp, w, color=[GREY] * 3 + [NAVY], label="F1 — затронутые компоненты")
    b2 = ax.bar(list(x), docs, w, color=[LIGHT] * 3 + ["#4a6b8c"], label="F1 — документы на пересмотр")
    b3 = ax.bar([i + w for i in x], chain, w, color=["#e4e7eb"] * 3 + [ACCENT], label="Полнота цепочек")
    for bs in (b1, b2, b3):
        bar_labels(ax, bs)
    ax.set_xticks(list(x), [lbl for _, lbl in keys])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("значение метрики")
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncol=3, bbox_to_anchor=(0, 1.13))
    fig.tight_layout()
    fig.savefig(OUT / "chart_impact.png")
    plt.close(fig)


def fig_contradictions():
    m = load("E3_contradictions_test.json")["methods"]
    names = list(m)
    labels = {"C1": "Сходство\nфрагментов", "C2": "Правила\nбез графа", "C3": "Гибрид EIS\n(правила + граф)"}
    rec = [m[k]["recall"] for k in names]
    prec = [m[k]["precision"] for k in names]
    fig, ax = plt.subplots(figsize=(5.6, 3.2), dpi=200)
    x = range(len(names))
    w = 0.36
    b1 = ax.bar([i - w / 2 for i in x], rec, w, color=[GREY, GREY, NAVY], label="Полнота (из 10 внесённых)")
    b2 = ax.bar([i + w / 2 for i in x], prec, w, color=[LIGHT, LIGHT, "#4a6b8c"], label="Точность")
    bar_labels(ax, b1)
    bar_labels(ax, b2)
    ax.set_xticks(list(x), [labels[k[:2]] for k in names])
    ax.set_ylim(0, 1.15)
    ax.legend(frameon=False, fontsize=8, loc="upper left", ncol=2, bbox_to_anchor=(0, 1.12))
    fig.tight_layout()
    fig.savefig(OUT / "chart_contradictions.png")
    plt.close(fig)


def fig_ablation():
    m = load("E2_impact_test.json")["methods"]
    rows = [("M4_hybrid", "Полный метод", "components"), ("M4_ablation_no_physics", "без учёта физики параметра", "components"),
            ("M4_ablation_no_load_path", "без пути нагрузки", "components"),
            ("M4_hybrid", "Полный метод", "documents"), ("M4_ablation_no_doc_filter", "без фильтра документов", "documents")]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.3), dpi=200, gridspec_kw={"width_ratios": [3, 2]})
    for ax, metric, title in [(axes[0], "components", "F1 по компонентам"), (axes[1], "documents", "F1 по документам")]:
        sel = [(lbl, m[k]["micro"][metric]["f1"]) for k, lbl, mt in rows if mt == metric]
        y = range(len(sel))[::-1]
        bars = ax.barh(list(y), [v for _, v in sel], color=[NAVY] + [GREY] * (len(sel) - 1), height=0.55)
        ax.set_yticks(list(y), [lbl for lbl, _ in sel], fontsize=8.5)
        ax.set_xlim(0.6, 1.0)
        ax.set_title(title, fontsize=9.5, loc="left")
        for b in bars:
            ax.text(b.get_width() + 0.005, b.get_y() + b.get_height() / 2, f"{b.get_width():.2f}", va="center", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(OUT / "chart_ablation.png")
    plt.close(fig)


def fig_architecture():
    fig, ax = plt.subplots(figsize=(7.4, 4.0), dpi=200)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 56)
    ax.axis("off")

    def box(x, y, w, h, title, sub="", fc="#ffffff", ec=NAVY, tc="#111", bold=True):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3,rounding_size=1.2", fc=fc, ec=ec, lw=1.2))
        ax.text(x + w / 2, y + h - 2.6, title, ha="center", va="top", fontsize=8.6, color=tc,
                weight="bold" if bold else "normal")
        if sub:
            ax.text(x + w / 2, y + h - 6.4, sub, ha="center", va="top", fontsize=6.2, color="#444" if tc == "#111" else "#dde",
                    linespacing=1.3)

    def arrow(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=9, color="#555", lw=1))

    box(1, 34, 17, 19, "Документы", "PDF, DOCX, XLSX,\nCSV, TXT,\nскан PNG/JPEG", fc="#f3f4f6")
    box(21.5, 34, 21, 19, "Разбор и OCR", "PyMuPDF, python-docx,\nopenpyxl, Tesseract\nфрагменты, координаты\nпроверка файлов", fc="#ffffff")
    box(46, 34, 23, 19, "Извлечение", "морфология pymorphy3\nсловарь параметров\nединицы → СИ\nтребования, связи,\nматериалы, испытания")
    box(73, 34, 26, 19, "Граф знаний", "NetworkX + PostgreSQL\nтипизированные узлы и\nсвязи, у каждой связи —\nдоказательство\n(документ, стр., цитата)",
        fc=NAVY, ec=NAVY, tc="#ffffff")
    arrow(18.3, 43.5, 21.7, 43.5)
    arrow(42.3, 43.5, 45.7, 43.5)
    arrow(69.3, 43.5, 72.7, 43.5)

    box(1, 9, 23, 19, "Анализ изменений", "обход графа с учётом\nфизики параметра,\nпроизводные величины,\nформальная перепроверка")
    box(26, 9, 23, 19, "Противоречия", "1 формальные правила\n2 LLM (опционально)\n3 проверка по графу\nстатус и уверенность")
    box(51, 9, 23, 19, "Гибридный поиск", "BM25 + e5-small,\nслияние RRF;\nпомощник с\nобязательными ссылками")
    box(76, 9, 23, 19, "Интерфейс и API", "FastAPI, React,\nReact Flow; отчёты\nDOCX/PDF; роли,\nжурнал, изоляция", fc="#f3f4f6")
    for cx in (12.5, 37.5, 62.5):
        arrow(86, 33.7, cx, 28.3)
    arrow(74.3, 18.5, 75.7, 18.5)
    ax.text(50, 3.2, "LLM подключается через интерфейс (Ollama / совместимый API), внешние — только с разрешения; "
            "без LLM система работает полностью", ha="center", fontsize=7.2, color="#555", style="italic")
    fig.savefig(OUT / "architecture.png", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    fig_impact()
    fig_contradictions()
    fig_ablation()
    fig_architecture()
    print("ok:", sorted(p.name for p in OUT.glob("*.png")))
