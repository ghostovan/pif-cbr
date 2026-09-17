"""Конвертация XLSX Банка России в нормализованные CSV.

Выход:
  data/processed/pif_long.csv          — ОПД_ПИФ (все месяцы стеком, 94 колонки)
  data/processed/pif_showcase_long.csv — Витрина ПИФ (комиссии распарсены в числа)

Схема колонок: schema.json (сопоставление по тексту шапки, не по позиции).
Пересоздать схему: python src/convert.py --make-schema
"""
import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

import openpyxl
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
SCHEMA_PATH = ROOT / "schema.json"

log = logging.getLogger("convert")

# ---------------------------------------------------------------- нейминги ---

OPD_NAMES = [
    "fund_name", "rule_number", "fund_type", "category", "status",
    "uk_name", "uk_inn", "currency_code",
    "units_total", "units_individuals", "holders_total", "holders_individuals",
    "unit_value", "nav",
    "assets_total",
    "cash_total", "cash_current_accounts", "cash_current_accounts_rub",
    "cash_current_accounts_fx", "cash_deposits_total", "cash_deposits_rub",
    "cash_deposits_fx", "cash_platforms_total", "cash_platforms_rub",
    "cash_platforms_fx",
    "securities_ru_total", "ru_corp_bonds", "ru_gov_bonds", "ru_region_bonds",
    "ru_municipal_bonds", "ru_rdr", "ru_fund_units", "ru_stocks", "ru_bills",
    "ru_mortgage_total", "ru_mortgage_covered_bonds", "ru_mortgage_certificates",
    "ru_other_securities",
    "securities_foreign_total", "foreign_bonds_total", "foreign_corp_bonds",
    "foreign_gov_bonds", "intl_org_bonds", "foreign_rdr", "foreign_fund_units",
    "foreign_stocks", "foreign_other_securities",
    "real_estate_total", "real_estate_ru", "real_estate_foreign",
    "lease_rights_ru", "lease_rights_foreign",
    "property_rights_total", "rights_ddu", "rights_property_after_construction",
    "rights_construction_land", "rights_reconstruction", "rights_other",
    "monetary_claims_total", "monetary_claims_non_mortgage",
    "monetary_claims_mortgage",
    "derivatives",
    "receivables_total", "receivables_brokers", "receivables_deals",
    "receivables_coupon", "receivables_other",
    "other_assets_total", "ooo_shares", "foreign_ooo_shares",
    "project_documentation", "precious_metals_total", "precious_metals_value",
    "precious_metals_claims", "art_values", "other_property",
    "liabilities_total", "payables", "liabilities_derivatives", "fee_reserves",
    "change_units_total", "change_from_deals", "change_fair_value",
    "change_income", "change_contract_payments", "change_fees",
    "change_expenses", "change_dividends", "change_other_income",
    "change_other_expenses",
    "flow_issuance", "flow_redemption", "flow_exchange_in", "flow_exchange_out",
]

SHOWCASE_NAMES = [
    "rule_number", "fund_name", "isin", "fund_type", "category", "status",
    "uk_name", "uk_inn", "uk_website", "rules_edit_date",
    "strategy_type", "benchmark", "benchmark_deviation",
    "uk_fee_raw", "success_fee_raw", "infra_fee_raw", "max_total_expense_raw",
    "income_right", "payment_frequency", "surcharges_raw", "discounts_raw",
    "return_1m", "return_3m", "return_6m", "return_12m",
]

# есть не во всех месяцах (в апреле 2026 отсутствуют)
SHOWCASE_OPTIONAL = {"return_1m", "return_3m", "return_6m"}

FILES = {
    "opd": {"names": OPD_NAMES},
    "showcase": {"names": SHOWCASE_NAMES, "optional": SHOWCASE_OPTIONAL},
}

# строки-сноски в начале ячейки с названием фонда
FOOTNOTE_PREFIXES = ("*", "'", "Дата", "Прим", "Дан")

WS = re.compile(r"\s+")
PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
NUMBER_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
WAIVE = {"", "-", "не предусмотрено", "не устанавливается", "н/д", "отсутствует"}


