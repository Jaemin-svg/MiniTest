"""철스크랩 협력사 입고 리스크 모니터링 대시보드 — Streamlit 진입점."""

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

import config as C
from modules import charts, exporter, loader
from modules import metrics as M
from modules import risk as R

ROOT = Path(__file__).resolve().parent
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

TAB_SUMMARY, TAB_RISK, TAB_ALL, TAB_DETAIL = "📊 전체 현황 요약", "🚨 리스크 업체", "📋 전체 협력사 현황", "🔍 협력사 상세"
FILTER_KEYS = ["f_region", "f_item", "f_grade", "f_level", "search"]
TH_KEYS = {k: f"th_{k}" for k in C.DEFAULT_THRESHOLDS}

st.set_page_config(page_title="철스크랩 협력사 리스크 모니터링", page_icon="🏭", layout="wide")


# ── 캐시 래퍼 ───────────────────────────────────────────────────────
# 업로드 데이터가 서버 메모리에 무한히 쌓이지 않도록 개수·유효시간 제한
CACHE = dict(show_spinner=False, max_entries=16, ttl=3600)


@st.cache_data(**CACHE)
def cached_sheets(file_bytes: bytes, filename: str) -> list[str]:
    return loader.list_sheets(file_bytes, filename)


@st.cache_data(**CACHE)
def cached_data_sheet(file_bytes: bytes, filename: str, sheets: tuple[str, ...]) -> int:
    return loader.detect_data_sheet(file_bytes, filename, list(sheets))


@st.cache_data(**CACHE)
def cached_load(file_bytes: bytes, filename: str, sheet: str | None) -> loader.LoadResult:
    return loader.load_data(file_bytes, filename, sheet)


@st.cache_data(**CACHE)
def cached_validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return M.validate_data(df)


@st.cache_data(show_spinner=False, max_entries=64, ttl=3600)
def cached_metrics(df: pd.DataFrame, ref: pd.Timestamp, history: int, ach_min: float) -> pd.DataFrame:
    return M.compute_supplier_metrics(df, ref, history, ach_min)


@st.cache_data(show_spinner=False)
def cached_template() -> bytes:
    return exporter.build_template()


# ── 표시 형식 ───────────────────────────────────────────────────────
def fmt_pct(v: float, signed: bool = False, na: str = "데이터 부족") -> str:
    if pd.isna(v):
        return na
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def fmt_ton(v: float) -> str:
    return "-" if pd.isna(v) else f"{v:,.0f}톤"


