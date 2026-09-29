"""앱 전역 설정: 컬럼 정의, 컬럼명 정규화 매핑, 리스크 기준 기본값."""

import re

# ── 표준 컬럼명 (PRD 4.2) ────────────────────────────────────────────
COL_MONTH = "기준월"
COL_CODE = "협력사코드"
COL_NAME = "협력사명"
COL_REGION = "지역"
COL_GRADE = "등급"
COL_ITEM = "품목"
COL_CONTRACT = "계약량(톤)"
COL_TARGET = "월목표량(톤)"
COL_ACTUAL = "실제입고량(톤)"
COL_PRICE = "단가(원/톤)"

REQUIRED_COLUMNS = [
    COL_MONTH, COL_CODE, COL_NAME, COL_REGION, COL_GRADE,
    COL_ITEM, COL_CONTRACT, COL_TARGET, COL_ACTUAL, COL_PRICE,
]
NUMERIC_COLUMNS = [COL_CONTRACT, COL_TARGET, COL_ACTUAL, COL_PRICE]
KEY_COLUMNS = [COL_MONTH, COL_CODE, COL_ITEM]

# 계약량은 연간 기준 (PRD 11장 잠정 결정)
CONTRACT_PERIOD_MONTHS = 12

# ── 컬럼명 정규화 ────────────────────────────────────────────────────
# 정규화 키(공백·괄호 내용 제거, 소문자) → 표준 컬럼명
COLUMN_ALIASES = {
    "기준월": COL_MONTH, "월": COL_MONTH, "년월": COL_MONTH, "입고월": COL_MONTH,
    "협력사코드": COL_CODE, "업체코드": COL_CODE, "코드": COL_CODE,
    "협력사명": COL_NAME, "협력사": COL_NAME, "업체명": COL_NAME,
    "지역": COL_REGION,
    "등급": COL_GRADE, "협력사등급": COL_GRADE,
    "품목": COL_ITEM, "품목명": COL_ITEM,
    "계약량": COL_CONTRACT, "연간계약량": COL_CONTRACT,
    "월목표량": COL_TARGET, "목표량": COL_TARGET,
    "실제입고량": COL_ACTUAL, "입고량": COL_ACTUAL, "실입고량": COL_ACTUAL,
    "단가": COL_PRICE, "입고단가": COL_PRICE,
}


def normalize_column_key(name) -> str:
    """'실제 입고량 (톤)' → '실제입고량' 처럼 비교용 키로 변환."""
    text = str(name)
    text = re.sub(r"[\(\[（].*?[\)\]）]", "", text)  # 괄호와 그 안의 단위 제거
    text = re.sub(r"\s+", "", text)
    return text.lower()


# ── 분석 설정 ────────────────────────────────────────────────────────
HISTORY_MONTH_OPTIONS = [3, 6, 12]
DEFAULT_HISTORY_MONTHS = 3
MIN_HISTORY_MONTHS = 3  # 이보다 과거 데이터가 적으면 증감률 "데이터 부족"

# ── 리스크 기준 기본값 (PRD F4-1, F4-2) ──────────────────────────────
DEFAULT_THRESHOLDS = {
    "achievement_min": 80.0,        # R1: 달성률 < 80% → 목표 미달
    "change_max": -20.0,            # R2: 과거 평균 대비 증감률 ≤ -20% → 입고량 급감
    "consecutive_min": 3,           # R3: 연속 미달 ≥ 3개월 → 지속 부진
    "contract_gap_pp": 10.0,        # R4: 계약 이행률 < 기간 경과율 - 10%p → 계약 이행 지연
    "high_risk_achievement": 50.0,  # 고위험: 달성률 < 50%
    "high_risk_rule_count": 3,      # 고위험: 해당 규칙 3개 이상
}

RISK_HIGH = "고위험"
RISK_CAUTION = "주의"
RISK_NORMAL = "정상"
RISK_LEVELS = [RISK_HIGH, RISK_CAUTION, RISK_NORMAL]

RISK_REASONS = {
    "R1": "목표 미달",
    "R2": "입고량 급감",
    "R3": "지속 부진",
    "R4": "계약 이행 지연",
    "R5": "입고 중단",
}

# 리스크 등급 = 상태(status) 색상. 차트·배지·표 전체에서 공통 사용하며, 항상 아이콘·라벨과 함께 표시.
RISK_COLORS = {RISK_HIGH: "#d03b3b", RISK_CAUTION: "#ec835a", RISK_NORMAL: "#0ca30c"}
RISK_ICONS = {RISK_HIGH: "🔴", RISK_CAUTION: "🟠", RISK_NORMAL: "🟢"}
RISK_BADGE_COLORS = {RISK_HIGH: "red", RISK_CAUTION: "orange", RISK_NORMAL: "green"}  # st.badge 색상명


def risk_label(level: str) -> str:
    return f"{RISK_ICONS.get(level, '')} {level}".strip()


# 차트 팔레트 (라이트/다크 각각 선택된 값, dataviz 검증 통과: 범주형 1~4 인접 CVD ΔE ≥ 8.4)
CHART_THEMES = {
    "light": {
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "reference": "#52514e", "target_fill": "#c3c2b7",
        "risk_zone": "rgba(208,59,59,0.06)",
    },
    "dark": {
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
        "surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "reference": "#c3c2b7", "target_fill": "#52514e",
        "risk_zone": "rgba(208,59,59,0.12)",
    },
}
CHART_FONT = '"Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", system-ui, -apple-system, "Segoe UI", sans-serif'

SAMPLE_DATA_PATH = "data/sample_scrap_data.xlsx"