# ------------------------------------------------------------ работа с xlsx --

def norm_text(value) -> str:
    if value is None:
        return ""
    s = str(value).replace("\xa0", " ").replace("\n", " ")
    return WS.sub(" ", s).strip()


def clean_text(value):
    """Нормализация текстового значения ячейки для CSV."""
    if value is None:
        return None
    s = str(value).replace("\xa0", " ")
    s = WS.sub(" ", s).strip()
    return s or None


def find_numbers_row(ws) -> int:
    """Строка с нумерацией колонок 1,2,3,... (якорь структуры листа)."""
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=15, values_only=True),
                            start=1):
        vals = [v for v in row if v is not None]
        if len(vals) >= 3 and vals[0] == 1 and vals[1] == 2 and vals[2] == 3:
            return i
    raise RuntimeError(f"Не найдена строка нумерации колонок на листе {ws.title}")


def header_rows_above(ws, numbers_row: int) -> list[int]:
    """Шапка = непрерывный блок непустых строк сразу над строкой нумерации."""
    rows = []
    r = numbers_row - 1
    while r >= 1:
        vals = list(ws.iter_rows(min_row=r, max_row=r, values_only=True))[0]
        if all(v is None for v in vals):
            break
        rows.append(r)
        r -= 1
    return sorted(rows)


def sheet_keys(ws, numbers_row: int, ncols: int) -> list[str]:
    """Ключи колонок: склеенные тексты шапки с заполнением merged-ячеек.
    Повторы получают суффикс #2, #3, ..."""
    hrows = header_rows_above(ws, numbers_row)
    if not hrows:
        raise RuntimeError(f"Не найдена шапка на листе {ws.title}")
    h0, h1 = hrows[0], hrows[-1]
    grid = {r: [None] * ncols for r in hrows}
    for r in hrows:
        vals = list(ws.iter_rows(min_row=r, max_row=r, max_col=ncols, values_only=True))[0]
        grid[r] = list(vals) + [None] * (ncols - len(vals))
    for mr in ws.merged_cells.ranges:
        if mr.min_row <= h1 and mr.max_row >= h0:
            tl = ws.cell(mr.min_row, mr.min_col).value
            for r in range(max(mr.min_row, h0), min(mr.max_row, h1) + 1):
                if r not in grid:
                    continue
                for c in range(mr.min_col - 1, min(mr.max_col, ncols)):
                    if grid[r][c] is None:
                        grid[r][c] = tl
    keys = [" | ".join(norm_text(grid[r][c]) for r in hrows) for c in range(ncols)]
    seen: Counter = Counter()
    out = []
    for k in keys:
        seen[k] += 1
        out.append(k if seen[k] == 1 else f"{k}#{seen[k]}")
    return out


def parse_report_date(sheet_name: str) -> pd.Timestamp:
    m = re.search(r"(\d{1,2})\s+(\d{1,2})\s+(\d{4})", sheet_name)
    if not m:
        raise RuntimeError(f"Не удалось извлечь дату из имени листа: {sheet_name!r}")
    d, mo, y = map(int, m.groups())
    return pd.Timestamp(year=y, month=mo, day=d)


def is_data_row(value) -> bool:
    """Строка данных = непустое название фонда без маркеров сносок."""
    if value is None:
        return False
    s = str(value).strip()
    if not s:
        return False
    return not s.startswith(FOOTNOTE_PREFIXES)


# ------------------------------------------------------------ парсер комиссий

