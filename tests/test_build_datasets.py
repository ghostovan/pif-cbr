"""Интеграционный тест: витрины собираются из закоммиченных processed-CSV."""
from pathlib import Path

import pandas as pd
import yaml

from build_datasets import build_all, load

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_FILES = [
    "nav_by_type.csv", "nav_by_category.csv", "flows.csv",
    "asset_structure.csv", "top_funds.csv", "investors.csv",
    "fees_agg.csv", "returns_agg.csv", "strategy_split.csv",
    "benchmarks_top.csv", "funds_merged_latest.csv", "fund_timeseries.csv",
]


def test_build_all_produces_datasets(tmp_path):
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    opd, show = load(cfg)
    assert len(opd) > 3000, "ОПД: подозрительно мало строк"
    assert len(show) > 1500, "витрина: подозрительно мало строк"

    counts = build_all(opd, show, tmp_path)
    for fname in EXPECTED_FILES:
        assert fname in counts and counts[fname] > 0, f"{fname} пуст"

    # ключевые инварианты витрин
    flows = pd.read_csv(tmp_path / "flows.csv")
    assert "group" in flows.columns and "net_flow" in flows.columns

    merged = pd.read_csv(tmp_path / "funds_merged_latest.csv",
                         dtype={"rule_number": str})
    assert merged["rule_number"].is_unique, "дубликаты фонда в merged"
    assert merged["report_date"].notna().all()

    fees = pd.read_csv(tmp_path / "fees_agg.csv")
    exact = fees.dropna(subset=["uk_fee_wavg_exact"])
    assert (exact["uk_fee_wavg_exact"] < 20).all(), \
        "взвешенная комиссия нереалистична — рублёвые тарифы попали в %"
