"""Дэшборд «ПИФ России»: данные Банка России.

Запуск: streamlit run app/dashboard.py (из корня репозитория).
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parent.parent

st.set_page_config(page_title="ПИФ России — данные Банка России",
                   page_icon="📊", layout="wide")

COLOR = "#0059a3"


# ------------------------------------------------------------------- данные --

@st.cache_data
def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@st.cache_data
def load_dash(fname: str) -> pd.DataFrame:
    cfg = load_config()
    path = ROOT / cfg["paths"]["dashboard_dir"] / fname
    return pd.read_csv(path, dtype={"rule_number": str},
                       parse_dates=["report_date"])


@st.cache_data
def load_quality_report() -> str:
    cfg = load_config()
    p = ROOT / cfg["paths"]["quality_dir"] / "report.md"
    return p.read_text(encoding="utf-8") if p.exists() else "_Отчёт не найден_"


# ---------------------------------------------------------------- утилиты ----

def ru_date(ts) -> str:
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]
    return f"{ts.day} {months[ts.month - 1]} {ts.year}"


def fmt_num(x: float, digits: int = 1) -> str:
    if pd.isna(x):
        return "—"
    s = f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")
    return s


def nav_trln(x: float) -> str:
    return f"{fmt_num(x / 1e12, 2)} трлн ₽"


def vol_mlrd(x: float) -> str:
    sign = "+" if x >= 0 else "−"
    return f"{sign}{fmt_num(abs(x) / 1e9)} млрд ₽"


def pct(x: float, digits: int = 1) -> str:
    return "—" if pd.isna(x) else f"{x * 100:.{digits}f}%".replace(".", ",")


def style_fig(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        margin=dict(l=10, r=10, t=40, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        font=dict(size=13),
    )
    return fig


DISCLAIMER = ("Данные: Банк России (открытые источники). Витрина фондов для "
              "неквалифицированных инвесторов публикуется ЦБ в тестовом формате. "
              "Материал носит информационный характер и не является инвестиционной "
              "рекомендацией.")


# ================================================================== страницы =

def page_overview() -> None:
    st.header("Обзор рынка ПИФ")
    nav = load_dash("nav_by_type.csv")
    inv = load_dash("investors.csv")
    flows = load_dash("flows.csv")

    last_dt = nav.report_date.max()
    last = nav[nav.report_date == last_dt]
    flows_last = flows[flows.report_date == last_dt]["net_flow"].sum()
    holders = inv[inv.report_date == last_dt]["holders_total"].sum()
    prev_dt = nav[nav.report_date < last_dt].report_date.max()
    nav_prev = nav[nav.report_date == prev_dt]["nav_sum"].sum()
    nav_now = last["nav_sum"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Фонды (без валютных)", f"{int(last['funds_count'].sum())}",
              delta=int(last['funds_count'].sum() -
                        nav[nav.report_date == prev_dt]['funds_count'].sum()))
    c2.metric("СЧА рынка", nav_trln(nav_now),
              delta=nav_trln(nav_now - nav_prev) if nav_prev else None,
              delta_color="off")
    c3.metric("Пайщики", f"{fmt_num(holders, 0)}",
              help="Число владельцев паёв (юр. и физ. лица), сумма по фондам")
    c4.metric("Чистый приток за месяц", vol_mlrd(flows_last))

    st.caption(f"Данные на {ru_date(last_dt)}")

    left, right = st.columns(2)
    with left:
        st.subheader("СЧА по типам фондов")
        fig = px.line(nav, x="report_date", y="nav_sum", color="group",
                      markers=True)
        fig.update_traces(line_width=3)
        fig.update_yaxes(title="СЧА, трлн ₽", tickformat=",.1f")
        st.plotly_chart(style_fig(fig), use_container_width=True)
    with right:
        st.subheader("Число фондов по типам")
        fig = px.bar(last.sort_values("nav_sum"), x="group", y="funds_count",
                     color="group", text="funds_count")
        fig.update_layout(showlegend=False)
        fig.update_xaxes(title=None)
        st.plotly_chart(style_fig(fig), use_container_width=True)

    st.subheader("СЧА по категориям")
    cat = load_dash("nav_by_category.csv")
    pivot = cat.pivot_table(index="report_date", columns="group",
                            values="nav_sum", aggfunc="sum").fillna(0)
    # мелкие категории объединяем в "прочие" для читаемости
    top_cats = pivot.iloc[-1].nlargest(4).index.tolist()
    other = [c for c in pivot.columns if c not in top_cats]
    if other:
        pivot["Прочие"] = pivot[other].sum(axis=1)
        pivot = pivot[top_cats + ["Прочие"]]
    fig = px.area(pivot.reset_index(), x="report_date", y=pivot.columns.tolist())
    st.plotly_chart(style_fig(fig), use_container_width=True)

    with st.expander("Таблица: СЧА по типам фондов"):
        st.dataframe(
            nav.pivot_table(index="group", columns="report_date",
                            values="nav_sum", aggfunc="sum")
            .apply(lambda s: s.map(lambda v: fmt_num(v / 1e9, 0))),
            use_container_width=True)
        st.caption("Значения — млрд ₽")


def page_flows() -> None:
    st.header("Притоки и оттоки средств")
    flows = load_dash("flows.csv")
    st.caption("Выдача/погашение и обмен паёв. Только рублёвые фонды; "
               "суммы — млрд ₽.")

    types = ["Все типы"] + sorted(flows["group"].unique())
    sel = st.selectbox("Тип фонда", types)
    sub = (flows.groupby("report_date", as_index=False)[
               ["flow_issuance", "flow_redemption", "net_flow"]].sum()
           if sel == "Все типы"
           else flows[flows["group"] == sel])

    sub = sub.sort_values("report_date")
    fig = go.Figure()
    fig.add_bar(x=sub.report_date, y=sub.flow_issuance / 1e9,
                name="Выдача паёв", marker_color="#2e9e5b")
    fig.add_bar(x=sub.report_date, y=sub.flow_redemption / 1e9,
                name="Погашение паёв", marker_color="#d64550")
    fig.add_scatter(x=sub.report_date, y=sub.net_flow / 1e9, name="Чистый поток",
                    mode="lines+markers", line=dict(color=COLOR, width=3))
    fig.update_layout(barmode="relative")
    fig.update_yaxes(title="млрд ₽")
    st.plotly_chart(style_fig(fig), use_container_width=True)

    st.subheader(f"Топ притоков и оттоков, {ru_date(flows.report_date.max())}")
    top_n = st.slider("Фондов в списке", 5, 30, 10)
    opd = load_processed_opd()
    last_dt = opd.report_date.max()
    lm = opd[opd.report_date == last_dt].copy()
    lm["net_flow"] = (lm.flow_issuance.fillna(0) - lm.flow_redemption.fillna(0)
                      + lm.flow_exchange_in.fillna(0)
                      - lm.flow_exchange_out.fillna(0))
    lm = lm[lm.currency_code == "643-RUB"]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Наибольший чистый приток**")
        show = lm.nlargest(top_n, "net_flow")[
            ["fund_name", "fund_type", "net_flow"]].copy()
        show["net_flow"] = show.net_flow.map(vol_mlrd)
        show.columns = ["Фонд", "Тип", "Чистый поток"]
        st.dataframe(show, use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**Наибольший чистый отток**")
        show = lm.nsmallest(top_n, "net_flow")[
            ["fund_name", "fund_type", "net_flow"]].copy()
        show["net_flow"] = show.net_flow.map(vol_mlrd)
        show.columns = ["Фонд", "Тип", "Чистый поток"]
        st.dataframe(show, use_container_width=True, hide_index=True)


@st.cache_data
def load_processed_opd() -> pd.DataFrame:
    cfg = load_config()
    p = ROOT / cfg["paths"]["processed_dir"] / "pif_long.csv"
    cols = ["report_date", "rule_number", "fund_name", "fund_type",
            "currency_code", "nav", "flow_issuance", "flow_redemption",
            "flow_exchange_in", "flow_exchange_out"]
    return pd.read_csv(p, usecols=cols, dtype={"rule_number": str},
                       parse_dates=["report_date"])


def page_assets() -> None:
    st.header("Структура активов фондов")
    st.caption("Суммарные активы рублёвых фондов по классам, млрд ₽.")
    df = load_dash("asset_structure.csv")

    last_dt = df.report_date.max()
    last = df[df.report_date == last_dt].sort_values("value_sum",
                                                     ascending=False)
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.bar(last, x="value_sum", y="asset_class", orientation="h",
                     text_auto=",.0f", color="value_sum",
                     color_continuous_scale="Blues")
        fig.update_layout(showlegend=False, coloraxis_showscale=False)
        fig.update_xaxes(title="млрд ₽")
        fig.update_yaxes(title=None)
        st.plotly_chart(style_fig(fig), use_container_width=True)
        st.caption(ru_date(last_dt))
    with c2:
        fig = px.pie(last, names="asset_class", values="value_sum", hole=0.45)
        st.plotly_chart(style_fig(fig), use_container_width=True)

    st.subheader("Динамика по классам активов")
    pivot = df.pivot_table(index="report_date", columns="asset_class",
                           values="value_sum", aggfunc="sum").fillna(0)
    fig = px.area(pivot.reset_index(), x="report_date",
                  y=pivot.columns.tolist())
    fig.update_yaxes(title="млрд ₽")
    st.plotly_chart(style_fig(fig), use_container_width=True)

    st.subheader("Крупнейшие фонды рынка")
    top = load_dash("top_funds.csv")
    top_last = top[top.report_date == last_dt]
    st.dataframe(
        top_last[["rank", "fund_name", "fund_type", "nav"]].assign(
            nav=lambda d: d.nav.map(nav_trln)).rename(columns={
                "rank": "#", "fund_name": "Фонд", "fund_type": "Тип",
                "nav": "СЧА"}),
        use_container_width=True, hide_index=True)


def page_showcase() -> None:
    st.header("Фонды для неквалифицированных инвесторов")
    st.caption("Источники: витрина ЦБ (комиссии, стратегии, доходность) + "
               "ОПД ЦБ (СЧА, пайщики). Тестовый формат витрины ЦБ. "
               "Взвешенные средние — только % от СЧА («не предусмотрено» = 0%).")

    fees = load_dash("fees_agg.csv")
    returns = load_dash("returns_agg.csv")
    strat = load_dash("strategy_split.csv")
    merged = load_dash("funds_merged_latest.csv")
    benchmarks = load_dash("benchmarks_top.csv")

    tab_over, tab_list = st.tabs(["📊 Агрегаты", "🔍 Фонды"])

    with tab_over:
        last_dt = fees.report_date.max()
        fj = fees[fees.report_date == last_dt]

        c1, c2, c3, c4 = st.columns(4)
        strat_last = strat[strat.report_date == strat.report_date.max()]
        n_pass = int(strat_last[strat_last.strategy_type == "пассивная"]
                     ["n_funds"].sum())
        n_act = int(strat_last[strat_last.strategy_type == "активная"]
                    ["n_funds"].sum())
        c1.metric("Фондов в витрине", int(len(merged)))
        c2.metric("Активных стратегий", n_act)
        c3.metric("Пассивных стратегий", n_pass)
        med_fee = merged["uk_fee_value"].median()
        c4.metric("Медианная комиссия УК", pct(med_fee / 100, 2)
                  if pd.notna(med_fee) else "—")

        st.subheader(f"Вознаграждение УК, {ru_date(last_dt)} (% годовых от СЧА)")
        sel = st.selectbox("Разрез", ["strategy_type", "category", "fund_type"],
                           format_func={
                               "strategy_type": "по стратегии",
                               "category": "по категории",
                               "fund_type": "по типу фонда"}.get)
        fsub = fj[fj["grouping"] == sel].sort_values("uk_fee_wavg_exact",
                                                  ascending=False)
        fig = go.Figure()
        fig.add_bar(x=fsub["group"], y=fsub["uk_fee_wavg_exact"],
                    name="Взвешенная по СЧА (точные тарифы)",
                    marker_color=COLOR)
        fig.add_scatter(x=fsub["group"], y=fsub["uk_fee_median"],
                        name="Медианная", mode="markers",
                        marker=dict(color="#d64550", size=12, symbol="diamond"))
        fig.update_yaxes(title="% годовых")
        st.plotly_chart(style_fig(fig), use_container_width=True)
        with st.expander("Детали по комиссиям"):
            st.dataframe(fsub[[
                "group", "n_funds", "uk_fee_wavg_exact", "uk_fee_wavg_upper",
                "uk_fee_median", "uk_fee_exact_nav_share", "uk_fee_fixed_share",
                "infra_fee_wavg", "max_expense_wavg_upper",
                "has_success_fee_share"]].round(3),
                use_container_width=True, hide_index=True)

        st.subheader("Доходность пая за 12 месяцев")
        rsub = returns[(returns.report_date == returns.report_date.max())
                       & (returns["grouping"] == sel)]
        fig = px.bar(rsub, x="group", y="return_12m_median",
                     color="group", text_auto=".1%")
        fig.update_layout(showlegend=False)
        fig.update_yaxes(title="медианная доходность", tickformat=".0%")
        st.plotly_chart(style_fig(fig), use_container_width=True)
        with st.expander("Медианная доходность за 1/3/6/12 мес."):
            st.dataframe(rsub[["group", "return_1m_median", "return_3m_median",
                               "return_6m_median", "return_12m_median"]]
                         .assign(**{c: (rsub[c] * 100).round(1)
                                    for c in rsub.columns
                                    if c.endswith("_median")}),
                         use_container_width=True, hide_index=True)

        st.subheader("Популярные бенчмарки пассивных фондов")
        b = benchmarks.drop(columns=["report_date"]).copy()
        b.columns = ["Бенчмарк", "Фондов", "СЧА, млрд ₽"]
        b["СЧА, млрд ₽"] = (b["СЧА, млрд ₽"] / 1e9).round(1)
        st.dataframe(b, use_container_width=True, hide_index=True)

    with tab_list:
        st.subheader("Все фонды витрины")
        df = merged.copy()
        types = ["Все"] + sorted(df["fund_type"].dropna().unique())
        strategies = ["Все"] + sorted(df["strategy_type"].dropna().unique())
        c1, c2, c3 = st.columns(3)
        ft = c1.selectbox("Тип фонда", types)
        stg = c2.selectbox("Стратегия", strategies)
        query = c3.text_input("Поиск по названию / УК", "").strip().lower()

        mask = pd.Series(True, index=df.index)
        if ft != "Все":
            mask &= df["fund_type"] == ft
        if stg != "Все":
            mask &= df["strategy_type"] == stg
        if query:
            mask &= (df.fund_name.fillna("").str.lower().str.contains(query)
                     | df.uk_name.fillna("").str.lower().str.contains(query))
        view = df[mask]
        st.caption(f"Найдено: {len(view)}")
        table = view[["fund_name", "fund_type", "category", "uk_name",
                      "nav", "uk_fee_value", "return_12m"]].copy()
        table.columns = ["Фонд", "Тип", "Категория", "УК", "СЧА, млрд ₽",
                         "Комиссия УК, %", "Доходность 12 мес."]
        table["СЧА, млрд ₽"] = (table["СЧА, млрд ₽"] / 1e9).round(2)
        table["Комиссия УК, %"] = table["Комиссия УК, %"].round(2)
        table["Доходность 12 мес."] = (table["Доходность 12 мес."] * 100
                                       ).round(1)
        st.dataframe(table, use_container_width=True, height=460,
                     hide_index=True)

        st.subheader("Карточка фонда")
        options = view.sort_values("nav", ascending=False,
                                   na_position="last").fund_name.dropna().tolist()
        if not options:
            st.info("Ничего не найдено")
            return
        fund_name = st.selectbox("Фонд", options)
        fund = view[view.fund_name == fund_name].iloc[0]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("СЧА", nav_trln(fund.nav) if fund.nav and fund.nav > 1e11
                  else f"{fmt_num((fund.nav or 0) / 1e9, 1)} млрд ₽")
        m2.metric("Стоимость пая",
                  fmt_num(fund.unit_value, 2) if pd.notna(fund.unit_value) else "—")
        m3.metric("Комиссия УК",
                  pct(fund.uk_fee_value / 100, 2)
                  if pd.notna(fund.uk_fee_value) else "—",
                  help=str(fund.uk_fee_raw) if pd.notna(fund.uk_fee_raw) else None)
        m4.metric("Доходность 12 мес.",
                  pct(fund.return_12m, 1) if pd.notna(fund.return_12m) else "—")

        rows = {
            "Тип / категория": f"{fund.fund_type} / {fund.category}",
            "Статус": fund.status,
            "УК": f"[{fund.uk_name}]({fund.uk_website})" if pd.notna(
                fund.uk_website) else str(fund.uk_name),
            "Стратегия": fund.strategy_type,
            "Бенчмарк": fund.benchmark if pd.notna(fund.benchmark) else "—",
            "Совокупные расходы": (str(fund.max_total_expense_raw)
                                   if pd.notna(fund.max_total_expense_raw) else "—"),
            "Вознаграждение за успех": (str(fund.success_fee_raw)
                                        if fund.has_success_fee else "не предусмотрено"),
            "Доход от ДУ / выплаты": (f"{fund.income_right} / {fund.payment_frequency}"),
            "Пайщиков": fmt_num(fund.holders_total, 0),
            "Паёв у физлиц": pct(fund.holders_individuals / fund.holders_total, 1)
            if fund.holders_total else "—",
        }
        st.markdown("\n".join(f"- **{k}:** {v}" for k, v in rows.items()))

        with st.expander("Надбавки при выдаче"):
            st.write(str(fund.surcharges_raw) if pd.notna(fund.surcharges_raw)
                     else "—")
        with st.expander("Скидки при погашении"):
            st.write(str(fund.discounts_raw) if pd.notna(fund.discounts_raw)
                     else "—")

        ts = load_dash("fund_timeseries.csv")
        fts = ts[ts.rule_number == fund.rule_number].sort_values("report_date")
        if len(fts):
            left, right = st.columns(2)
            with left:
                fig = px.line(fts, x="report_date", y="nav", markers=True)
                fig.update_yaxes(title="СЧА, млрд ₽", tickformat=",.0f")
                st.plotly_chart(style_fig(fig), use_container_width=True)
            with right:
                fig = px.line(fts, x="report_date", y="unit_value", markers=True)
                fig.update_yaxes(title="Стоимость пая")
                st.plotly_chart(style_fig(fig), use_container_width=True)


def page_data() -> None:
    st.header("Данные и качество")
    st.markdown(
        "Наборы данных формируются скриптами проекта из файлов ЦБ и "
        "коммитятся в репозиторий. Обновление: `make update`.")

    st.subheader("Отчёт валидации")
    st.markdown(load_quality_report())

    st.subheader("Скачать наборы (CSV)")
    cfg = load_config()
    ddir = ROOT / cfg["paths"]["dashboard_dir"]
    files = sorted(ddir.glob("*.csv"))
    for f in files:
        with open(f, "rb") as fh:
            st.download_button(f"⬇ {f.name}", fh.read(),
                               file_name=f.name, mime="text/csv")
    for f in sorted((ROOT / cfg["paths"]["processed_dir"]).glob("*.csv")):
        with open(f, "rb") as fh:
            st.download_button(f"⬇ processed/{f.name}", fh.read(),
                               file_name=f.name, mime="text/csv")


# --------------------------------------------------------------------- main --

PAGES = {
    "Обзор рынка": page_overview,
    "Потоки": page_flows,
    "Структура активов": page_assets,
    "Фонды для неквалов": page_showcase,
    "Данные": page_data,
}

page = st.sidebar.radio("Раздел", list(PAGES.keys()))
PAGES[page]()
st.sidebar.caption(DISCLAIMER)
