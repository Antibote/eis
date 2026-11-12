# Конкурсные материалы

| Файл | Что это |
|---|---|
| `EIS_konkursnaya_rabota.docx` / `.pdf` | Конкурсная работа (12 страниц) |
| `slides/project/` | Исходники презентации (10 слайдов, тексты выступления в `<aside>`) |
| `defense_script.md` | Сценарий защиты и демонстрации, ответы на вопросы |
| `../analogs.md` | Обзор аналогов с источниками и итоговая новизна |

Пересборка работы (числа подставляются из `experiments/results/*_test.json`):

```bash
cd docs/competition && npm install
node build_paper.js
python3 update_toc.py EIS_konkursnaya_rabota.docx   # PDF с заполненным оглавлением (нужен LibreOffice)
```
Графики: `.venv/bin/python experiments/make_figures.py`.
