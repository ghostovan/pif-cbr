"""Smoke-тест Streamlit-дэшборда: все страницы рендерятся без ошибок.

Запуск напрямую: python tests/smoke_dashboard.py
"""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
PAGES = ["Обзор рынка", "Потоки", "Структура активов",
         "Фонды для неквалов", "Данные"]


def _render(page: str) -> list[str]:
    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value(page)
    at.run()
    return [str(e.value) for e in at.exception]


def test_all_pages_render():
    failed = {}
    for page in PAGES:
        errs = _render(page)
        if errs:
            failed[page] = errs[:3]
        print(f"[{'OK' if not errs else 'FAIL'}] {page}: ошибок={len(errs)}",
              flush=True)
    assert not failed, f"Страницы с ошибками: {failed}"


if __name__ == "__main__":
    bad = [p for p in PAGES if _render(p)]
    sys.exit(1 if bad else 0)