def parse_fee(raw) -> dict:
    """Текстовое описание комиссии -> числовые поля.

    Возвращает: value (сопоставимое значение, % от СЧА или руб.),
    min/max (% от СЧА), base (nav|fixed|mixed|none), is_exact, is_empty, ok.
    """
    out = {"value": None, "min": None, "max": None, "base": "none",
           "is_exact": False, "is_empty": True, "ok": True}
    if raw is None:
        return out
    t = norm_text(raw).lower().rstrip(".")
    if t in WAIVE:
        out.update(value=0.0, min=0.0, max=0.0, base="none", is_exact=True)
        return out
    out["is_empty"] = False
    percents = PERCENT_RE.findall(t)
    has_rub = "руб" in t
    if not percents and not has_rub:
        out["ok"] = False
        return out
    upper_only = ("не более" in t) or ("не выше" in t)
    range_style = t.startswith("от ") and " до " in t and len(percents) >= 2
    if percents:
        if range_style:
            lo = float(percents[0].replace(",", "."))
            hi = float(percents[-1].replace(",", "."))
            out.update(value=hi, min=lo, max=hi, base="nav", is_exact=False)
        elif upper_only:
            v = float(percents[-1].replace(",", "."))
            out.update(value=v, min=None, max=v, base="nav", is_exact=False)
        else:
            v = float(percents[-1].replace(",", "."))
            out.update(value=v, min=v, max=v, base="nav", is_exact=True)
        if has_rub:
            out["base"] = "mixed"
    else:  # только рубли
        nums = NUMBER_RE.findall(t)
        if not nums:
            out["ok"] = False
            return out
        v = float(nums[0].replace(",", "."))
        out.update(value=v, min=v, max=v, base="fixed", is_exact=True)
    return out


FEE_COLUMNS = {
    "uk_fee_raw": ("uk_fee_value", "uk_fee_min", "uk_fee_max",
                   "uk_fee_base", "uk_fee_exact"),
    "infra_fee_raw": ("infra_fee_value", "infra_fee_min", "infra_fee_max",
                      "infra_fee_base", "infra_fee_exact"),
    "max_total_expense_raw": ("max_expense_value", "max_expense_min",
                              "max_expense_max", "max_expense_base",
                              "max_expense_exact"),
}


