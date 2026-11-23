"""
대학원 학사 규정 Q&A 및 상담 메모 앱 (Vercel & 로컬 겸용 FastAPI 서버)

- Vercel 배포 시: 이 파일(app.py)의 최상위 `app` 변수를 자동으로 인식해 실행됩니다.
- 내 컴퓨터 실행 시:
      .venv\\Scripts\\uvicorn.exe app:app --reload
  실행 후 브라우저에서 http://127.0.0.1:8000 접속
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from consultations import append_consultation, load_consultations, rows_to_excel_csv_bytes
from gemini_helper import ask_regulation_qa, get_api_key_status
from regulations import (
    GRAD_SCHOOL_OPTIONS,
    build_context_for_school,
    extract_matching_original_clauses,
    load_regulation_sections,
)

# 경로 설정 (항상 작업 폴더 grad-rule-helper 내부만 사용)
BASE_DIR = Path(__file__).resolve().parent
REGULATIONS_DIR = BASE_DIR / "data" / "regulations"
REGULATIONS_CACHE_PATH = BASE_DIR / "data" / "regulations_cache.json"
SAMPLE_CSV_PATH = BASE_DIR / "data" / "sample_consultations.csv"
WORKING_CSV_PATH = BASE_DIR / "data" / "consultations.csv"
STATIC_INDEX_PATH = BASE_DIR / "static" / "index.html"

QUICK_QUESTIONS: List[str] = [
    "논문 대신 학점 대체 가능 여부",
    "휴학 가능 기간 및 신청 절차",
    "수료 기준 학점과 연구등록 안내",
    "전과 또는 전공 변경 가능 여부",
    "장학금 지급 기준 및 성적 요건",
    "외국어시험·종합시험 응시 및 면제 조건",
]

ADMISSION_YEAR_OPTIONS: List[str] = [
    "미지정 (전체 기준)",
    "2026학년도",
    "2025학년도",
    "2024학년도",
    "2023학년도",
    "2022학년도",
    "2021학년도",
    "2020학년도",
    "직접 입력",
]

# Vercel이 자동으로 인식하는 최상위 FastAPI 앱 변수
app = FastAPI(title="대학원 학사 규정 Q&A 및 상담 메모 앱")

# 메모리 캐시 (규정 문서를 한 번만 불러와 빠르게 재사용)
_REGULATION_CACHE = None


def _get_regulations():
    global _REGULATION_CACHE
    if _REGULATION_CACHE is None:
        _REGULATION_CACHE = load_regulation_sections(REGULATIONS_DIR, REGULATIONS_CACHE_PATH)
    return _REGULATION_CACHE


class SearchRequest(BaseModel):
    school: str = "일반대학원"
    admission_year: str = "미지정 (전체 기준)"
    question: str = ""


class RawVerifyRequest(BaseModel):
    school: str = "일반대학원"
    articles: List[str] = []
    keyword: str = ""


class ConsultationRequest(BaseModel):
    대학원구분: str = ""
    입학년도: str = ""
    가상학번: str = ""
    상담자이름: str = ""
    학과: str = ""
    질문내용: str = ""
    답변요약: str = ""
    근거조항: str = ""
    특이사항: str = ""


class ExportCsvRequest(BaseModel):
    rows: List[Dict[str, str]] = []


@app.get("/")
def serve_home():
    """메인 웹 화면을 보여줍니다."""
    return FileResponse(STATIC_INDEX_PATH)


@app.get("/api/meta")
def get_meta():
    """화면 초기 구성에 필요한 대학원 목록, 퀵 질문, 연결 상태(키 값 비공개)를 반환합니다."""
    sections, loaded_files = _get_regulations()
    return {
        "api_key_ready": get_api_key_status(),
        "schools": GRAD_SCHOOL_OPTIONS,
        "admission_years": ADMISSION_YEAR_OPTIONS,
        "quick_questions": QUICK_QUESTIONS,
        "loaded_files": loaded_files,
        "section_count": len(sections),
    }


@app.post("/api/search")
def search_regulation(req: SearchRequest):
    """선택한 대학원·입학년도·질문에 맞춰 3단 답변과 원문 대조 단락을 반환합니다."""
    question = req.question.strip()
    if not question:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error_message": "질문이나 키워드를 먼저 입력해 주세요."},
        )

    sections, _ = _get_regulations()
    context_text, target_sections = build_context_for_school(
        sections=sections,
        selected_school=req.school,
        question=question,
    )

    result = ask_regulation_qa(
        question=question,
        selected_school=req.school,
        admission_year=req.admission_year,
        regulation_context=context_text,
    )

    if not result.ok:
        return {"ok": False, "error_message": result.error_message}

    article_hints = [c.article for c in result.citations]
    raw_matches = extract_matching_original_clauses(
        target_sections=target_sections,
        article_numbers=article_hints,
        keyword="",
        max_items=8,
    )

    return {
        "ok": True,
        "school": req.school,
        "admission_year": req.admission_year,
        "question": question,
        "one_line_conclusion": result.one_line_conclusion,
        "details": result.details,
        "required_documents": result.required_documents,
        "addendum_caution": result.addendum_caution,
        "comparison_note": result.comparison_note,
        "citations": [asdict(c) for c in result.citations],
        "memo_summary": result.memo_summary or result.one_line_conclusion,
        "raw_matches": raw_matches,
    }


@app.post("/api/verify-raw")
def verify_raw_clauses(req: RawVerifyRequest):
    """[근거 조항 원문 펼쳐보기] 안에서 사용자가 입력한 단어로 실제 PDF 원문을 직접 검색합니다."""
    sections, _ = _get_regulations()
    _, target_sections = build_context_for_school(sections, req.school, req.keyword)
    matches = extract_matching_original_clauses(
        target_sections=target_sections,
        article_numbers=req.articles,
        keyword=req.keyword,
        max_items=8,
    )
    return {"matches": matches}


@app.get("/api/consultations")
def get_consultations():
    """초기(샘플 또는 로컬 저장) 상담 이력 목록을 반환합니다."""
    rows = load_consultations(SAMPLE_CSV_PATH, WORKING_CSV_PATH)
    return {"rows": rows}


@app.post("/api/consultations")
def save_consultation(req: ConsultationRequest):
    """새 상담 메모를 저장하고(로컬 CSV 반영), 생성된 항목을 반환합니다."""
    new_row = append_consultation(
        sample_path=SAMPLE_CSV_PATH,
        working_path=WORKING_CSV_PATH,
        record=req.model_dump(),
    )
    return {"ok": True, "row": new_row}


@app.post("/api/export-csv")
def export_csv(req: ExportCsvRequest):
    """전달받은 상담 목록을 엑셀용 UTF-8 BOM CSV 파일로 내려받습니다."""
    csv_bytes = rows_to_excel_csv_bytes(req.rows)
    today = datetime.now().strftime("%Y%m%d")
    filename = f"grad_consultations_{today}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
