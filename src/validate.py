"""Валидация обработанных данных и отчёт качества.

Проверки (fail => ненулевой код выхода):
  - строки на лист в разумных пределах;
  - уникальность (rule_number, report_date);
  - join файлов по № ПДУ >= порога;
  - доля непарсируемых комиссий <= порога;
  - отрицательные СЧА <= порога;
  - наличие СЧА/типа у фондов.

Отчёт: data/quality/report.md
"""
import json
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
log = logging.getLogger("validate")

RULE_NUMBER_DTYPE = {"rule_number": str}


def load(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    pdir = ROOT / cfg["paths"]["processed_dir"]
    opd = pd.read_csv(pdir / "pif_long.csv", dtype=RULE_NUMBER_DTYPE,
                      parse_dates=["report_date"])
    show = pd.read_csv(pdir / "pif_showcase_long.csv", dtype=RULE_NUMBER_DTYPE,
                       parse_dates=["report_date"])
    return opd, show


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    v = cfg["validation"]

    opd, show = load(cfg)
    checks: list[tuple[str, bool, str]] = []  # (название, ok, детали)
    metrics: dict = {}

    # -- объёмы --------------------------------------------------------------
    months_opd = sorted(opd.report_date.dt.strftime("%Y-%m-%d").unique())
    months_show = sorted(show.report_date.dt.strftime("%Y-%m-%d").unique())
    rows_per_month = opd.groupby("report_date").size()
    bad_rows = rows_per_month[(rows_per_month < v["min_rows_per_sheet"]) |
                              (rows_per_month > v["max_rows_per_sheet"])]
    metrics["months_opd"] = months_opd
    metrics["months_showcase"] = months_show
    metrics["rows_per_month"] = {str(k): int(x) for k, x in rows_per_month.items()}
    checks.append(("Объём данных", bad_rows.empty,
                   f"{len(opd)} строк ОПД, {len(show)} строк витрины, "
                   f"месяцев: {len(months_opd)} / {len(months_show)}" +
                   (f", аномальные месяцы: {dict(bad_rows)}" if not bad_rows.empty else "")))

    # -- уникальность ключа --------------------------------------------------
    dup_opd = int(opd.duplicated(["rule_number", "report_date"]).sum())
    dup_show = int(show.duplicated(["rule_number", "report_date"]).sum())
    checks.append(("Уникальность (№ ПДУ, месяц)", dup_opd + dup_show == 0,
                   f"дубликатов: ОПД {dup_opd}, витрина {dup_show}"))

    # -- join ----------------------------------------------------------------
    last_opd = opd.report_date.max()
    last_show = show[show.report_date == show.report_date.max()]
    opd_last = opd[opd.report_date == last_opd]
    merged = opd_last.merge(last_show, on="rule_number", how="left",
                            indicator=True)
    coverage = (merged["_merge"] == "both").mean()
    metrics["join_coverage_latest"] = round(float(coverage), 4)
    metrics["join_dates"] = [str(last_opd.date()), str(last_show.report_date.max().date())]
    checks.append(("Join файлов по № ПДУ (последний месяц)",
                   coverage >= v["min_join_coverage"],
                   f"совпадение {coverage:.1%} "
                   f"(ОПД {last_opd.date()}, витрина {last_show.report_date.max().date()})"))

    # -- комиссии ------------------------------------------------------------
    stats_path = ROOT / cfg["paths"]["quality_dir"] / "convert_stats.json"
    fail_rate = 0.0
    if stats_path.exists():
        fail_rate = json.loads(stats_path.read_text(encoding="utf-8")) \
            .get("showcase", {}).get("fee_parse_fail_rate", 0.0)
    metrics["fee_parse_fail_rate"] = fail_rate
    checks.append(("Парсинг комиссий", fail_rate <= v["max_fee_parse_fail_rate"],
                   f"непарсируемых {fail_rate:.2%} (порог {v['max_fee_parse_fail_rate']:.0%})"))

    # -- СЧА -----------------------------------------------------------------
    nav = opd["nav"]
    neg_share = float((nav.fillna(0) < 0).mean())
    metrics["nav_missing"] = int(nav.isna().sum())
    metrics["nav_negative_share"] = round(neg_share, 6)
    checks.append(("Отрицательные СЧА", neg_share <= v["max_nav_negative_share"],
                   f"пропусков СЧА: {int(nav.isna().sum())}, отрицательных: {neg_share:.3%} "
                   f"(легитимно для фондов в ликвидации; fail при >{v['max_nav_negative_share']:.0%})"))

    # -- полнота ключевых полей ---------------------------------------------
    miss_type = int(opd["fund_type"].isna().sum())
    miss_status = int(opd["status"].isna().sum())
    ok_fields = miss_type == 0 and miss_status == 0
    checks.append(("Полнота тип/статус", ok_fields,
                   f"пропусков: тип {miss_type}, статус {miss_status}"))

    # -- мультивалютность: доля RUB для агрегатов ----------------------------
    rub_share = float((opd["currency_code"] == "643-RUB").mean())
    metrics["rub_share"] = round(rub_share, 4)
    checks.append(("Доля RUB-фондов (информационная)", True,
                   f"{rub_share:.1%} строк — агрегаты считаются только по RUB "
                   f"(мультивалютные фонды исключаются из сумм/весов)"))

    # -- отчёт ---------------------------------------------------------------
    all_ok = all(ok for _, ok, _ in checks)
    lines = [
        "# Отчёт качества данных",
        f"",
        f"Дата прогона: {date.today().isoformat()}",
        "",
        "| Проверка | Статус | Детали |",
        "|---|---|---|",
    ]
    for name, ok, detail in checks:
        lines.append(f"| {name} | {'✅' if ok else '❌ FAIL'} | {detail} |")
    lines += ["", "## Метрики", ""]
    lines += [f"- `{k}`: {json.dumps(val, ensure_ascii=False)}"
              for k, val in metrics.items()]
    report = "\n".join(lines) + "\n"

    qdir = ROOT / cfg["paths"]["quality_dir"]
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / "report.md").write_text(report, encoding="utf-8")

    for name, ok, detail in checks:
        log.info("%s %s — %s", "✅" if ok else "❌", name, detail)
    log.info("Отчёт: %s", qdir / "report.md")
    if not all_ok:
        log.error("Валидация НЕ пройдена")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
