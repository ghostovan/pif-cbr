"""Скачивание исходных XLSX-файлов Банка России по URL из config.yaml.

Использование: python src/download.py [--force]
Без --force файл не перекачивается, если уже существует и не битый.
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

XLSX_MAGIC = b"PK\x03\x04"  # xlsx — это zip-архив

log = logging.getLogger("download")


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def looks_valid(path: Path, min_bytes: int) -> bool:
    if not path.exists() or path.stat().st_size < min_bytes:
        return False
    try:
        with open(path, "rb") as f:
            return f.read(4) == XLSX_MAGIC
    except OSError:
        return False


def download(url: str, dest: Path, timeout: int, retries: int, min_bytes: int) -> bool:
    """Скачивает файл с retry. Возвращает True, если файл был (пере)скачан."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            log.info("Загрузка (попытка %d/%d): %s", attempt, retries, url)
            with requests.get(url, timeout=timeout, headers=HEADERS, stream=True) as r:
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "")
                if "text/html" in ctype.lower():
                    raise RuntimeError(f"Получен HTML вместо XLSX (Content-Type: {ctype})")
                size = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        f.write(chunk)
                        size += len(chunk)
            if size < min_bytes:
                raise RuntimeError(f"Файл подозрительно мал: {size} байт")
            if open(tmp, "rb").read(4) != XLSX_MAGIC:
                raise RuntimeError("Файл не является XLSX (нет ZIP-сигнатуры)")
            tmp.replace(dest)
            log.info("Сохранено: %s (%.1f МБ)", dest, size / 1e6)
            return True
        except Exception as err:  # noqa: BLE001 — логируем и ретраим
            last_err = err
            log.warning("Попытка %d не удалась: %s", attempt, err)
            tmp.unlink(missing_ok=True)
            if attempt < retries:
                sleep_s = 5 * attempt
                log.info("Пауза %d с перед повтором", sleep_s)
                time.sleep(sleep_s)
    raise RuntimeError(f"Не удалось скачать {url}: {last_err}") from last_err


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="перекачать, даже если файл есть")
    args = parser.parse_args()

    cfg = load_config()
    dl_cfg = cfg["download"]
    failed = []
    for key, src in cfg["sources"].items():
        dest = ROOT / src["raw_file"]
        if not args.force and looks_valid(dest, dl_cfg["min_file_bytes"]):
            log.info("[%s] уже скачан, пропускаю: %s", key, dest)
            continue
        try:
            download(
                src["url"],
                dest,
                timeout=dl_cfg["timeout_sec"],
                retries=dl_cfg["retries"],
                min_bytes=dl_cfg["min_file_bytes"],
            )
        except RuntimeError as err:
            log.error("[%s] %s", key, err)
            failed.append(key)

    if failed:
        log.error("Не удалось получить: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
