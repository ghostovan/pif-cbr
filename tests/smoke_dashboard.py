"""Smoke-тест: все страницы дэшборда рендерятся без ошибок."""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "app" / "dashboard.py"
PAGES = ["Обзор рынка", "Потоки", "Структура активов",
         "Фонды для неквалов", "Данные"]


def main() -> int:
    failed = False
    for page in PAGES:
        at = AppTest.from_file(str(APP), default_timeout=120)
        at.run()
        at.sidebar.radio[0].set_value(page)
        at.run()
        errs = [str(e.value) for e in at.exception]
        print(f"[{'OK' if not errs else 'FAIL'}] {page}: ошибок={len(errs)}",
              flush=True)
        for e in errs[:3]:
            print("   EXC:", e[:400], flush=True)
        failed = failed or bool(errs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
