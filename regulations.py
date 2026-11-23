"""
규정 문서(PDF, TXT, MD)를 읽고 대학원별로 깔끔하게 정리해 주는 모듈입니다.
비유하자면, 책장에 꽂힌 두꺼운 학칙·시행세칙 규정집에서
필요한 대학원 쪽만 빠르게 찾아 펼쳐 주는 '사서 선생님' 역할을 합니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from pypdf import PdfReader

# 수원대학교 학칙 제2조 기준 대학원 목록 (일반대학원 + 12개 특수대학원)
SPECIAL_GRAD_SCHOOLS: List[str] = [
    "경영대학원",
    "고용서비스대학원",
    "공공정책대학원",
    "공학대학원",
    "교육대학원",
    "글로벌창업대학원",
    "문화예술대학원",
    "미술대학원",
    "사회복지대학원",
    "스포츠과학대학원",
    "음악대학원",
    "호텔관광대학원",
]

GRAD_SCHOOL_OPTIONS: List[str] = [
    "전체 비교",
    "일반대학원",
    *SPECIAL_GRAD_SCHOOLS,
]

COMMON_SECTION_KEYS: List[str] = [
    "대학원 학칙",
    "장학금 지급규정",
    "학·석사 연계과정 운영 규정",
    "석·박사 통합과정 운영 규정",
    "기타 공통 규정",
]


@dataclass
class RegulationSection:
    """대학원별 또는 공통 규정 한 묶음의 정보"""

    key: str  # 예: "일반대학원", "공학대학원", "대학원 학칙"
    title: str  # 표시용 문서명
    source_file: str  # 원본 파일명
    pages: List[Tuple[int, str]]  # (PDF 쪽번호 또는 1, 본문 텍스트) 리스트

    @property
    def full_text(self) -> str:
        chunks = []
        for page_no, text in self.pages:
            chunks.append(f"[출처: {self.source_file} / {self.title} / p.{page_no}]\n{text}")
        return "\n\n".join(chunks)


def _normalize_for_heading(line: str) -> str:
    """공백과 특수기호를 줄여 제목 패턴을 안정적으로 비교합니다."""
    return re.sub(r"[\s·ㆍ・]+", "", line)


def _detect_section_start(page_text: str) -> Tuple[str, str] | None:
    """
    시행세칙 합본 PDF의 각 페이지 상단을 보고,
    새로운 대학원 시행세칙이나 부속 규정이 시작되는 쪽인지 판별합니다.
    """
    raw_lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    if not raw_lines:
        return None

    # 목차 페이지는 건너뜀
    top_preview = " ".join(raw_lines[:6])
    if "목" in top_preview and "차" in top_preview and ("··" in page_text or ".." in page_text):
        return None

    # 쪽번호('- 17 -' 등)를 제외한 맨 첫 2줄에서만 규정 제목을 확인합니다.
    candidate_lines = [
        line for line in raw_lines if not re.fullmatch(r"[-–—\s\d]+", line)
    ][:2]

    for line in candidate_lines:
        # 본문 문장(조항·항·마침표로 끝나는 문장)은 제목이 아니므로 제외
        if line.startswith(("제", "①", "②", "③", "④", "⑤")) or line.endswith("다."):
            continue
        compact = _normalize_for_heading(line)

        # 1) 특수대학원 학칙시행세칙 확인
        for school in SPECIAL_GRAD_SCHOOLS:
            if compact in (f"{school}학칙시행세칙", f"{school}시행세칙"):
                return school, f"{school} 학칙시행세칙"

        # 2) 일반대학원 학칙시행세칙 (문서 표기가 "대학원 학칙시행세칙" 또는 "일반대학원 학칙시행세칙")
        if compact in ("대학원학칙시행세칙", "일반대학원학칙시행세칙"):
            return "일반대학원", "일반대학원 학칙시행세칙"

        # 3) 부속 공통 규정 확인
        if compact in ("장학금지급규정", "대학원장학금지급규정"):
            return "장학금 지급규정", "장학금 지급규정"
        if compact in ("학석사연계과정운영규정", "대학원학석사연계과정운영규정"):
            return "학·석사 연계과정 운영 규정", "학·석사 연계과정 운영 규정"
        if compact in ("석박사통합과정운영규정", "대학원석박사통합과정운영규정"):
            return "석·박사 통합과정 운영 규정", "석·박사 통합과정 운영 규정"

    return None


def _guess_key_from_filename(filename: str) -> Tuple[str, str]:
    """개별 파일 이름에서 어느 대학원/공통 규정인지 추정합니다."""
    stem = Path(filename).stem
    for school in SPECIAL_GRAD_SCHOOLS:
        if school in stem:
            return school, stem
    if "일반대학원" in stem:
        return "일반대학원", stem
    if "장학금" in stem:
        return "장학금 지급규정", stem
    if "연계과정" in stem:
        return "학·석사 연계과정 운영 규정", stem
    if "통합과정" in stem:
        return "석·박사 통합과정 운영 규정", stem
    if "학칙" in stem and "시행세칙" not in stem:
        return "대학원 학칙", stem
    return "기타 공통 규정", stem


def load_regulation_sections(regulations_dir: Path) -> Tuple[Dict[str, RegulationSection], List[str]]:
    """
    data/regulations/ 폴더 안의 모든 PDF, TXT, MD 규정 파일을 읽어
    대학원별·공통 규정 섹션 딕셔너리로 반환합니다.
    반환값: (섹션 딕셔너리, 읽어 들인 파일명 목록)
    """
    sections: Dict[str, RegulationSection] = {}
    loaded_files: List[str] = []

    if not regulations_dir.exists():
        return sections, loaded_files

    def add_page(key: str, title: str, source_file: str, page_no: int, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        if key not in sections:
            sections[key] = RegulationSection(
                key=key,
                title=title,
                source_file=source_file,
                pages=[],
            )
        sections[key].pages.append((page_no, cleaned))

    target_files = sorted(
        p
        for p in regulations_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".pdf", ".txt", ".md"} and not p.name.startswith(".")
    )

    for file_path in target_files:
        suffix = file_path.suffix.lower()
        loaded_files.append(file_path.name)

        if suffix == ".pdf":
            try:
                reader = PdfReader(str(file_path))
            except Exception:
                continue

            # 시행세칙 합본 여부 확인: 내부에서 2개 이상의 섹션 제목이 감지되면 자동 분할
            detected_starts: Dict[int, Tuple[str, str]] = {}
            page_texts: List[str] = []
            for idx, page in enumerate(reader.pages):
                txt = (page.extract_text() or "").strip()
                page_texts.append(txt)
                found = _detect_section_start(txt)
                if found:
                    detected_starts[idx] = found

            if len(detected_starts) >= 2:
                current_key: str | None = None
                current_title: str = file_path.stem
                for idx, txt in enumerate(page_texts):
                    if idx in detected_starts:
                        current_key, current_title = detected_starts[idx]
                    if current_key is not None:
                        add_page(current_key, current_title, file_path.name, idx + 1, txt)
            else:
                key, title = _guess_key_from_filename(file_path.name)
                for idx, txt in enumerate(page_texts):
                    add_page(key, title, file_path.name, idx + 1, txt)
        else:
            try:
                txt = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                txt = file_path.read_text(encoding="cp949", errors="ignore")
            key, title = _guess_key_from_filename(file_path.name)
            add_page(key, title, file_path.name, 1, txt)

    return sections, loaded_files


def build_context_for_school(
    sections: Dict[str, RegulationSection],
    selected_school: str,
) -> Tuple[str, List[RegulationSection]]:
    """
    선택한 대학원에 맞춰 AI에게 전달할 규정 본문을 구성합니다.
    - 특정 대학원을 고르면: [대학원 학칙] + [해당 대학원 시행세칙 전체] + [공통 부속 규정]
    - '전체 비교'를 고르면: [대학원 학칙] + [일반대학원 및 모든 특수대학원 시행세칙] + [공통 부속 규정]
    """
    chosen: List[RegulationSection] = []

    if "대학원 학칙" in sections:
        chosen.append(sections["대학원 학칙"])

    if selected_school == "전체 비교":
        for school in ["일반대학원", *SPECIAL_GRAD_SCHOOLS]:
            if school in sections:
                chosen.append(sections[school])
    else:
        if selected_school in sections:
            chosen.append(sections[selected_school])

    for common_key in [
        "장학금 지급규정",
        "학·석사 연계과정 운영 규정",
        "석·박사 통합과정 운영 규정",
        "기타 공통 규정",
    ]:
        if common_key in sections:
            chosen.append(sections[common_key])

    parts = []
    for sec in chosen:
        parts.append(f"====================\n[규정 구분: {sec.title}]\n====================\n{sec.full_text}")

    return "\n\n".join(parts), chosen


def extract_matching_original_clauses(
    target_sections: List[RegulationSection],
    article_numbers: List[str],
    keyword: str = "",
    max_items: int = 8,
) -> List[Dict[str, str]]:
    """
    [근거 조항 원문 펼쳐보기]에서 실제 PDF 원문을 그대로 대조할 수 있도록
    언급된 조항 번호(예: 제24조, 부칙)나 검색어가 포함된 실제 원문 단락을 찾아 반환합니다.
    """
    results: List[Dict[str, str]] = []
    seen = set()

    # 조항 번호 패턴 정규화 (예: "제24조", "제 24 조", "부칙")
    patterns: List[str] = []
    for item in article_numbers:
        for m in re.findall(r"제\s*\d+\s*조(?:의\s*\d+)?|부\s*칙", item):
            compact = re.sub(r"\s+", "", m)
            if compact not in patterns:
                patterns.append(compact)

    kw = keyword.strip()

    for sec in target_sections:
        for page_no, page_text in sec.pages:
            # 조항 단위로 보기 좋게 분리
            blocks = re.split(r"(?=(?:^|\n)\s*(?:제\s*\d+\s*조(?:의\s*\d+)?|부\s*칙))", page_text)
            for block in blocks:
                cleaned = block.strip()
                if len(cleaned) < 10:
                    continue
                compact_block = re.sub(r"\s+", "", cleaned)

                matched_label = None
                if kw:
                    if kw in cleaned:
                        matched_label = f"검색어 '{kw}'"
                elif patterns:
                    for pat in patterns:
                        if pat in compact_block:
                            matched_label = pat
                            break

                if matched_label:
                    uid = (sec.title, page_no, cleaned[:60])
                    if uid in seen:
                        continue
                    seen.add(uid)
                    results.append(
                        {
                            "section": sec.title,
                            "source_file": sec.source_file,
                            "page": str(page_no),
                            "match": matched_label,
                            "text": cleaned,
                        }
                    )
                    if len(results) >= max_items:
                        return results

    return results