def show_chart(fig) -> None:
    st.plotly_chart(fig, theme=None, width="stretch",
                    config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def tint(color: str, alpha: float = 0.16) -> str:
    h = color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


TON = "%,.1f톤"
COLUMN_FORMATS = {
    R.RISK_LEVEL: st.column_config.TextColumn(pinned=True, width=96),
    C.COL_NAME: st.column_config.TextColumn(pinned=True),
    C.COL_CODE: st.column_config.TextColumn("코드", width="small"),
    C.COL_REGION: st.column_config.TextColumn(width="small"),
    C.COL_GRADE: st.column_config.TextColumn(width="small"),
    M.M_MAIN_ITEM: st.column_config.TextColumn("주요품목", width="small"),
    M.M_CONSEC: st.column_config.NumberColumn("연속미달", format="%d개월", width="small"),
    M.M_ACTUAL: st.column_config.NumberColumn("당월 입고량", format=TON),
    M.M_TARGET: st.column_config.NumberColumn("당월 목표량", format=TON),
    M.M_ACH: st.column_config.ProgressColumn("달성률", format="%.1f%%", width="small", min_value=0, max_value=120,
                                             help="당월 입고량 ÷ 당월 목표량 (막대는 120%에서 가득 참)"),
    M.M_HIST: st.column_config.NumberColumn(format=TON, help="기준월을 제외한 직전 N개월 평균"),
    M.M_CHG: st.column_config.NumberColumn("과거평균 대비", format="%+.1f%%", help="(당월 − 과거 평균) ÷ 과거 평균"),
    M.M_MOM: st.column_config.NumberColumn(format="%+.1f%%"),
    M.M_YTD: st.column_config.NumberColumn(format=TON, help="연초(또는 데이터 시작월) ~ 기준월 누적"),
    M.M_CONTRACT: st.column_config.NumberColumn(format="%,.0f톤"),
    M.M_FULFILL: st.column_config.NumberColumn(format="%.1f%%", help="누적 입고량 ÷ 연간 계약량"),
    M.M_AMOUNT: st.column_config.NumberColumn(format="%,.0f원"),
    M.M_PRICE: st.column_config.NumberColumn(format="%,.0f원"),
    R.RISK_REASON: st.column_config.TextColumn(width="medium"),
}

RISK_TABLE_COLUMNS = [
    R.RISK_LEVEL, C.COL_NAME, C.COL_CODE, C.COL_REGION, C.COL_GRADE, M.M_MAIN_ITEM,
    M.M_ACTUAL, M.M_TARGET, M.M_ACH, M.M_CHG, M.M_CONSEC, R.RISK_REASON, M.M_NOTE,
]
ALL_TABLE_COLUMNS = [
    R.RISK_LEVEL, C.COL_NAME, C.COL_CODE, C.COL_REGION, C.COL_GRADE, M.M_ITEMS,
    M.M_ACTUAL, M.M_TARGET, M.M_ACH, M.M_HIST, M.M_CHG, M.M_MOM, M.M_YTD, M.M_CONTRACT,
    M.M_FULFILL, M.M_CONSEC, M.M_AMOUNT, M.M_PRICE, R.RISK_REASON, M.M_NOTE,
]


def styled_table(df: pd.DataFrame, cols: list[str], th: dict):
    """리스크 등급 배지 + 증감률·연속 미달 조건부 색상."""
    view = df[cols].copy()
    levels = view[R.RISK_LEVEL]
    view[R.RISK_LEVEL] = levels.map(C.risk_label)
    bg_level = {C.risk_label(l): f"background-color: {tint(c)}" for l, c in C.RISK_COLORS.items()}
    danger = f"background-color: {tint(C.RISK_COLORS[C.RISK_HIGH], 0.14)}"

    styler = view.style.map(lambda v: bg_level.get(v, ""), subset=[R.RISK_LEVEL])
    if M.M_CHG in cols:
        styler = styler.map(lambda v: danger if pd.notna(v) and v <= th["change_max"] else "", subset=[M.M_CHG])
    if M.M_CONSEC in cols:
        styler = styler.map(lambda v: danger if v >= th["consecutive_min"] else "", subset=[M.M_CONSEC])
    return styler


def reset_filters() -> None:
    for k in FILTER_KEYS:
        st.session_state.pop(k, None)


def reset_thresholds() -> None:
    for k, key in TH_KEYS.items():
        st.session_state[key] = C.DEFAULT_THRESHOLDS[k]


def on_all_table_select() -> None:
    """전체 협력사 표에서 행 선택 → 협력사 상세 탭으로 이동."""
    rows = st.session_state["all_table"].selection.rows
    codes = st.session_state.get("_all_view_codes", [])
    if rows and rows[0] < len(codes):
        st.session_state["_goto_code"] = codes[rows[0]]
        st.session_state["main_tab"] = TAB_DETAIL


dark = st.context.theme.type == "dark"
P = charts.palette(dark)

# ── 사이드바 ①: 데이터 업로드 ────────────────────────────────────────
with st.sidebar:
    st.subheader("① 데이터 업로드")
    uploaded = st.file_uploader(
        "입고 실적 파일 (xlsx · xls · csv)", type=["xlsx", "xls", "csv"],
        help="한 행 = 한 협력사·한 품목의 한 달 실적. 과거 실적은 이전 기준월 행으로 넣어 주세요.",
    )
    if uploaded is not None:
        file_bytes, filename = uploaded.getvalue(), uploaded.name
    else:
        sample = ROOT / C.SAMPLE_DATA_PATH
        if not sample.exists():
            st.error("샘플 데이터가 없습니다. 터미널에서 `python scripts/make_sample.py`를 실행하세요.")
            st.stop()
        file_bytes, filename = sample.read_bytes(), sample.name
        st.caption("📎 파일을 올리지 않아 **샘플 데이터**로 보여 줍니다.")

    try:
        sheets = cached_sheets(file_bytes, filename)
    except Exception:
        st.error(f"'{filename}' 파일을 열 수 없습니다. 엑셀(xlsx/xls) 또는 CSV 형식인지, 암호가 걸려 있지 않은지 확인하세요.")
        st.stop()
    sheet = st.selectbox(
        "시트 선택", sheets, index=cached_data_sheet(file_bytes, filename, tuple(sheets)),
        help="필수 컬럼이 있는 첫 시트를 자동으로 고릅니다. 다른 시트를 보려면 바꾸세요.",
    ) if len(sheets) > 1 else None
    st.download_button("📄 입력 양식 템플릿", cached_template(), file_name="철스크랩_입고실적_템플릿.xlsx",
                       mime=XLSX_MIME, width="stretch", help="필수 컬럼 10개와 예시 5행이 들어 있는 양식입니다.")

# ── 헤더 · 로드 · 검증 ──────────────────────────────────────────────
st.title("🏭 철스크랩 협력사 입고 리스크 모니터링")
header = st.empty()

with st.spinner("파일을 읽는 중..."):
    try:
        result = cached_load(file_bytes, filename, sheet)
    except Exception as e:
        st.error(f"'{filename}'{f' / {sheet}' if sheet else ''}을(를) 읽는 중 문제가 생겼습니다: {e}")
        st.stop()

if not result.ok:
    found = ", ".join(map(str, result.df.columns[:12])) or "(없음)"
    st.error(
        "**필수 컬럼이 없어 분석할 수 없습니다.**\n\n"
        + "\n".join(f"- '{c}' 컬럼이 없습니다." for c in result.missing_columns)
        + f"\n\n현재 파일의 컬럼: {found}\n\n"
        "사이드바의 **입력 양식 템플릿**과 컬럼명을 맞춰 주세요. 공백·괄호·단위 표기 차이는 자동으로 인식합니다."
        + ("\n\n다른 시트에 데이터가 있다면 사이드바에서 **시트 선택**을 바꿔 보세요." if sheet else "")
    )
    st.stop()

data, issues = cached_validate(result.df)
if data.empty:
    st.error("계산할 수 있는 행이 없습니다. 아래 검증 결과에서 오류 내용을 확인해 주세요.")
    st.dataframe(issues, hide_index=True, width="stretch")
    st.stop()

months = M.available_months(data)
all_items = sorted(data[C.COL_ITEM].dropna().unique())
ITEM_COLORS = charts.item_colors(all_items, dark)

# ── 사이드바 ②~④ ───────────────────────────────────────────────────
with st.sidebar:
    st.subheader("② 분석 설정")
    ref_label = st.selectbox("분석 기준월", [f"{m:%Y-%m}" for m in reversed(months)],
                             help="이 달의 실적을 목표·과거 평균과 비교합니다. 기본값은 데이터의 최신 월입니다.")
    ref_month = pd.Timestamp(f"{ref_label}-01")
    history = st.segmented_control(
        "과거 평균 기간", C.HISTORY_MONTH_OPTIONS, default=C.DEFAULT_HISTORY_MONTHS, required=True,
        format_func=lambda n: f"{n}개월",
        help="기준월을 제외한 직전 N개월 평균과 비교합니다. 기준월 실적이 없어도 이 기간 안에 실적이 있으면 "
             "기준월 0톤(입고 중단)으로 봅니다.",
    )

    st.subheader("③ 필터")
    f_region = st.multiselect("지역", sorted(data[C.COL_REGION].dropna().unique()), placeholder="전체", key="f_region")
    f_item = st.multiselect("품목", all_items, placeholder="전체", key="f_item",
                            help="선택한 품목만 합산해 협력사 지표를 다시 계산합니다.")
    f_grade = st.multiselect("협력사 등급", sorted(data[C.COL_GRADE].dropna().unique()), placeholder="전체", key="f_grade")
    f_level = st.multiselect("리스크 등급", C.RISK_LEVELS, placeholder="전체", key="f_level",
                             format_func=C.risk_label)
    st.button("↺ 필터 초기화", on_click=reset_filters, width="stretch")

    st.subheader("④ 리스크 기준")
    d = C.DEFAULT_THRESHOLDS
    for k, key in TH_KEYS.items():
        st.session_state.setdefault(key, d[k])
    with st.expander("기준값 조정", icon="⚙️"):
        th = {
            "achievement_min": st.number_input("R1 목표 미달 — 달성률 < (%)", 0.0, 200.0, step=5.0,
                                               key=TH_KEYS["achievement_min"],
                                               help="R3 연속 미달의 '미달' 기준으로도 쓰입니다."),
            "change_max": st.number_input("R2 입고량 급감 — 증감률 ≤ (%)", -100.0, 0.0, step=5.0,
                                          key=TH_KEYS["change_max"]),
            "consecutive_min": st.number_input("R3 지속 부진 — 연속 미달 ≥ (개월)", 1, 12, step=1,
                                               key=TH_KEYS["consecutive_min"]),
            "contract_gap_pp": st.number_input("R4 계약 이행 지연 — 경과율보다 부족 (%p)", 0.0, 100.0, step=5.0,
                                               key=TH_KEYS["contract_gap_pp"],
                                               help="계약 이행률 < 기간 경과율 − 이 값이면 해당"),
            "high_risk_achievement": st.number_input("고위험 — 달성률 < (%)", 0.0, 200.0, step=5.0,
                                                     key=TH_KEYS["high_risk_achievement"]),
            "high_risk_rule_count": st.number_input("고위험 — 해당 규칙 수 ≥", 1, 5, step=1,
                                                    key=TH_KEYS["high_risk_rule_count"]),
        }
        st.button("기본값으로 되돌리기", on_click=reset_thresholds, width="stretch")

# ── 계산 파이프라인 ─────────────────────────────────────────────────
with st.spinner("협력사 지표를 계산하는 중..."):
    rows = data
    if f_region:
        rows = rows[rows[C.COL_REGION].isin(f_region)]
    if f_item:
        rows = rows[rows[C.COL_ITEM].isin(f_item)]
    if f_grade:
        rows = rows[rows[C.COL_GRADE].isin(f_grade)]

    # B2: 기준월 행이 없지만 최근 실적이 있는 협력사는 기준월 0톤 행으로 채워 KPI·차트·표 모두에 반영
    rows = M.fill_missing_ref_rows(rows, ref_month, history)
    classified = R.classify(cached_metrics(rows, ref_month, history, float(th["achievement_min"])), th)
    analyzed_codes = set(classified[C.COL_CODE])
    inactive = sorted(set(rows.loc[rows[C.COL_MONTH] <= ref_month, C.COL_CODE]) - analyzed_codes)
    zero_filled = classified.loc[classified[M.M_NOTE].str.contains("기준월 실적 없음", na=False), C.COL_NAME].tolist()
    prev_month = M.previous_month(months, ref_month)
    classified_prev = (R.classify(cached_metrics(rows, prev_month, history, float(th["achievement_min"])), th)
                       if prev_month is not None else None)
    if f_level:
        classified = classified[classified[R.RISK_LEVEL].isin(f_level)].reset_index(drop=True)

    rows = rows[rows[C.COL_CODE].isin(classified[C.COL_CODE])]
    ref_rows = rows[rows[C.COL_MONTH] == ref_month]
    monthly = M.monthly_totals(rows[rows[C.COL_MONTH] <= ref_month])
    risky = classified[classified[R.RISK_LEVEL] != C.RISK_NORMAL]

total_actual = ref_rows[C.COL_ACTUAL].sum()
total_target = ref_rows[C.COL_TARGET].sum()
total_ach = M.achievement(ref_rows)
total_chg = M.overall_change(rows, ref_month, history)
n_high = int((classified[R.RISK_LEVEL] == C.RISK_HIGH).sum())
n_caution = int((classified[R.RISK_LEVEL] == C.RISK_CAUTION).sum())

summary = pd.DataFrame({
    "항목": ["분석 기준월", "과거 평균 기간", "협력사 수", "당월 입고량(톤)", "당월 목표량(톤)", "전체 달성률(%)",
           "과거평균 대비 증감률(%)", "고위험 업체 수", "주의 업체 수", "원본 파일"],
    "값": [f"{ref_month:%Y-%m}", f"{history}개월", len(classified), round(total_actual, 1), round(total_target, 1),
          None if pd.isna(total_ach) else round(total_ach, 1), None if pd.isna(total_chg) else round(total_chg, 1),
          n_high, n_caution, filename],
})

# ── 사이드바 ⑤ 다운로드 ────────────────────────────────────────────
with st.sidebar:
    st.subheader("⑤ 다운로드")
    st.download_button("📥 전체 분석 결과 (엑셀)", exporter.build_report(summary, classified, th),
                       file_name=exporter.export_filename(ref_month), mime=XLSX_MIME, width="stretch",
                       type="primary", help="요약 · 전체 협력사 · 리스크 업체 · 적용 기준 4개 시트")

# ── 헤더 정보 · 알림 ───────────────────────────────────────────────
active_filters = [f"{n}: {', '.join(v)}" for n, v in
                  (("지역", f_region), ("품목", f_item), ("등급", f_grade), ("리스크", f_level)) if v]
header.markdown(
    f":blue-badge[:material/calendar_month: 기준월 {ref_month:%Y-%m}] "
    f":gray-badge[과거 평균 {history}개월] "
    f":gray-badge[데이터 {months[0]:%Y-%m} ~ {months[-1]:%Y-%m}] "
    f":gray-badge[:material/description: {filename}{f' / {sheet}' if sheet else ''}]"
    + (f" :violet-badge[:material/filter_alt: {' · '.join(active_filters)}]" if active_filters else "")
)

n_err = int((issues[M.ISSUE_LEVEL] == M.LEVEL_ERROR).sum())
n_warn = int((issues[M.ISSUE_LEVEL] == M.LEVEL_WARN).sum())
renamed_note = ("컬럼명 자동 인식: " + ", ".join(f"{k} → {v}" for k, v in result.renamed_columns.items())
                if result.renamed_columns else "")
if n_err or n_warn:
    label = f"데이터 검증 — 오류 {n_err}건(계산 제외) · 경고 {n_warn}건"
    with st.expander(label, icon="⚠️" if n_err else "ℹ️", expanded=bool(n_err)):
        if renamed_note:
            st.caption(renamed_note)
        st.dataframe(issues, hide_index=True, width="stretch")
elif renamed_note:
    st.caption(f"ℹ️ {renamed_note}")

with st.expander("데이터 미리보기 (상위 10행)", icon="📄"):
    preview = result.df.head(10).copy()
    preview[C.COL_MONTH] = preview[C.COL_MONTH].dt.strftime("%Y-%m")
    for col in preview.select_dtypes("object").columns:  # '1,234'·'abc'가 섞인 숫자 컬럼은 원본 그대로 문자열로 표시
        preview[col] = preview[col].astype("string")
    preview_formats = {  # 숫자로 읽힌 컬럼만 천 단위 콤마 (문자가 섞인 컬럼은 원본 표시)
        col: st.column_config.NumberColumn(format="%,.1f" if col == C.COL_ACTUAL else "%,.0f")
        for col in C.NUMERIC_COLUMNS if pd.api.types.is_numeric_dtype(preview[col])
    }
    st.dataframe(preview, hide_index=True, width="stretch", column_config=preview_formats)
    st.caption(f"전체 {len(result.df):,}행 · 협력사 {data[C.COL_CODE].nunique():,}개 · "
               f"기간 {months[0]:%Y-%m} ~ {months[-1]:%Y-%m}")

notes = []
if zero_filled:
    notes.append(f"기준월 실적이 없어 **0톤(입고 중단)으로 처리**한 협력사 {len(zero_filled)}개: "
                 + ", ".join(zero_filled[:6]) + (" 외" if len(zero_filled) > 6 else ""))
if inactive:
    notes.append(f"최근 {history}개월 실적이 없어 분석에서 제외된 협력사 {len(inactive)}개: "
                 + ", ".join(inactive[:10]) + (" ..." if len(inactive) > 10 else ""))
for n in notes:
    st.caption(f"ℹ️ {n}")

if n_high:
    names = classified.loc[classified[R.RISK_LEVEL] == C.RISK_HIGH, C.COL_NAME].tolist()
    st.error(f"**고위험 협력사 {n_high}개** — {', '.join(names[:6])}{' 외' if len(names) > 6 else ''}"
             " · 리스크 업체 탭에서 사유를 확인하세요.", icon="🚨")

tab_summary, tab_risk, tab_all, tab_detail = st.tabs([TAB_SUMMARY, TAB_RISK, TAB_ALL, TAB_DETAIL],
                                                     key="main_tab", on_change="rerun")

if classified.empty:
    for tab in (tab_summary, tab_risk, tab_all, tab_detail):
        with tab:
            st.info("선택한 조건에 맞는 협력사가 없습니다. 사이드바에서 **필터 초기화**를 눌러 보세요.", icon="🔎")
    st.stop()

# ── 탭1: 전체 현황 요약 ─────────────────────────────────────────────
with tab_summary:
    prev = monthly[monthly[C.COL_MONTH] == prev_month].iloc[0] if prev_month in set(monthly[C.COL_MONTH]) else None
    prev_high = prev_caution = None
    if classified_prev is not None:
        cp = classified_prev[classified_prev[C.COL_CODE].isin(classified[C.COL_CODE])]
        prev_high = int((cp[R.RISK_LEVEL] == C.RISK_HIGH).sum())
        prev_caution = int((cp[R.RISK_LEVEL] == C.RISK_CAUTION).sum())

    k = st.columns(6)
    k[0].metric("협력사 수", f"{len(classified):,}개", border=True, help="기준월 분석 대상 (필터 적용)")
    k = k[1:]
    k[0].metric("입고량(톤)", f"{total_actual:,.0f}",
                f"{total_actual - prev[C.COL_ACTUAL]:+,.0f}" if prev is not None else None, border=True,
                help=f"당월 입고량 합계 · 전월 대비 증감")
    k[1].metric("달성률", fmt_pct(total_ach, na="N/A"),
                f"{total_ach - prev[M.M_ACH]:+.1f}%p" if prev is not None and pd.notna(prev[M.M_ACH]) else None,
                border=True, help=f"전월 대비 증감 · 당월 목표량 {fmt_ton(total_target)} · 목표량 0인 행의 입고량은 제외")
    k[2].metric("평균 대비", fmt_pct(total_chg, signed=True), border=True,
                help=f"과거 {history}개월 평균 대비 증감률 (전체 입고량 합계 기준, 기준월 제외)")
    k[3].metric(C.risk_label(C.RISK_HIGH), f"{n_high}개",
                f"{n_high - prev_high:+d}" if prev_high is not None else None,
                delta_color="inverse", border=True, help="전월 대비 증감 (늘어나면 빨간색)")
    k[4].metric(C.risk_label(C.RISK_CAUTION), f"{n_caution}개",
                f"{n_caution - prev_caution:+d}" if prev_caution is not None else None,
                delta_color="inverse", border=True, help="전월 대비 증감 (늘어나면 빨간색)")
    st.caption(f"협력사 {len(classified)}개 · 증감 표시는 전월({prev_month:%Y-%m}) 대비" if prev_month is not None
               else f"협력사 {len(classified)}개 · 전월 데이터가 없어 증감을 표시하지 않습니다")

    c1, c2 = st.columns([2, 1], gap="medium")
    with c1:
        show_chart(charts.trend_chart(monthly, dark=dark))
        with st.expander("표로 보기"):
            t = monthly.assign(**{C.COL_MONTH: monthly[C.COL_MONTH].dt.strftime("%Y-%m")})
            st.dataframe(t, hide_index=True, width="stretch", column_config={
                C.COL_ACTUAL: st.column_config.NumberColumn(format=TON),
                C.COL_TARGET: st.column_config.NumberColumn(format=TON),
                M.M_ACH: st.column_config.NumberColumn(format="%.1f%%"),
            })
    with c2:
        show_chart(charts.risk_donut(classified, dark=dark))
    c3, c4 = st.columns(2, gap="medium")
    with c3:
        show_chart(charts.category_bar(ref_rows, C.COL_REGION, dark=dark))
    with c4:
        show_chart(charts.category_bar(ref_rows, C.COL_ITEM, dark=dark))

# ── 탭2: 리스크 업체 ───────────────────────────────────────────────
with tab_risk:
    if risky.empty:
        st.success("현재 조건에서 리스크 업체가 없습니다. 모든 협력사가 기준을 충족합니다.", icon="✅")
    else:
        h1, h2 = st.columns([3, 1], vertical_alignment="bottom")
        h1.subheader(f"리스크 업체 {len(risky)}개")
        h1.caption(f"{C.risk_label(C.RISK_HIGH)} {n_high}개 · {C.risk_label(C.RISK_CAUTION)} {n_caution}개 — "
                   "고위험 → 주의, 같은 등급은 A등급·달성률 낮은 순")
        h2.download_button("📥 리스크 업체 목록", exporter.build_table(risky[RISK_TABLE_COLUMNS], "리스크 업체"),
                           file_name=f"리스크업체_{ref_month:%Y%m}.xlsx", mime=XLSX_MIME, width="stretch")
        st.dataframe(styled_table(risky, RISK_TABLE_COLUMNS, th), hide_index=True, width="stretch",
                     column_config=COLUMN_FORMATS, height=min(38 + 35 * len(risky), 520))
    show_chart(charts.quadrant_scatter(classified, th, dark=dark))
    st.caption("버블 크기 = 연간 계약량 · 점선 = 리스크 기준(달성률, 증감률) · 붉은 영역은 목표 미달이면서 입고가 급감한 구간")
    with st.expander("적용 중인 리스크 기준"):
        st.dataframe(R.rule_descriptions(th), hide_index=True, width="stretch")

# ── 탭3: 전체 협력사 현황 ───────────────────────────────────────────
with tab_all:
    s1, s2 = st.columns([2, 3], vertical_alignment="bottom")
    query = s1.text_input("협력사 검색", placeholder="이름 또는 코드 (예: 대한, V001)", key="search")
    view = classified
    if query:
        q = query.strip()
        view = view[view[C.COL_NAME].str.contains(q, case=False, regex=False)
                    | view[C.COL_CODE].str.contains(q, case=False, regex=False)]
    s2.caption(f"{len(view)}개 협력사 · 행을 클릭하면 **협력사 상세** 탭으로 이동합니다.")
    st.session_state["_all_view_codes"] = view[C.COL_CODE].tolist()
    st.dataframe(styled_table(view, ALL_TABLE_COLUMNS, th), hide_index=True, width="stretch",
                 column_config=COLUMN_FORMATS, key="all_table", on_select=on_all_table_select,
                 selection_mode="single-row")
    show_chart(charts.ranking_bar(view, th, dark=dark))

# ── 탭4: 협력사 상세 ───────────────────────────────────────────────
with tab_detail:
    # 옵션 목록이 바뀌거나 표에서 이동할 때마다 새 key로 위젯을 만들어, 화면 표시와 선택값이 어긋나지 않게 한다.
    codes_now = classified[C.COL_CODE].tolist()
    labels = [f"{n} ({c})" for c, n in zip(codes_now, classified[C.COL_NAME])]
    label_to_code = dict(zip(labels, codes_now))
    goto = st.session_state.pop("_goto_code", None)
    if goto is not None:
        st.session_state["detail_code"] = goto
        st.session_state["detail_nonce"] = st.session_state.get("detail_nonce", 0) + 1
    wanted = st.session_state.get("detail_code")
    sig = hashlib.md5("|".join(codes_now).encode()).hexdigest()[:8]
    code = label_to_code[st.selectbox(
        "협력사 선택", labels, index=codes_now.index(wanted) if wanted in codes_now else 0,
        key=f"detail_{st.session_state.get('detail_nonce', 0)}_{sig}",
        help="목록은 리스크 등급 순입니다. 전체 협력사 표에서 행을 클릭해도 이동합니다.",
    )]
    st.session_state["detail_code"] = code
    s = classified[classified[C.COL_CODE] == code].iloc[0]
    level = s[R.RISK_LEVEL]

    with st.container(border=True):
        a, b = st.columns([3, 2], vertical_alignment="center")
        with a:
            st.markdown(f"### {s[C.COL_NAME]} <small style='opacity:.6'>{code}</small>", unsafe_allow_html=True)
            st.badge(C.risk_label(level), color=C.RISK_BADGE_COLORS[level])
            reasons = [C.RISK_REASONS[r] for r in R.RULE_IDS if s[r]]
            st.markdown("**리스크 사유:** " + (" · ".join(reasons) if reasons else "해당 없음"))
        with b:
            st.markdown(
                f"**지역** {s[C.COL_REGION]} &nbsp;·&nbsp; **등급** {s[C.COL_GRADE]}  \n"
                f"**연간 계약량** {fmt_ton(s[M.M_CONTRACT])}  \n"
                f"**취급 품목** {s[M.M_ITEMS]} (주요: {s[M.M_MAIN_ITEM]})"
            )
            if s[M.M_NOTE]:
                st.caption(f"비고: {s[M.M_NOTE]}")

    j = st.columns(5)
    has_target = pd.notna(s[M.M_TARGET]) and s[M.M_TARGET] > 0
    j[0].metric("당월 입고량 (톤)", f"{s[M.M_ACTUAL]:,.0f}",
                f"{s[M.M_MOM]:+.1f}%" if pd.notna(s[M.M_MOM]) else None, border=True, help="증감 표시는 전월 대비")
    j[1].metric("목표 달성률", fmt_pct(s[M.M_ACH]) if has_target else "N/A", border=True,
                help=f"당월 목표량 {fmt_ton(s[M.M_TARGET])}")
    j[2].metric(f"과거 {history}개월 대비", fmt_pct(s[M.M_CHG], signed=True), border=True,
                help=f"과거 평균 {fmt_ton(s[M.M_HIST])}")
    j[3].metric("계약 이행률", fmt_pct(s[M.M_FULFILL], na="N/A"), f"경과율 {s[M.M_ELAPSED]:.1f}%",
                delta_color="off", delta_arrow="off", border=True)
    j[4].metric("연속 미달", f"{int(s[M.M_CONSEC])}개월", border=True)

    figs = charts.supplier_detail_charts(rows, code, ref_month, ITEM_COLORS, dark=dark)
    show_chart(figs["trend"])
    d1, d2 = st.columns(2, gap="medium")
    with d1:
        show_chart(figs["items"])
    with d2:
        show_chart(figs["price"])

    st.markdown("**리스크 규칙 판정**")
    rules = R.rule_descriptions(th).iloc[:5].copy()
    rules.insert(0, "판정", ["🔴 해당" if s[r] else "—" for r in R.RULE_IDS])
    st.dataframe(rules, hide_index=True, width="stretch")
