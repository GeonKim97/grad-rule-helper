"""
상담 메모를 CSV 파일로 읽고 저장하며,
엑셀(Excel)에서 한글이 깨지지 않게 내려받도록 도와주는 모듈입니다.
(무거운 외부 라이브러리 없이 파이썬 기본 csv 도구만 사용해 Vercel 배포에도 가볍습니다.)
"""

from __future__ import annotations

import csv
import io
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

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


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {col: (raw.get(col) or "").strip() for col in COLUMNS}
            rows.append(row)
    return rows


def load_consultations(sample_path: Path, working_path: Path) -> List[Dict[str, str]]:
    """
    상담 이력을 불러옵니다.
    로컬에서는 data/consultations.csv를 우선 사용하고,
    읽기 전용 웹 서버(Vercel)에서는 sample_consultations.csv를 안전하게 읽어옵니다.
    """
    if working_path.exists():
        return _read_csv_rows(working_path)
    if sample_path.exists():
        try:
            working_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sample_path, working_path)
            return _read_csv_rows(working_path)
        except OSError:
            return _read_csv_rows(sample_path)
    return []


def append_consultation(
    sample_path: Path,
    working_path: Path,
    record: Dict[str, str],
) -> Dict[str, str]:
    """
    새 상담 내역 1건을 만듭니다.
    로컬 PC에서는 data/consultations.csv에도 함께 저장하고,
    읽기 전용 서버(Vercel)에서는 오류 없이 브라우저 저장소와 연동되도록 새 항목을 반환합니다.
    """
    new_row = {
        "상담일시": record.get("상담일시") or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "대학원구분": (record.get("대학원구분") or "").strip(),
        "입학년도": (record.get("입학년도") or "").strip(),
        "가상학번": (record.get("가상학번") or "").strip(),
        "상담자이름": (record.get("상담자이름") or "").strip(),
        "학과": (record.get("학과") or "").strip(),
        "질문내용": (record.get("질문내용") or "").strip(),
        "답변요약": (record.get("답변요약") or "").strip(),
        "근거조항": (record.get("근거조항") or "").strip(),
        "특이사항": (record.get("특이사항") or "").strip(),
    }

    try:
        existing = load_consultations(sample_path, working_path)
        updated = [new_row, *existing]
        working_path.parent.mkdir(parents=True, exist_ok=True)
        with working_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(updated)
    except OSError:
        # Vercel 서버리스 환경은 파일 쓰기가 제한되므로 정상 통과 (브라우저에 안전 저장)
        pass

    return new_row


def rows_to_excel_csv_bytes(rows: List[Dict[str, str]]) -> bytes:
    """윈도우 엑셀에서 한글이 깨지지 않도록 UTF-8 BOM(utf-8-sig) CSV를 만듭니다."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({col: (row.get(col) or "") for col in COLUMNS})
    return buffer.getvalue().encode("utf-8-sig")
