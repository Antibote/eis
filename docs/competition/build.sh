#!/usr/bin/env bash
# Сборка конкурсной работы: считает объём кода и тестов, собирает DOCX и PDF с заполненным оглавлением.
set -euo pipefail
cd "$(dirname "$0")"
ROOT=../..
fmt() { python3 -c "import sys; n=int(sys.argv[1]); print(f'{round(n, -2):,}'.replace(',', ' '))" "$1"; }
PY=$(find $ROOT/backend/eis -name '*.py' -print0 | xargs -0 cat | wc -l)
TS=$(find $ROOT/frontend/src -name '*.ts*' -print0 | xargs -0 cat | wc -l)
TESTS=$($ROOT/.venv/bin/python -m pytest -q --collect-only $ROOT/backend/tests 2>/dev/null | grep -c '::')
export EIS_LOC="{\"py\":\"$(fmt $PY)\",\"ts\":\"$(fmt $TS)\",\"tests\":\"$TESTS\"}"
echo "код: $EIS_LOC"
node build_paper.js
zip -d EIS_konkursnaya_rabota.docx '*/' >/dev/null 2>&1 || true
python3 update_toc.py EIS_konkursnaya_rabota.docx
pdfinfo EIS_konkursnaya_rabota.pdf | grep Pages
