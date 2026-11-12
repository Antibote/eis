# EIS — Engineering Intelligence System

Прототип системы анализа инженерной документации и оценки последствий конструкторских изменений:
извлечение требований с привязкой к первоисточнику → типизированный граф знаний → формальные проверки
ограничений → анализ последствий изменения с классами влияния → обнаружение противоречий → помощник с
обязательными ссылками на источники. Работает полностью локально, без внешних API.

> Демонстрационные документы (насосный агрегат НА-200) **синтетические** и созданы для демонстрации.

## Быстрый старт (локально)
```bash
python3.12 -m venv .venv
.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python dataset/generator/build.py            # синтетический датасет + эталон
cd backend && ../.venv/bin/uvicorn eis.api.app:app --port 8000
cd frontend && npm ci && npx vite                       # http://localhost:5173
```
Вход: `admin` / значение `EIS_ADMIN_PASSWORD` (по умолчанию `admin` — смените). На «Обзоре» — кнопка
загрузки демонстрационного набора. Для OCR сканов: `sudo apt install tesseract-ocr tesseract-ocr-rus`.

## Docker
```bash
cp .env.example .env               # задать EIS_SECRET_KEY и EIS_ADMIN_PASSWORD (файл не коммитится)
docker compose up --build          # http://localhost:8000 (PostgreSQL + backend + собранный фронтенд)
EIS_PORT=8080 docker compose up --build  # если порт 8000 занят
docker compose --profile llm up    # + локальная LLM через Ollama (EIS_LLM_PROVIDER=ollama)
```

LLM необязательна: без неё система работает полностью. Docker + Ollama на хосте:
```bash
OLLAMA_HOST=172.17.0.1:11434 ollama serve &       # адрес моста docker0 — доступен контейнерам, не локальной сети
EIS_LLM_PROVIDER=ollama EIS_LLM_URL=http://host.docker.internal:11434 docker compose up -d
```
С локальной Ollama без Docker:
```bash
ollama serve & ollama pull qwen2.5:3b
EIS_LLM_PROVIDER=ollama EIS_LLM_URL=http://127.0.0.1:11434 EIS_LLM_MODEL=qwen2.5:3b \
  ../.venv/bin/uvicorn eis.api.app:app --port 8000          # из backend/
```
Эксперименты: `./experiments/run_all.sh` (E1–E3), `experiments/eval_noise.py` (E4, сканы),
`experiments/eval_scale.py` (E5), `experiments/eval_llm.py` (E6, нужна Ollama). Журнал — `docs/experiments_log.md`.

## Эксперименты
```bash
./experiments/run_all.sh           # датасет → E1 извлечение → E2 последствия → E3 противоречия
```
Результаты — `experiments/results/`, журнал прогонов и ограничения — `docs/experiments_log.md`.

## Тесты
```bash
cd backend && ../.venv/bin/python -m pytest -q
```

## Структура
| Путь | Содержание |
|---|---|
| `backend/eis/parsing` | парсеры PDF/DOCX/XLSX/CSV/TXT/изображений (OCR) → фрагменты с местом в документе |
| `backend/eis/extraction` | единицы измерения, словарь параметров, морфологический поиск сущностей, правила, конвейер |
| `backend/eis/graph` | `GraphStore` и реализация на NetworkX |
| `backend/eis/services` | анализ изменений, противоречия, помощник, разбор извещений, отчёты |
| `backend/eis/llm` | провайдеры LLM (нет / Ollama / OpenAI-совместимый) и проверка ссылок |
| `backend/eis/api` | REST API, аутентификация, аудит |
| `dataset/generator` | модель изделия (источник истины), генерация документов и эталона |
| `experiments` | методы M1–M4, оценка E1–E3 |
| `docs` | проектирование, решения (ADR), журнал экспериментов |
