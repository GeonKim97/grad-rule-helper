"""
상담 메모를 CSV 파일로 저장하고 불러오며,
엑셀(Excel)에서 한글이 깨지지 않게 내려받도록 도와주는 모듈입니다.
비유하자면, 상담 일지를 차곡차곡 철해 두고 필요할 때
엑셀 파일로 복사해 주는 '상담 대장 관리함' 역할을 합니다.
"""

from __future__ import annotations

import csv
import io
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

COLUMNS: List[str] = [
    "상담일시",
    "대학원구분",
    "입학년도",
    "가상학번",
    "상담자이름",
    "학과",
    "질문내용",
    "답변요약",
    "근거조항",
    "특이사항",
]


def ensure_working_csv(sample_path: Path, working_path: Path) -> None:
    """
    작업용 상담 파일(data/consultations.csv)이 아직 없으면
    가상 테스트 데이터(data/sample_consultations.csv)를 복사해 초기 대장을 만듭니다.
    """
    working_path.parent.mkdir(parents=True, exist_ok=True)
    if not working_path.exists():
        if sample_path.exists():
            shutil.copyfile(sample_path, working_path)
        else:
            with working_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(COLUMNS)


def load_consultations(sample_path: Path, working_path: Path) -> pd.DataFrame:
    """저장된 상담 이력을 표(DataFrame) 형태로 읽어옵니다."""
    ensure_working_csv(sample_path, working_path)
    try:
        df = pd.read_csv(working_path, encoding="utf-8-sig", dtype=str).fillna("")
    except Exception:
        df = pd.DataFrame(columns=COLUMNS)

    # 누락된 열이 있으면 빈 값으로 보완
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]


def append_consultation(
    sample_path: Path,
    working_path: Path,
    record: Dict[str, str],
) -> pd.DataFrame:
    """새 상담 내역 1건을 파일에 추가하고 최신 목록을 반환합니다."""
    df = load_consultations(sample_path, working_path)
    new_row = {
        "상담일시": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "대학원구분": record.get("대학원구분", "").strip(),
        "입학년도": record.get("입학년도", "").strip(),
        "가상학번": record.get("가상학번", "").strip(),
        "상담자이름": record.get("상담자이름", "").strip(),
        "학과": record.get("학과", "").strip(),
        "질문내용": record.get("질문내용", "").strip(),
        "답변요약": record.get("답변요약", "").strip(),
        "근거조항": record.get("근거조항", "").strip(),
        "특이사항": record.get("특이사항", "").strip(),
    }
    updated = pd.concat([pd.DataFrame([new_row]), df], ignore_index=True)
    updated.to_csv(working_path, index=False, encoding="utf-8-sig")
    return updated


def dataframe_to_excel_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    윈도우 엑셀에서 더블클릭해도 한글이 깨지지 않도록
    UTF-8 BOM(utf-8-sig) 형식으로 CSV 바이트를 만들어 반환합니다.
    """
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8-sig")
