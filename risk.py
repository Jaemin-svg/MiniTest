"""리스크 규칙 판정 및 등급 산정 (PRD F4)."""

import pandas as pd

import config as C
from modules import metrics as M

RISK_LEVEL = "리스크 등급"
RISK_REASON = "리스크 사유"
RULE_COUNT = "해당 규칙 수"
RULE_IDS = list(C.RISK_REASONS)  # R1..R5

_LEVEL_ORDER = {lvl: i for i, lvl in enumerate(C.RISK_LEVELS)}
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2}


def evaluate_rules(metrics: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """R1~R5 해당 여부를 불리언 컬럼으로 추가. 값이 NaN이면 해당 규칙은 미해당."""
    t = {**C.DEFAULT_THRESHOLDS, **thresholds}
    out = metrics.copy()
    out["R1"] = (out[M.M_ACH] < t["achievement_min"]).fillna(False)
    out["R2"] = (out[M.M_CHG] <= t["change_max"]).fillna(False)
    out["R3"] = (out[M.M_CONSEC] >= t["consecutive_min"]).fillna(False)
    out["R4"] = (out[M.M_FULFILL] < out[M.M_ELAPSED] - t["contract_gap_pp"]).fillna(False)
    out["R5"] = (out[M.M_ACTUAL] == 0).fillna(False)
    for r in RULE_IDS:
        out[r] = out[r].astype(bool)
    return out


def classify(metrics: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    """규칙 판정 → 리스크 등급·사유 추가 → PRD 정렬 순서로 반환.

    등급: 고위험 = R5 또는 달성률 < high_risk_achievement 또는 규칙 high_risk_rule_count개 이상
          주의 = 규칙 1개 이상, 정상 = 해당 없음
    정렬: 고위험 → 주의 → 정상, 같은 등급 내 A등급 우선, 그다음 달성률 낮은 순(N/A는 뒤).
    """
    t = {**C.DEFAULT_THRESHOLDS, **thresholds}
    out = evaluate_rules(metrics, t)
    out[RULE_COUNT] = out[RULE_IDS].sum(axis=1).astype(int)

    high = (
        out["R5"]
        | (out[M.M_ACH] < t["high_risk_achievement"]).fillna(False)
        | (out[RULE_COUNT] >= t["high_risk_rule_count"])
    )
    out[RISK_LEVEL] = C.RISK_NORMAL
    out.loc[out[RULE_COUNT] > 0, RISK_LEVEL] = C.RISK_CAUTION
    out.loc[high, RISK_LEVEL] = C.RISK_HIGH

    out[RISK_REASON] = out[RULE_IDS].apply(
        lambda row: ", ".join(C.RISK_REASONS[r] for r in RULE_IDS if row[r]), axis=1
    ) if not out.empty else pd.Series(dtype=str)

    out["_lvl"] = out[RISK_LEVEL].map(_LEVEL_ORDER)
    out["_grd"] = out[C.COL_GRADE].map(_GRADE_ORDER).fillna(len(_GRADE_ORDER))
    out = out.sort_values(["_lvl", "_grd", M.M_ACH], na_position="last", kind="stable")
    return out.drop(columns=["_lvl", "_grd"]).reset_index(drop=True)


def rule_descriptions(thresholds: dict) -> pd.DataFrame:
    """적용 기준 설명표 (화면/엑셀 공용)."""
    t = {**C.DEFAULT_THRESHOLDS, **thresholds}
    rows = [
        ("R1", C.RISK_REASONS["R1"], f"목표 달성률 < {t['achievement_min']:g}%"),
        ("R2", C.RISK_REASONS["R2"], f"과거평균 대비 증감률 ≤ {t['change_max']:g}%"),
        ("R3", C.RISK_REASONS["R3"], f"연속 미달 ≥ {t['consecutive_min']:g}개월 (미달 기준 {t['achievement_min']:g}%)"),
        ("R4", C.RISK_REASONS["R4"], f"계약 이행률 < 기간 경과율 - {t['contract_gap_pp']:g}%p"),
        ("R5", C.RISK_REASONS["R5"], "당월 입고량 = 0"),
        ("등급", C.RISK_HIGH,
         f"R5 해당 또는 달성률 < {t['high_risk_achievement']:g}% 또는 규칙 {t['high_risk_rule_count']:g}개 이상"),
        ("등급", C.RISK_CAUTION, "규칙 1개 이상 해당"),
        ("등급", C.RISK_NORMAL, "해당 규칙 없음"),
    ]
    return pd.DataFrame(rows, columns=["구분", "명칭", "조건"])
