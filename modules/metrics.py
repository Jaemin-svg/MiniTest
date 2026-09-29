"""데이터 검증(PRD 4.3)과 협력사별 지표 계산(PRD F3)."""

import numpy as np
import pandas as pd

import config as C

# ── 지표 컬럼명 ─────────────────────────────────────────────────────
M_MAIN_ITEM = "주요 품목"
M_ITEMS = "취급 품목"
M_ACTUAL = "당월 입고량(톤)"
M_TARGET = "당월 목표량(톤)"
M_ACH = "목표 달성률(%)"
M_HIST = "과거 평균 입고량(톤)"
M_HIST_N = "과거 데이터(개월)"
M_CHG = "과거평균 대비 증감률(%)"
M_MOM = "전월 대비 증감률(%)"
M_YTD = "누적 입고량(톤)"
M_CONTRACT = "연간 계약량(톤)"
M_FULFILL = "계약 이행률(%)"
M_ELAPSED = "기간 경과율(%)"
M_CONSEC = "연속 미달(개월)"
M_AMOUNT = "입고 금액(원)"
M_PRICE = "가중평균 단가(원/톤)"
M_NOTE = "비고"

METRIC_COLUMNS = [
    C.COL_CODE, C.COL_NAME, C.COL_REGION, C.COL_GRADE, M_MAIN_ITEM, M_ITEMS,
    M_ACTUAL, M_TARGET, M_ACH, M_HIST, M_HIST_N, M_CHG, M_MOM, M_YTD,
    M_CONTRACT, M_FULFILL, M_ELAPSED, M_CONSEC, M_AMOUNT, M_PRICE, M_NOTE,
]

ISSUE_ROW, ISSUE_LEVEL, ISSUE_COL, ISSUE_MSG = "행 번호", "구분", "항목", "내용"
LEVEL_ERROR, LEVEL_WARN = "오류", "경고"

_AMOUNT = "_amount"


def _pct(num: pd.Series, den: pd.Series) -> pd.Series:
    """num / den × 100. 분모가 0 또는 NaN이면 NaN."""
    return (num / den.where(den > 0)) * 100


