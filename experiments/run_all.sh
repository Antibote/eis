#!/usr/bin/env bash
# Воспроизведение всех экспериментов: датасет → E1 → E2 → E3 (результаты в experiments/results)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
$PY dataset/generator/build.py --seed 42
for v in dev test; do
  $PY -W ignore experiments/eval_extraction.py --variant $v
  (cd experiments && ../$PY -W ignore eval_impact.py --variant $v --with-holdout --with-holdout2 && ../$PY -W ignore eval_contradictions.py --variant $v)
done
