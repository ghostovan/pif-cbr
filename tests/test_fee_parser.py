"""Тесты парсера комиссий на реальных формулировках из файла ЦБ."""
import pytest

from convert import parse_fee


@pytest.mark.parametrize("raw,expected", [
    # точный процент от СЧА
    ("1,5% от среднегодовой СЧА",
     {"value": 1.5, "base": "nav", "is_exact": True, "min": 1.5, "max": 1.5}),
    ("4% от среднегодовой СЧА",
     {"value": 4.0, "base": "nav", "is_exact": True}),
    # верхняя граница
    ("не более 2% от среднегодовой СЧА",
     {"value": 2.0, "base": "nav", "is_exact": False, "max": 2.0}),
    # не предусмотрено => 0%
    ("не предусмотрено",
     {"value": 0.0, "base": "none", "is_exact": True}),
    # отсутствующая ячейка — нет данных (не путать с 0%)
    (None, {"value": None, "base": "none", "is_exact": False, "is_empty": True}),
    # рублёвые
    ("350000 руб. в месяц", {"value": 350000.0, "base": "fixed"}),
    # гибрид: рубли + процент-потолок
    ("10000 руб. в месяц, но не более 2% от среднегодовой СЧА",
     {"value": 2.0, "base": "mixed", "is_exact": False}),
    # диапазон
    ("от 1% до 2% от среднегодовой СЧА",
     {"value": 2.0, "min": 1.0, "max": 2.0, "base": "nav", "is_exact": False}),
])
def test_parse_fee(raw, expected):
    got = parse_fee(raw)
    for key, val in expected.items():
        assert got[key] == pytest.approx(val) if isinstance(val, float) \
            else got[key] == val, f"{key}: {got[key]} != {val}"
    assert got["ok"] is True


@pytest.mark.parametrize("raw", ["какой-то непонятный текст", "— ??"],
                         ids=["garbage", "symbols"])
def test_parse_fee_unparseable(raw):
    got = parse_fee(raw)
    assert got["ok"] is False
    assert got["is_empty"] is False


def test_parse_fee_dash_variants():
    for raw in ["-", "", "   ", "н/д"]:
        assert parse_fee(raw)["value"] == 0.0


def test_real_mix_is_comparable():
    """Рублёвые тарифы не должны попадать в % агрегаты: base=fixed."""
    fixed = parse_fee("522 000 руб. в месяц")
    nav_pct = parse_fee("1,5% от среднегодовой СЧА")
    assert fixed["base"] == "fixed"
    assert nav_pct["base"] == "nav"
    assert fixed["value"] != pytest.approx(nav_pct["value"])