# ── 검증 ───────────────────────────────────────────────────────────
def validate_data(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """PRD 4.3 검증.

    - 오류(계산 제외): 기준월 인식 불가, 협력사코드/품목 누락, 숫자 컬럼 빈 값·문자·음수
    - 경고(계산 포함): 월목표량 0, 기준월+협력사코드+품목 중복(합산), 과거 데이터 3개월 미만

    행 번호는 엑셀 기준(헤더 1행 + 1)이며 loader가 유지한 원본 index에서 계산한다.

    Returns:
        (정제된 DataFrame, 문제 목록 DataFrame[행 번호, 구분, 항목, 내용])
    """
    issues: list[dict] = []

    def add(mask: pd.Series, level: str, col: str, msg) -> None:
        for i in mask.index[mask.to_numpy(dtype=bool)]:
            text = msg(i) if callable(msg) else msg
            issues.append({ISSUE_ROW: int(i) + 2, ISSUE_LEVEL: level, ISSUE_COL: col, ISSUE_MSG: text})

    work = df.copy()
    bad = pd.Series(False, index=work.index)

    m = work[C.COL_MONTH].isna()
    add(m, LEVEL_ERROR, C.COL_MONTH, "기준월 형식을 인식할 수 없음 → 계산 제외")
    bad |= m

    for col in (C.COL_CODE, C.COL_ITEM):
        m = work[col].fillna("").astype(str).str.strip().eq("")
        add(m, LEVEL_ERROR, col, "값 없음 → 계산 제외")
        bad |= m

    for col in C.NUMERIC_COLUMNS:
        orig = work[col]
        if pd.api.types.is_numeric_dtype(orig):
            num = pd.to_numeric(orig, errors="coerce")
        else:  # '1,234' 같은 천 단위 구분 기호 허용
            num = pd.to_numeric(orig.astype(str).str.replace(",", "").str.strip(), errors="coerce")
        m_empty = orig.isna()
        m_text = num.isna() & ~m_empty
        m_neg = num < 0
        add(m_empty, LEVEL_ERROR, col, "값 없음 → 계산 제외")
        add(m_text, LEVEL_ERROR, col, lambda i, o=orig: f"숫자가 아닌 값 '{o[i]}' → 계산 제외")
        add(m_neg, LEVEL_ERROR, col, lambda i, n=num: f"음수 값 {n[i]:g} → 계산 제외")
        bad |= m_empty | m_text | m_neg
        work[col] = num

    clean = work[~bad].copy()

    add(clean[C.COL_TARGET] == 0, LEVEL_WARN, C.COL_TARGET, "월목표량 0 → 달성률 N/A")

    exact = clean.duplicated(C.REQUIRED_COLUMNS, keep="first")
    add(exact, LEVEL_WARN, "전체 컬럼", "앞 행과 완전히 같은 중복 행 → 1행만 사용")
    clean = clean[~exact]

    dup = clean.duplicated(C.KEY_COLUMNS, keep=False)
    add(dup, LEVEL_WARN, "기준월+협력사코드+품목", "값이 다른 중복 행 → 입고량·목표량 합산")
    if dup.any():
        clean = _merge_duplicates(clean)

    months = clean[C.COL_MONTH].dropna().unique()
    if 0 < len(months) and len(months) - 1 < C.MIN_HISTORY_MONTHS:
        issues.append({
            ISSUE_ROW: None, ISSUE_LEVEL: LEVEL_WARN, ISSUE_COL: C.COL_MONTH,
            ISSUE_MSG: f"과거 데이터가 {len(months) - 1}개월뿐 → 과거평균 대비 증감률 '데이터 부족'",
        })

    issue_df = pd.DataFrame(issues, columns=[ISSUE_ROW, ISSUE_LEVEL, ISSUE_COL, ISSUE_MSG])
    issue_df[ISSUE_ROW] = issue_df[ISSUE_ROW].astype("Int64")
    return clean.reset_index(drop=True), issue_df


def _merge_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """중복 키 합산. 단가는 입고량 가중평균(입고량 0이면 단순평균), 계약량은 최대값."""
    d = df.assign(**{_AMOUNT: df[C.COL_ACTUAL] * df[C.COL_PRICE]})
    g = d.groupby(C.KEY_COLUMNS, as_index=False, sort=False).agg(
        **{
            C.COL_NAME: (C.COL_NAME, "first"),
            C.COL_REGION: (C.COL_REGION, "first"),
            C.COL_GRADE: (C.COL_GRADE, "first"),
            C.COL_CONTRACT: (C.COL_CONTRACT, "max"),
            C.COL_TARGET: (C.COL_TARGET, "sum"),
            C.COL_ACTUAL: (C.COL_ACTUAL, "sum"),
            _AMOUNT: (_AMOUNT, "sum"),
            "_price_mean": (C.COL_PRICE, "mean"),
        }
    )
    g[C.COL_PRICE] = np.where(g[C.COL_ACTUAL] > 0, g[_AMOUNT] / g[C.COL_ACTUAL].where(g[C.COL_ACTUAL] > 0), g["_price_mean"])
    return g[C.REQUIRED_COLUMNS]


# ── 지표 ───────────────────────────────────────────────────────────
def available_months(df: pd.DataFrame) -> list[pd.Timestamp]:
    """데이터에 존재하는 기준월 목록 (오름차순)."""
    return sorted(pd.Timestamp(m) for m in df[C.COL_MONTH].dropna().unique())


FILLED = "_filled"  # 기준월 실적이 없어 0톤으로 채운 행 표시


def fill_missing_ref_rows(df: pd.DataFrame, ref_month: pd.Timestamp, lookback_months: int) -> pd.DataFrame:
    """기준월 행이 없지만 직전 lookback_months개월 안에 실적이 있는 협력사·품목에 기준월 0톤 행을 추가.

    실데이터에서는 입고가 끊기면 행 자체가 없는 경우가 많아, 이렇게 채워야 R5(입고 중단)로 잡힌다.
    목표량·계약량·단가·속성은 해당 품목의 가장 최근 행 값을 쓴다. 이미 채운 df에 다시 호출해도 결과가 같다.
    """
    ref = pd.Timestamp(ref_month)
    present = set(df.loc[df[C.COL_MONTH] == ref, C.COL_CODE])
    window_start = ref - pd.DateOffset(months=lookback_months)
    recent = df[(df[C.COL_MONTH] >= window_start) & (df[C.COL_MONTH] < ref) & ~df[C.COL_CODE].isin(present)]
    if recent.empty:
        return df
    last = recent.sort_values(C.COL_MONTH).groupby([C.COL_CODE, C.COL_ITEM], as_index=False).tail(1)
    filled = last.assign(**{C.COL_MONTH: ref, C.COL_ACTUAL: 0.0, FILLED: True})
    base = df if FILLED in df.columns else df.assign(**{FILLED: False})
    return pd.concat([base, filled], ignore_index=True)


def _with_target_actual(df: pd.DataFrame) -> pd.DataFrame:
    """달성률 분자용: 목표량 > 0인 행의 입고량만 남긴 컬럼 추가 (목표 0 행이 달성률을 부풀리지 않게)."""
    return df.assign(_act_t=df[C.COL_ACTUAL].where(df[C.COL_TARGET] > 0, 0.0))


def achievement(rows: pd.DataFrame) -> float:
    """행 집합 전체의 목표 달성률(%). 목표량 0인 행의 입고량은 분자에서 제외."""
    target = rows[C.COL_TARGET].sum()
    if target <= 0:
        return float("nan")
    return rows.loc[rows[C.COL_TARGET] > 0, C.COL_ACTUAL].sum() / target * 100


def compute_supplier_metrics(
    df: pd.DataFrame,
    ref_month: pd.Timestamp,
    history_months: int = C.DEFAULT_HISTORY_MONTHS,
    achievement_min: float = C.DEFAULT_THRESHOLDS["achievement_min"],
) -> pd.DataFrame:
    """협력사 단위(품목 합산) 지표 계산.

    - 대상: 기준월 행이 있는 협력사 + 기준월 행은 없지만 직전 history_months개월 안에 실적이 있는
      협력사(기준월 0톤으로 간주, fill_missing_ref_rows).
    - 달성률: 목표량 > 0인 행의 입고량 ÷ 목표량. 목표량이 모두 0이면 NaN.
    - 과거 평균: 기준월 직전 N개 달력월(기준월 제외)의 월 입고량 평균. 데이터가 있는 달이
      MIN_HISTORY_MONTHS 미만이면 NaN(데이터 부족).
    - 누적/계약 이행률: 협력사별로 max(기준 연도 1월, 그 협력사의 첫 실적 월) ~ 기준월. 기간 경과율도
      같은 기간으로 계산해 연중 신규 협력사가 R4로 오판되지 않게 한다. 계약량은 연간 기준.
    - 연속 미달: 기준월부터 거꾸로 달성률 < achievement_min 인 달이 끊김 없이 이어진 수.
      데이터 없는 달·목표량 0인 달에서 끊긴다.
    """
    ref = pd.Timestamp(ref_month)
    d = fill_missing_ref_rows(df[df[C.COL_MONTH] <= ref], ref, history_months)
    cur_rows = d[d[C.COL_MONTH] == ref]
    if cur_rows.empty:
        return pd.DataFrame(columns=METRIC_COLUMNS)

    d = _with_target_actual(d).assign(**{_AMOUNT: d[C.COL_ACTUAL] * d[C.COL_PRICE]})
    codes = pd.Index(cur_rows[C.COL_CODE].unique(), name=C.COL_CODE)
    d = d[d[C.COL_CODE].isin(codes)]

    monthly = d.groupby([C.COL_CODE, C.COL_MONTH])[[C.COL_TARGET, C.COL_ACTUAL, "_act_t", _AMOUNT]].sum()
    months = pd.date_range(d[C.COL_MONTH].min(), ref, freq="MS")

    def grid(col: str) -> pd.DataFrame:
        return monthly[col].unstack(C.COL_MONTH).reindex(index=codes, columns=months)

    act, act_t, tgt, amt = grid(C.COL_ACTUAL), grid("_act_t"), grid(C.COL_TARGET), grid(_AMOUNT)
    cur, cur_t = act[ref], tgt[ref]

    hist_window = pd.date_range(ref - pd.DateOffset(months=history_months), periods=history_months, freq="MS")
    hist = act.reindex(columns=hist_window)
    hist_n = hist.notna().sum(axis=1)
    hist_avg = hist.mean(axis=1).where(hist_n >= min(C.MIN_HISTORY_MONTHS, history_months))

    prev = ref - pd.DateOffset(months=1)
    prev_act = act[prev] if prev in act.columns else pd.Series(np.nan, index=codes)

    # 누적 기간은 협력사별: max(연초, 첫 실적 월). 채운 0톤 행은 첫 실적 월 계산에서 제외.
    year_start = pd.Timestamp(ref.year, 1, 1)
    real = d[~d[FILLED].fillna(False).astype(bool)] if FILLED in d.columns else d
    period_start = real.groupby(C.COL_CODE)[C.COL_MONTH].min().reindex(codes).clip(lower=year_start)
    in_period = pd.DataFrame(months.values[None, :] >= period_start.values[:, None], index=codes, columns=months)
    ytd = act.where(in_period).sum(axis=1, min_count=1)
    ytd_rows = d[d[C.COL_MONTH] >= d[C.COL_CODE].map(period_start)].sort_values(C.COL_MONTH)
    contract = (
        ytd_rows.groupby([C.COL_CODE, C.COL_ITEM])[C.COL_CONTRACT].last().groupby(level=0).sum()
        .reindex(codes)
    )
    period_months = (ref.year - period_start.dt.year) * 12 + ref.month - period_start.dt.month + 1
    elapsed = period_months / C.CONTRACT_PERIOD_MONTHS * 100

    under = (_pct(act_t, tgt) < achievement_min)
    consec = pd.Series(0, index=codes)
    running = pd.Series(True, index=codes)
    for m in reversed(months):
        running &= under[m]
        consec += running.astype(int)

    cur_amount = amt[ref]

    latest = d.sort_values(C.COL_MONTH)
    attrs = latest.groupby(C.COL_CODE)[[C.COL_NAME, C.COL_REGION, C.COL_GRADE]].last().reindex(codes)
    by_item = cur_rows.groupby([C.COL_CODE, C.COL_ITEM])[[C.COL_ACTUAL, C.COL_TARGET]].sum()
    main_item = (
        by_item.assign(_k=by_item[C.COL_ACTUAL] + by_item[C.COL_TARGET] * 1e-9)["_k"]
        .groupby(level=0).idxmax().map(lambda t: t[1]).reindex(codes)
    )
    items = cur_rows.groupby(C.COL_CODE)[C.COL_ITEM].agg(lambda s: ", ".join(sorted(s.unique()))).reindex(codes)
    if FILLED in cur_rows.columns:
        filled_codes = set(cur_rows.loc[cur_rows[FILLED].fillna(False).astype(bool), C.COL_CODE])
    else:
        filled_codes = set()

    out = pd.DataFrame(index=codes)
    out[C.COL_NAME] = attrs[C.COL_NAME]
    out[C.COL_REGION] = attrs[C.COL_REGION]
    out[C.COL_GRADE] = attrs[C.COL_GRADE]
    out[M_MAIN_ITEM] = main_item
    out[M_ITEMS] = items
    out[M_ACTUAL] = cur
    out[M_TARGET] = cur_t
    out[M_ACH] = _pct(act_t[ref], cur_t)
    out[M_HIST] = hist_avg
    out[M_HIST_N] = hist_n
    out[M_CHG] = _pct(cur - hist_avg, hist_avg)
    out[M_MOM] = _pct(cur - prev_act, prev_act)
    out[M_YTD] = ytd
    out[M_CONTRACT] = contract
    out[M_FULFILL] = _pct(ytd, contract)
    out[M_ELAPSED] = elapsed
    out[M_CONSEC] = consec
    out[M_AMOUNT] = cur_amount
    out[M_PRICE] = cur_amount / cur.where(cur > 0)

    zero_target = cur_rows[cur_rows[C.COL_TARGET] == 0].groupby(C.COL_CODE).size().reindex(codes).fillna(0)
    notes = pd.Series("", index=codes)
    notes = notes.where(~codes.isin(filled_codes), notes + "기준월 실적 없음(0톤 처리); ")
    notes = notes.where(~(cur_t == 0), notes + "목표량 0(달성률 N/A); ")
    notes = notes.where(~((zero_target > 0) & (cur_t > 0)), notes + "목표량 0인 품목은 달성률에서 제외; ")
    notes = notes.where(hist_avg.notna(), notes + "과거 데이터 부족; ")
    started = period_start > year_start
    notes = notes.where(~started, notes + "누적 기간 " + period_start.dt.strftime("%Y-%m") + "~; ")
    out[M_NOTE] = notes.str.rstrip("; ")

    return out.reset_index()[METRIC_COLUMNS]


def monthly_totals(df: pd.DataFrame, group_cols: list[str] | None = None) -> pd.DataFrame:
    """월별 입고량·목표량·달성률 합계 (추이 차트용). 달성률 분자는 목표량 > 0인 행의 입고량."""
    keys = [C.COL_MONTH] + (group_cols or [])
    g = _with_target_actual(df).groupby(keys, as_index=False)[[C.COL_ACTUAL, C.COL_TARGET, "_act_t"]].sum()
    g[M_ACH] = _pct(g["_act_t"], g[C.COL_TARGET])
    return g.drop(columns="_act_t").sort_values(keys, ignore_index=True)


def category_totals(rows: pd.DataFrame, by: str) -> pd.DataFrame:
    """지역/품목 등 범주별 입고량·목표량·달성률 (달성률 분자는 목표량 > 0인 행의 입고량)."""
    g = _with_target_actual(rows).groupby(by, as_index=False)[[C.COL_ACTUAL, C.COL_TARGET, "_act_t"]].sum()
    g[M_ACH] = _pct(g["_act_t"], g[C.COL_TARGET])
    return g.drop(columns="_act_t")


def overall_change(df: pd.DataFrame, ref_month: pd.Timestamp, history_months: int) -> float:
    """전체 합계 기준 과거 평균 대비 증감률(%). 과거 데이터 부족 시 NaN."""
    ref = pd.Timestamp(ref_month)
    totals = df.groupby(C.COL_MONTH)[C.COL_ACTUAL].sum()
    window = pd.date_range(ref - pd.DateOffset(months=history_months), periods=history_months, freq="MS")
    hist = totals.reindex(window).dropna()
    if ref not in totals.index or len(hist) < min(C.MIN_HISTORY_MONTHS, history_months) or hist.mean() <= 0:
        return float("nan")
    return (totals[ref] - hist.mean()) / hist.mean() * 100


def previous_month(months: list[pd.Timestamp], ref_month: pd.Timestamp) -> pd.Timestamp | None:
    prev = pd.Timestamp(ref_month) - pd.DateOffset(months=1)
    return prev if prev in months else None
