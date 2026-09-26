#!/usr/bin/env bash
# Идемпотентное обновление данных и публикация.
# Сборка -> валидация -> коммит только при изменениях -> pull --rebase -> push.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"

echo "==> 1/5 Скачивание исходных файлов"
$PY src/download.py

echo "==> 2/5 Конвертация XLSX -> CSV"
$PY src/convert.py

echo "==> 3/5 Сборка витрин"
$PY src/build_datasets.py

echo "==> 4/5 Валидация"
$PY src/validate.py

echo "==> 5/5 Публикация"
# Committed raw-файлы игнорируются, сравниваем только отслеживаемые данные и код
if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain -- data src app tests)" ]; then
  echo "Изменений нет — пуш не требуется."
  exit 0
fi

git add data/processed data/dashboard data/quality src app tests schema.json config.yaml 2>/dev/null || true
if git diff --cached --quiet; then
  echo "Данные не изменились — пуш не требуется."
  exit 0
fi

git commit -m "data: обновление наборов ПИФ $(date +%Y-%m-%d)"
git pull --rebase origin main || true
git push origin main
echo "Пуш выполнен."
