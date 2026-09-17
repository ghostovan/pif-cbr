"""Формирование витрин для дэшборда из обработанных CSV.

Правила агрегации:
  - суммы СЧА и веса для средних — только фонды в рублях (643-RUB);
  - взвешенные средние комиссий — только «точные» значения (base=nav, exact=True);
  - дополнительно считается среднее по верхним границам (для «не более N%»).

Выход: data/dashboard/*.csv
"""
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
log = logging.getLogger("build")

RUB = "643-RUB"
TOP_N = 20
ASSET_CLASSES = {
    "cash_total": "Денежные средства",
    "securities_ru_total": "Ценные бумаги РФ",
    "securities_foreign_total": "Ценные бумаги иностранных эмитентов",
    "real_estate_total": "Недвижимость и права аренды",
    "property_rights_total": "Имущественные права",
    "monetary_claims_total": "Денежные требования",
    "derivatives": "Производные финансовые инструменты",
    "receivables_total": "Дебиторская задолженность",
    "other_assets_total": "Прочие активы",
}


def load(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    pdir = ROOT / cfg["paths"]["processed_dir"]
    opd = pd.read_csv(pdir / "pif_long.csv", dtype={"rule_number": str},
                      parse_dates=["report_date"])
    show = pd.read_csv(pdir / "pif_showcase_long.csv", dtype={"rule_number": str},
                       parse_dates=["report_date"])
    return opd, show


def rub(df: pd.DataFrame) -> pd.DataFrame:
    """Только фонды с СЧА в рублях (для сумм и весов)."""
    return df[df["currency_code"] == RUB]


def wavg(df: pd.DataFrame, value_col: str, weight_col: str = "nav") -> float:
    sub = df[[value_col, weight_col]].dropna()
    sub = sub[sub[weight_col] > 0]
    if sub.empty or sub[weight_col].sum() == 0:
        return float("nan")
    return float((sub[value_col] * sub[weight_col]).sum() / sub[weight_col].sum())


# --------------------------------------------------------------- рыночные ---

def nav_by(opd_rub: pd.DataFrame, col: str) -> pd.DataFrame:
    g = opd_rub.groupby(["report_date", col], observed=True).agg(
        funds_count=("rule_number", "count"),
        nav_sum=("nav", "sum"),
        holders_total=("holders_total", "sum"),
    ).reset_index()
    return g.rename(columns={col: "group"})


def build_flows(opd_rub: pd.DataFrame) -> pd.DataFrame:
    g = opd_rub.groupby(["report_date", "fund_type"], observed=True).agg(
        flow_issuance=("flow_issuance", "sum"),
        flow_redemption=("flow_redemption", "sum"),
        flow_exchange_in=("flow_exchange_in", "sum"),
        flow_exchange_out=("flow_exchange_out", "sum"),
    ).reset_index()
    g["net_flow"] = (g["flow_issuance"] - g["flow_redemption"]
                     + g["flow_exchange_in"] - g["flow_exchange_out"])
    return g.rename(columns={"fund_type": "group"})


def build_asset_structure(opd_rub: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dt, grp in opd_rub.groupby("report_date"):
        for col, label in ASSET_CLASSES.items():
            rows.append({"report_date": dt, "asset_class": label,
                         "value_sum": grp[col].sum()})
    out = pd.DataFrame(rows)
    return out.sort_values(["report_date", "asset_class"])


def build_top_funds(opd_rub: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for dt, grp in opd_rub.groupby("report_date"):
        top = grp.nlargest(TOP_N, "nav")[
            ["report_date", "rule_number", "fund_name", "fund_type",
             "uk_name", "nav", "unit_value"]].copy()
        top["rank"] = range(1, len(top) + 1)
        parts.append(top)
    return pd.concat(parts, ignore_index=True)


def build_investors(opd_rub: pd.DataFrame) -> pd.DataFrame:
    return opd_rub.groupby(["report_date", "fund_type"], observed=True).agg(
        holders_total=("holders_total", "sum"),
        holders_individuals=("holders_individuals", "sum"),
        units_individuals=("units_individuals", "sum"),
    ).reset_index()


# -------------------------------------------------------------- неквалы -----

def _comparable_nav_values(sub: pd.DataFrame, base_col: str,
                           value_col: str, max_col: str):
    """Комиссии, сопоставимые с '% от СЧА': base=nav, а также 'не предусмотрено'
    (base=none => 0%). Рублёвые и гибридные тарифы несопоставимы — исключаются."""
    ok = sub[base_col].isin(["nav", "none"])
    vals = sub.loc[ok].copy()
    vals[value_col] = vals[value_col].where(vals[base_col] == "nav", 0.0)
    vals[max_col] = vals[max_col].where(vals[base_col] == "nav", 0.0)
    return vals


def _grouped_fees(show_rub: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for dt, grp in show_rub.groupby("report_date"):
        for gval, sub in grp.groupby(group_col, observed=True):
            nav_sum = sub["nav"].sum()
            cmp_vals = _comparable_nav_values(sub, "uk_fee_base",
                                              "uk_fee_value", "uk_fee_max")
            exact = cmp_vals[cmp_vals["uk_fee_exact"]]
            infra_vals = _comparable_nav_values(sub, "infra_fee_base",
                                                "infra_fee_value", "infra_fee_max")
            exp_vals = _comparable_nav_values(sub, "max_expense_base",
                                              "max_expense_value", "max_expense_max")
            rows.append({
                "report_date": dt, "grouping": group_col, "group": gval,
                "n_funds": len(sub),
                "nav_sum": nav_sum,
                "uk_fee_wavg_exact": wavg(exact, "uk_fee_value"),
                "uk_fee_wavg_upper": wavg(cmp_vals, "uk_fee_max"),
                "uk_fee_median": float(cmp_vals["uk_fee_value"].median()),
                "uk_fee_exact_nav_share":
                    float(exact["nav"].sum() / nav_sum) if nav_sum else float("nan"),
                "uk_fee_fixed_share": float((sub["uk_fee_base"] == "fixed").mean()),
                "infra_fee_wavg": wavg(infra_vals, "infra_fee_value"),
                "max_expense_wavg_upper": wavg(exp_vals, "max_expense_max"),
                "has_success_fee_share": float(sub["has_success_fee"].mean()),
            })
    return pd.DataFrame(rows)


def build_fees(show_rub: pd.DataFrame) -> pd.DataFrame:
    parts = [_grouped_fees(show_rub, c) for c in
             ("strategy_type", "category", "fund_type")]
    return pd.concat(parts, ignore_index=True)


def build_returns(show_rub: pd.DataFrame) -> pd.DataFrame:
    cols = ["return_1m", "return_3m", "return_6m", "return_12m"]
    rows = []
    for group_col in ("strategy_type", "category", "fund_type"):
        for dt, grp in show_rub.groupby("report_date"):
            for gval, sub in grp.groupby(group_col, observed=True):
                rec = {"report_date": dt, "grouping": group_col, "group": gval,
                       "n_funds": int(len(sub))}
                for c in cols:
                    rec[f"{c}_median"] = float(sub[c].median())
                rec["return_12m_wavg"] = wavg(sub, "return_12m")
                rows.append(rec)
    return pd.DataFrame(rows)


def build_strategy_split(show_rub: pd.DataFrame) -> pd.DataFrame:
    g = show_rub.groupby(["report_date", "strategy_type"], observed=True).agg(
        n_funds=("rule_number", "count"), nav_sum=("nav", "sum"),
    ).reset_index()
    return g


def build_benchmarks_top(show_rub: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    last_dt = show_rub.report_date.max()
    last = show_rub[show_rub.report_date == last_dt]
    passive = last[last["strategy_type"] == "пассивная"]
    g = (passive.groupby("benchmark", observed=True)
         .agg(n_funds=("rule_number", "count"), nav_sum=("nav", "sum"))
         .reset_index()
         .nlargest(top_n, "n_funds"))
    g.insert(0, "report_date", last_dt)
    return g


# ------------------------------------------------------------- объединённые --

MERGED_COLS = [
    "report_date",
    "rule_number", "fund_name", "isin", "fund_type", "category", "status",
    "uk_name", "uk_inn", "uk_website", "strategy_type", "benchmark",
    "benchmark_deviation",
    "uk_fee_raw", "uk_fee_value", "uk_fee_exact", "uk_fee_base",
    "success_fee_raw", "has_success_fee",
    "infra_fee_raw", "infra_fee_value",
    "max_total_expense_raw", "max_expense_value",
    "income_right", "payment_frequency", "surcharges_raw", "discounts_raw",
    "return_1m", "return_3m", "return_6m", "return_12m",
    "units_total", "holders_total", "holders_individuals",
    "unit_value", "nav", "currency_code",
]

TIMESERIES_COLS = ["report_date", "rule_number", "fund_name", "fund_type",
                   "status", "currency_code", "nav", "unit_value",
                   "holders_total", "units_total"]


def build_merged(opd: pd.DataFrame, show: pd.DataFrame) -> pd.DataFrame:
    """Последний месяц обоих источников: свойства фонда + рыночные метрики."""
    last_show_dt = show.report_date.max()
    last_opd_dt = opd.report_date.max()
    s = show[show.report_date == last_show_dt].copy()
    s["report_date"] = last_opd_dt
    o = opd[opd.report_date == last_opd_dt][
        ["rule_number", "units_total", "holders_total", "holders_individuals",
         "unit_value", "nav", "currency_code"]]
    m = s.merge(o, on="rule_number", how="left", suffixes=("", "_opd"))
    # currency_code берём из ОПД (там он нормативный), fallback на витрину
    if "currency_code_opd" in m.columns:
        m["currency_code"] = m["currency_code_opd"].fillna(m["currency_code"])
        m = m.drop(columns=["currency_code_opd"])
    cols = [c for c in MERGED_COLS if c in m.columns]
    return m[cols].sort_values("nav", ascending=False, na_position="last")


def build_timeseries(opd: pd.DataFrame) -> pd.DataFrame:
    return opd[TIMESERIES_COLS].sort_values(["rule_number", "report_date"])


# --------------------------------------------------------------------- main --

def attach_market_data(show: pd.DataFrame, opd: pd.DataFrame) -> pd.DataFrame:
    """Витрина не содержит валюту и СЧА — подтягиваем из ОПД по № ПДУ и месяцу
    (даты срезов могут отличаться на несколько дней)."""
    o = opd[["rule_number", "report_date", "currency_code", "nav"]].copy()
    o["month"] = o["report_date"].dt.to_period("M")
    s = show.copy()
    s["month"] = s["report_date"].dt.to_period("M")
    out = s.merge(
        o.drop(columns="report_date").rename(columns={"nav": "nav_weight"}),
        on=["rule_number", "month"], how="left",
    )
    # fallback: если месяца нет в ОПД — берём последнюю известную валюту/СЧА
    last = (opd.sort_values("report_date")
            .drop_duplicates("rule_number", keep="last")
            [["rule_number", "currency_code", "nav"]]
            .rename(columns={"nav": "nav_weight_last"}))
    out = out.merge(last, on="rule_number", how="left", suffixes=("", "_fb"))
    for cur_col in ("currency_code", "currency_code_fb"):
        if cur_col not in out.columns:
            out[cur_col] = None
    out["currency_code"] = out["currency_code"].fillna(out["currency_code_fb"])
    out["nav"] = out["nav_weight"].fillna(out["nav_weight_last"])
    out = out.drop(
        columns=["nav_weight", "nav_weight_last", "month", "currency_code_fb"],
        errors="ignore")
    return out


def build_all(opd: pd.DataFrame, show: pd.DataFrame, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    opd_rub = rub(opd)
    show_rub = rub(attach_market_data(show, opd))

    datasets = {
        "nav_by_type.csv": nav_by(opd_rub, "fund_type"),
        "nav_by_category.csv": nav_by(opd_rub, "category"),
        "flows.csv": build_flows(opd_rub),
        "asset_structure.csv": build_asset_structure(opd_rub),
        "top_funds.csv": build_top_funds(opd_rub),
        "investors.csv": build_investors(opd_rub),
        "fees_agg.csv": build_fees(show_rub),
        "returns_agg.csv": build_returns(show_rub),
        "strategy_split.csv": build_strategy_split(show_rub),
        "benchmarks_top.csv": build_benchmarks_top(show_rub),
        "funds_merged_latest.csv": build_merged(opd, show),
        "fund_timeseries.csv": build_timeseries(opd),
    }
    for fname, df in datasets.items():
        df.to_csv(out_dir / fname, index=False, encoding="utf-8-sig")
        log.info("%s: %d строк x %d колонок", fname, len(df), df.shape[1])
    return {k: len(v) for k, v in datasets.items()}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    opd, show = load(cfg)
    out_dir = ROOT / cfg["paths"]["dashboard_dir"]
    build_all(opd, show, out_dir)
    log.info("Витрины сохранены: %s", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