def apply_fee_parsing(df: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Добавляет числовые поля комиссий. Возвращает (df, доля непарсируемых)."""
    total_bad = 0
    total_nonempty = 0
    for raw_col, targets in FEE_COLUMNS.items():
        parsed = df[raw_col].map(parse_fee)
        v_col, min_col, max_col, base_col, exact_col = targets
        df[v_col] = parsed.map(lambda p: p["value"])
        df[min_col] = parsed.map(lambda p: p["min"])
        df[max_col] = parsed.map(lambda p: p["max"])
        df[base_col] = parsed.map(lambda p: p["base"])
        df[exact_col] = parsed.map(lambda p: p["is_exact"])
        total_bad += sum(1 for p in parsed if not p["ok"])
        total_nonempty += sum(1 for p in parsed if not p["is_empty"])
    fail_rate = total_bad / total_nonempty if total_nonempty else 0.0
    df["has_success_fee"] = df["success_fee_raw"].map(
        lambda s: bool(norm_text(s)) and norm_text(s).lower() not in WAIVE
    )
    return df.copy(), fail_rate


# ------------------------------------------------------------------- схема ---

def latest_sheet(wb) -> str:
    """Имя самого свежего листа (по дате в имени листа)."""
    return max(wb.sheetnames, key=lambda sn: parse_report_date(sn))


def make_schema(cfg: dict) -> dict:
    """Собирает schema.json как объединение ключей ВСЕХ листов raw-файла.

    Имя колонки определяется по ключу (текст шапки); для новых ключей —
    по позиции в самом свежем листе. Формулировки шапки у ЦБ меняются
    от месяца к месяцу, поэтому схема должна покрывать все варианты.
    """
    schema = {}
    for key, src in cfg["sources"].items():
        names_ref = FILES[key]["names"]
        optional = FILES[key].get("optional", set())
        wb = openpyxl.load_workbook(ROOT / src["raw_file"])
        ref_sn = latest_sheet(wb)

        def sheet_ncols(ws: openpyxl.worksheet.worksheet.Worksheet) -> int:
            nr = find_numbers_row(ws)
            vals = list(ws.iter_rows(min_row=nr, max_row=nr, values_only=True))[0]
            return len([v for v in vals if isinstance(v, (int, float))])

        ws_ref = wb[ref_sn]
        keys_ref = sheet_keys(ws_ref, find_numbers_row(ws_ref), sheet_ncols(ws_ref))
        key_name: dict[str, str] = dict(zip(keys_ref, names_ref))

        for sn in wb.sheetnames:
            ws = wb[sn]
            ncols = sheet_ncols(ws)
            for i, k in enumerate(sheet_keys(ws, find_numbers_row(ws), ncols)):
                by_pos = names_ref[i] if i < len(names_ref) else f"unknown_col_{i + 1}"
                if k in key_name:
                    continue  # ключ уже известен — имя по ключу важнее позиции
                key_name[k] = by_pos

        ordered = [(k, key_name[k]) for k in keys_ref]
        ordered += [(k, n) for k, n in key_name.items() if k not in keys_ref]
        cols = [{"key": k, "name": n, "optional": n in optional} for k, n in ordered]
        schema[key] = {"columns": cols, "reference_sheet": ref_sn,
                       "reference_ncols": len(keys_ref)}
        log.info("[%s] схема: %d уникальных ключей (эталон: %s)",
                 key, len(cols), ref_sn)
    with open(SCHEMA_PATH, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
    log.info("Схема сохранена: %s", SCHEMA_PATH)
    return schema


def verify_schema(schema: dict, cfg: dict) -> None:
    """Строгая проверка: неизвестные ключи и отсутствие обязательных колонок
    в любом листе — ошибка (защита от молчаливого сдвига схемы ЦБ).
    Одно имя может иметь несколько текстовых вариантов ключа (формулировки
    ЦБ меняются от месяца к месяцу) — колонка считается присутствующей,
    если найден хотя бы один её ключ."""
    for key, src in cfg["sources"].items():
        cols = schema[key]["columns"]
        known = {c["key"]: c for c in cols}
        name_keys: dict[str, set[str]] = {}
        for c in cols:
            name_keys.setdefault(c["name"], set()).add(c["key"])
        wb = openpyxl.load_workbook(ROOT / src["raw_file"])
        for sn in wb.sheetnames:
            ws = wb[sn]
            nr = find_numbers_row(ws)
            vals = list(ws.iter_rows(min_row=nr, max_row=nr, values_only=True))[0]
            ncols = len([v for v in vals if isinstance(v, (int, float))])
            keys = set(sheet_keys(ws, nr, ncols))
            unknown = [k for k in keys if k not in known]
            missing = [name for name, ks in name_keys.items()
                       if not (ks & keys) and name not in FILES[key].get("optional", set())]
            if unknown:
                raise RuntimeError(
                    f"{key} / {sn}: неизвестные колонки — обновите схему "
                    f"(python src/convert.py --make-schema) и сверьте diff: "
                    f"{[u[:80] for u in unknown]}"
                )
            if missing:
                raise RuntimeError(
                    f"{key} / {sn}: отсутствуют обязательные колонки: {missing}"
                )
        log.info("[%s] все листы соответствуют схеме", key)


# ---------------------------------------------------------------- конвертация

def convert_sheet(ws, cols: list[dict]) -> pd.DataFrame:
    """Лист -> DataFrame с именами колонок из схемы."""
    numbers_row = find_numbers_row(ws)
    row_vals = list(ws.iter_rows(min_row=numbers_row, max_row=numbers_row,
                                 values_only=True))[0]
    ncols = len([v for v in row_vals if isinstance(v, (int, float))])
    keys = sheet_keys(ws, numbers_row, ncols)
    key2name = {c["key"]: c["name"] for c in cols}
    present = [key2name[k] for k in keys]
    name_by_idx = {i: key2name[k] for i, k in enumerate(keys)}

    records = []
    # индекс колонки с названием фонда (для фильтрации сносок)
    fund_name_idx = (list(name_by_idx.values()).index("fund_name")
                     if "fund_name" in name_by_idx.values() else 0)

    for row in ws.iter_rows(min_row=numbers_row + 1, values_only=True):
        cell = row[fund_name_idx] if fund_name_idx < len(row) else None
        if not is_data_row(cell):
            continue
        rec = {}
        for i, v in enumerate(row[:ncols]):
            rec[name_by_idx[i]] = clean_text(v)
        # данные фонда = есть и название, и номер ПДУ (отсекает хвостовые сноски)
        if not rec.get("fund_name") or not rec.get("rule_number"):
            continue
        records.append(rec)
    df = pd.DataFrame(records, columns=present)
    df["report_date"] = parse_report_date(ws.title)
    return df


def numeric_cols(names: list[str]) -> list[str]:
    num_prefixes = (
        "units_", "holders_", "unit_value", "nav", "assets_", "cash_",
        "securities_", "ru_", "foreign_", "intl_", "real_estate_", "lease_",
        "rights_", "monetary_", "derivatives", "receivables_", "other_assets_",
        "ooo_shares", "project_documentation", "precious_metals_", "art_values",
        "other_property", "liabilities", "payables", "fee_reserves",
        "change_", "flow_", "return_",
    )
    skip = {"uk_inn"}
    return [n for n in names
            if n.startswith(num_prefixes) and n not in skip]


def to_numeric_smart(series: pd.Series) -> pd.Series:
    """Числа: float/int как есть; строки с ',' и '−' -> NaN."""
    def cast(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    return series.map(cast)


def normalize_df(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    for col in numeric_cols(names):
        if col in df.columns:
            df[col] = to_numeric_smart(df[col])
    if "uk_inn" in df.columns:  # ИНН — строка без дробной части
        df["uk_inn"] = df["uk_inn"].map(
            lambda v: None if v is None
            else (str(int(float(v))) if str(v).replace(".", "", 1).isdigit() else str(v))
        )
    if "rule_number" in df.columns:
        df["rule_number"] = df["rule_number"].map(lambda v: str(v).strip() if v else None)
    return df


def convert_file(key: str, cfg: dict, schema: dict) -> tuple[pd.DataFrame, dict]:
    src = cfg["sources"][key]
    wb = openpyxl.load_workbook(ROOT / src["raw_file"])
    frames = []
    stats = {"sheets": {}}
    for sn in wb.sheetnames:
        df = convert_sheet(wb[sn], schema[key]["columns"])
        frames.append(df)
        stats["sheets"][sn] = int(len(df))
        log.info("[%s] %s: %d строк", key, sn, len(df))
    out = pd.concat(frames, ignore_index=True)
    out = normalize_df(out, [c["name"] for c in schema[key]["columns"]])
    out["report_date"] = pd.to_datetime(out["report_date"])
    out = out.sort_values(["report_date", "rule_number"]).reset_index(drop=True)

    extra = {}
    if key == "showcase":
        out, fail_rate = apply_fee_parsing(out)
        extra["fee_parse_fail_rate"] = fail_rate
        log.info("[%s] доля непарсируемых комиссий: %.2f%%", key, fail_rate * 100)
    stats.update(extra)
    stats["rows"] = int(len(out))
    return out, stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--make-schema", action="store_true",
                        help="пересобрать schema.json из raw-файлов")
    args = parser.parse_args()

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if args.make_schema or not SCHEMA_PATH.exists():
        schema = make_schema(cfg)
    else:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
    verify_schema(schema, cfg)

    processed = ROOT / cfg["paths"]["processed_dir"]
    processed.mkdir(parents=True, exist_ok=True)
    quality = ROOT / cfg["paths"]["quality_dir"]
    quality.mkdir(parents=True, exist_ok=True)

    all_stats = {}
    outputs = {"opd": "pif_long.csv", "showcase": "pif_showcase_long.csv"}
    for key, fname in outputs.items():
        df, stats = convert_file(key, cfg, schema)
        path = processed / fname
        df.to_csv(path, index=False, encoding="utf-8-sig")
        log.info("[%s] сохранено %s: %d строк x %d колонок",
                 key, path, len(df), df.shape[1])
        all_stats[key] = stats

    with open(quality / "convert_stats.json", "w", encoding="utf-8") as f:
        json.dump(all_stats, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
