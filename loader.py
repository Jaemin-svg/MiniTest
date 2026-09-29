"""파일 로드, 컬럼명 정규화, 필수 컬럼 검사, 기준월 변환.

Streamlit에 의존하지 않는다. 캐싱은 app.py에서 감싼다.
"""

import io
from dataclasses import dataclass, field

import pandas as pd

import config as C


@dataclass
class LoadResult:
    df: pd.DataFrame
    missing_columns: list[str] = field(default_factory=list)
    renamed_columns: dict[str, str] = field(default_factory=dict)  # 원래 이름 → 표준 이름
    invalid_month_rows: list[int] = field(default_factory=list)  # 엑셀 기준 행 번호

    @property
    def ok(self) -> bool:
        return not self.missing_columns


def _is_csv(filename: str) -> bool:
    return filename.lower().endswith(".csv")


def list_sheets(file_bytes: bytes, filename: str) -> list[str]:
    """엑셀 파일의 시트 이름 목록. CSV는 빈 리스트."""
    if _is_csv(filename):
        return []
    return pd.ExcelFile(io.BytesIO(file_bytes)).sheet_names


def detect_data_sheet(file_bytes: bytes, filename: str, sheets: list[str]) -> int:
    """필수 컬럼이 모두 있는 첫 시트의 인덱스. 없으면 0."""
    for i, name in enumerate(sheets):
        try:
            header = pd.read_excel(io.BytesIO(file_bytes), sheet_name=name, nrows=0)
        except Exception:
            continue
        if not find_missing_columns(normalize_columns(header)[0]):
            return i
    return 0


def read_raw(file_bytes: bytes, filename: str, sheet: str | None = None) -> pd.DataFrame:
    """xlsx/xls/csv를 DataFrame으로 읽는다. CSV는 UTF-8(BOM 포함) → CP949 순으로 시도."""
    buf = io.BytesIO(file_bytes)
    if _is_csv(filename):
        for enc in ("utf-8-sig", "cp949"):
            try:
                buf.seek(0)
                return pd.read_csv(buf, encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError("CSV 인코딩을 인식할 수 없습니다. UTF-8 또는 CP949로 저장해 주세요.")
    return pd.read_excel(buf, sheet_name=sheet or 0)


def normalize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """컬럼명 표기 차이(공백·괄호·단위)를 표준 컬럼명으로 맞춘다."""
    rename = {}
    taken = set()
    for col in df.columns:
        std = C.COLUMN_ALIASES.get(C.normalize_column_key(col))
        if std and std not in taken:
            taken.add(std)
            if col != std:
                rename[col] = std
    return df.rename(columns=rename), rename


def find_missing_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in C.REQUIRED_COLUMNS if c not in df.columns]


def parse_month(series: pd.Series) -> pd.Series:
    """기준월을 월초 Timestamp로 변환. 변환 불가 값은 NaT.

    허용: datetime, '2026-08', '2026.08', '2026/08', '202608', '2026-08-15'
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.to_period("M").dt.to_timestamp()

    def _one(v):
        if pd.isna(v):
            return pd.NaT
        if isinstance(v, pd.Timestamp):
            return v.to_period("M").to_timestamp()
        text = str(v).strip()
        if text.endswith(".0"):  # 202608.0 처럼 숫자로 읽힌 경우
            text = text[:-2]
        text = text.replace(".", "-").replace("/", "-")
        if text.isdigit() and len(text) == 6:
            text = f"{text[:4]}-{text[4:]}"
        ts = pd.to_datetime(text[:7], format="%Y-%m", errors="coerce")
        return ts

    return pd.to_datetime(series.map(_one))


def load_data(file_bytes: bytes, filename: str, sheet: str | None = None) -> LoadResult:
    """읽기 → 컬럼 정규화 → 필수 컬럼 검사 → 기준월 변환."""
    raw = read_raw(file_bytes, filename, sheet)
    raw = raw.dropna(how="all")
    df, renamed = normalize_columns(raw)

    missing = find_missing_columns(df)
    if missing:
        return LoadResult(df=df, missing_columns=missing, renamed_columns=renamed)

    df = df[C.REQUIRED_COLUMNS].copy()
    df[C.COL_MONTH] = parse_month(df[C.COL_MONTH])
    invalid = [int(i) + 2 for i in df.index[df[C.COL_MONTH].isna()]]  # 헤더 1행 + 0-based 보정
    for col in (C.COL_CODE, C.COL_NAME, C.COL_REGION, C.COL_GRADE, C.COL_ITEM):
        df[col] = df[col].astype("string").str.strip()

    return LoadResult(df=df, renamed_columns=renamed, invalid_month_rows=invalid)
