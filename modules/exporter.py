"""분석 결과 엑셀 내보내기 (PRD F6)."""

import io

import pandas as pd

import config as C
from modules import metrics as M
from modules import risk as R

# 반올림 자릿수: 금액·단가는 정수, 나머지 숫자는 소수 1자리
_ROUND_0 = {M.M_AMOUNT, M.M_PRICE, M.M_CONTRACT}


def readable(df: pd.DataFrame) -> pd.DataFrame:
    """엑셀용 정리: R1~R5 → 'R1 목표 미달' 컬럼에 '해당'/빈칸, 숫자 반올림."""
    out = df.copy()
    for r in R.RULE_IDS:
        if r in out.columns:
            out[r] = out[r].map(lambda v: "해당" if bool(v) else "")
            out = out.rename(columns={r: f"{r} {C.RISK_REASONS[r]}"})
    for col in out.select_dtypes("number").columns:
        out[col] = out[col].round(0 if col in _ROUND_0 else 1)
    return out


def export_filename(ref_month: pd.Timestamp) -> str:
    """스크랩_협력사_리스크분석_YYYYMM.xlsx"""
    return f"스크랩_협력사_리스크분석_{pd.Timestamp(ref_month):%Y%m}.xlsx"


def _write(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            for i, col in enumerate(df.columns, start=1):  # 대략적인 열 너비
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) * 1.3 + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(width, 50)
            ws.freeze_panes = "A2"
    return buf.getvalue()


def build_report(summary: pd.DataFrame, classified: pd.DataFrame, thresholds: dict) -> bytes:
    """시트: 요약, 전체 협력사, 리스크 업체, 적용 기준."""
    risky = classified[classified[R.RISK_LEVEL] != C.RISK_NORMAL]
    return _write({
        "요약": summary,
        "전체 협력사": readable(classified),
        "리스크 업체": readable(risky),
        "적용 기준": R.rule_descriptions(thresholds),
    })


def build_table(df: pd.DataFrame, sheet_name: str) -> bytes:
    """단일 표 엑셀 (리스크 업체만 다운로드 등)."""
    return _write({sheet_name: readable(df)})


def build_template() -> bytes:
    """입력 양식 템플릿 (컬럼 헤더 + 샘플 5행)."""
    rows = [
        ("2026-08", "V001", "대한스크랩", "경기", "A", "생철", 12000, 1000, 950.0, 520000),
        ("2026-08", "V001", "대한스크랩", "경기", "A", "중량", 6000, 500, 480.5, 480000),
        ("2026-08", "V002", "한국철강자원", "충남", "B", "경량", 9600, 800, 612.0, 430000),
        ("2026-08", "V003", "동해금속", "경북", "C", "선반", 4800, 400, 0.0, 400000),
        ("2026-07", "V001", "대한스크랩", "경기", "A", "생철", 12000, 1000, 1010.0, 518000),
    ]
    sample = pd.DataFrame(rows, columns=C.REQUIRED_COLUMNS)
    guide = pd.DataFrame({
        "컬럼": C.REQUIRED_COLUMNS,
        "설명": [
            "실적 귀속 월 (YYYY-MM)", "협력사 고유 코드", "협력사 이름", "소재 지역", "협력사 등급 (A/B/C)",
            "철스크랩 품목", "연간 계약 물량(톤)", "해당 월 입고 목표량(톤)", "해당 월 실제 입고량(톤)", "적용 단가(원/톤)",
        ],
    })
    return _write({"입고실적": sample, "작성 안내": guide})
