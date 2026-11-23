"""
규정 문서(PDF, TXT, MD)를 읽고 대학원별로 깔끔하게 정리해 주는 모듈입니다.
비유하자면, 책장에 꽂힌 두꺼운 학칙·시행세칙 규정집에서
필요한 대학원 쪽만 빠르게 찾아 펼쳐 주는 '사서 선생님' 역할을 합니다.

※ 웹 배포(Vercel)에서도 0.01초 만에 규정을 불러올 수 있도록
   미리 정리된 빠른 색인 파일(data/regulations_cache.json)을 함께 지원합니다.
"""

from __future__ import annotations

import json
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

# '전체 비교' 질문 시 빠른 핵심 발췌를 돕는 일상어 -> 규정어 보조 키워드
SYNONYM_GROUPS: List[List[str]] = [
    ["논문", "학점", "대체", "비논문", "졸업", "학위수여", "청구논문", "추가학점", "이수학점"],
    ["휴학", "복학", "제적", "자퇴", "재입학", "등록", "수업연한"],
    ["수료", "연구등록", "이수학점", "졸업학점", "평점", "성적"],
    ["전과", "전공", "변경", "과정전환", "편입"],
    ["장학", "장학금", "성적", "감면", "지급"],
    ["외국어", "종합시험", "면제", "자격시험", "영어", "어학"],
    ["연계", "통합", "석박사", "학석사"],
]


@dataclass
class RegulationSection:
    """대학원별 또는 공통 규정 한 묶음의 정보"""

    key: str
    title: str
    source_file: str
    pages: List[Tuple[int, str]]

    @property
    def full_text(self) -> str:
        chunks = []
        for page_no, text in self.pages:
            chunks.append(f"[출처: {self.source_file} / {self.title} / p.{page_no}]\n{text}")
        return "\n\n".join(chunks)


def _normalize_for_heading(line: str) -> str:
    return re.sub(r"[\s·ㆍ・]+", "", line)


def _detect_section_start(page_text: str) -> Tuple[str, str] | None:
    raw_lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    if not raw_lines:
        return None

    top_preview = " ".join(raw_lines[:6])
    if "목" in top_preview and "차" in top_preview and ("··" in page_text or ".." in page_text):
        return None

    candidate_lines = [
        line for line in raw_lines if not re.fullmatch(r"[-–—\s\d]+", line)
    ][:2]

    for line in candidate_lines:
        if line.startswith(("제", "①", "②", "③", "④", "⑤")) or line.endswith("다."):
            continue
        compact = _normalize_for_heading(line)

        for school in SPECIAL_GRAD_SCHOOLS:
            if compact in (f"{school}학칙시행세칙", f"{school}시행세칙"):
                return school, f"{school} 학칙시행세칙"

        if compact in ("대학원학칙시행세칙", "일반대학원학칙시행세칙"):
            return "일반대학원", "일반대학원 학칙시행세칙"

        if compact in ("장학금지급규정", "대학원장학금지급규정"):
            return "장학금 지급규정", "장학금 지급규정"
        if compact in ("학석사연계과정운영규정", "대학원학석사연계과정운영규정"):
            return "학·석사 연계과정 운영 규정", "학·석사 연계과정 운영 규정"
        if compact in ("석박사통합과정운영규정", "대학원석박사통합과정운영규정"):
            return "석·박사 통합과정 운영 규정", "석·박사 통합과정 운영 규정"

    return None


def _guess_key_from_filename(filename: str) -> Tuple[str, str]:
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


def parse_regulations_from_files(regulations_dir: Path) -> Tuple[Dict[str, RegulationSection], List[str]]:
    """PDF/TXT/MD 원본 파일들을 직접 읽어 대학원별 섹션으로 나눕니다."""
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


def save_regulations_cache(
    cache_path: Path,
    sections: Dict[str, RegulationSection],
    loaded_files: List[str],
) -> None:
    """파싱 결과를 빠른 JSON 색인 파일로 저장합니다."""
    payload = {
        "loaded_files": loaded_files,
        "sections": [
            {
                "key": sec.key,
                "title": sec.title,
                "source_file": sec.source_file,
                "pages": [[pno, txt] for pno, txt in sec.pages],
            }
            for sec in sections.values()
        ],
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_regulation_sections(
    regulations_dir: Path,
    cache_path: Path | None = None,
) -> Tuple[Dict[str, RegulationSection], List[str]]:
    """
    빠른 색인 파일(regulations_cache.json)이 최신 상태이면 즉시 읽고,
    없거나 새 규정 파일이 추가되었으면 원본 PDF/TXT를 다시 읽어옵니다.
    """
    if cache_path is not None and cache_path.exists():
        # 원본 파일 목록이 캐시와 같으면 초고속 로드 (Vercel 콜드스타트 0.01초)
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_files = cached.get("loaded_files", [])
            current_files = (
                sorted(
                    p.name
                    for p in regulations_dir.iterdir()
                    if p.is_file()
                    and p.suffix.lower() in {".pdf", ".txt", ".md"}
                    and not p.name.startswith(".")
                )
                if regulations_dir.exists()
                else []
            )
            if not current_files or current_files == cached_files:
                sections: Dict[str, RegulationSection] = {}
                for item in cached.get("sections", []):
                    sec = RegulationSection(
                        key=item["key"],
                        title=item["title"],
                        source_file=item["source_file"],
                        pages=[(int(p[0]), str(p[1])) for p in item.get("pages", [])],
                    )
                    sections[sec.key] = sec
                return sections, cached_files
        except Exception:
            pass

    sections, loaded_files = parse_regulations_from_files(regulations_dir)
    if cache_path is not None and sections:
        try:
            save_regulations_cache(cache_path, sections, loaded_files)
        except OSError:
            # Vercel 등 읽기 전용 서버에서는 캐시 쓰기를 건너뜀
            pass
    return sections, loaded_files


def _expand_query_keywords(question: str) -> List[str]:
    """질문에서 핵심 단어를 뽑고 관련 규정 동의어를 함께 묶어줍니다."""
    tokens = [t for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", question) if len(t) >= 2]
    stopwords = {"있나요", "인가요", "가능한가요", "여부", "관련", "안내", "어떻게", "무엇", "대신", "할수"}
    keywords = [t for t in tokens if t not in stopwords]

    expanded = list(keywords)
    for group in SYNONYM_GROUPS:
        if any(any(g in kw or kw in g for kw in keywords) for g in group):
            for g in group:
                if g not in expanded:
                    expanded.append(g)
    return expanded


def build_context_for_school(
    sections: Dict[str, RegulationSection],
    selected_school: str,
    question: str = "",
) -> Tuple[str, List[RegulationSection]]:
    """
    선택한 대학원에 맞춰 AI에게 전달할 규정 본문을 구성합니다.
    - 단일 대학원 선택 시: [대학원 학칙] + [해당 대학원 시행세칙 전체] + [공통 부속 규정]
    - '전체 비교' 선택 시: [대학원 학칙] + [일반/특수대학원 13곳 중 질문 관련 조항 + 부칙]
      (서버 응답 속도와 정확도를 동시에 지키기 위해 핵심 쪽만 압축 전달)
    """
    chosen: List[RegulationSection] = []

    if "대학원 학칙" in sections:
        chosen.append(sections["대학원 학칙"])

    if selected_school == "전체 비교":
        keywords = _expand_query_keywords(question)
        parts = []
        if "대학원 학칙" in sections:
            sec = sections["대학원 학칙"]
            parts.append(f"====================\n[규정 구분: {sec.title}]\n====================\n{sec.full_text}")

        for school in ["일반대학원", *SPECIAL_GRAD_SCHOOLS]:
            if school not in sections:
                continue
            sec = sections[school]
            chosen.append(sec)

            selected_pages = []
            for pno, txt in sec.pages:
                if not keywords or "부칙" in txt or any(kw in txt for kw in keywords):
                    selected_pages.append((pno, txt))
            # 일치하는 쪽이 너무 적으면 앞/뒤 요약 쪽 포함
            if not selected_pages:
                selected_pages = sec.pages[:3]
            # 대학원당 최대 3쪽 이내로 정리하여 Vercel에서도 빠른 응답 속도 확보
            if len(selected_pages) > 3:
                scored = sorted(
                    selected_pages,
                    key=lambda item: sum(item[1].count(kw) for kw in keywords) + (2 if "부칙" in item[1] else 0),
                    reverse=True,
                )[:3]
                scored.sort(key=lambda item: item[0])
                selected_pages = scored

            chunks = [
                f"[출처: {sec.source_file} / {sec.title} / p.{pno}]\n{txt}"
                for pno, txt in selected_pages
            ]
            parts.append(
                f"====================\n[규정 구분: {sec.title}]\n====================\n"
                + "\n\n".join(chunks)
            )

        for common_key in ["장학금 지급규정", "학·석사 연계과정 운영 규정", "석·박사 통합과정 운영 규정"]:
            if common_key in sections:
                sec = sections[common_key]
                if any(kw in sec.title or any(kw in t for _, t in sec.pages) for kw in keywords):
                    chosen.append(sec)
                    parts.append(f"====================\n[규정 구분: {sec.title}]\n====================\n{sec.full_text}")

        return "\n\n".join(parts), chosen

    # 단일 대학원 선택: 대학원 학칙 + 해당 대학원 시행세칙 전체 + 질문 관련 부속 규정
    if selected_school in sections:
        chosen.append(sections[selected_school])

    q_lower = question.lower()
    conditional_commons = [
        ("장학금 지급규정", ["장학", "감면", "등록금", "성적", "평점"]),
        ("학·석사 연계과정 운영 규정", ["연계", "학석사", "학·석사", "조기"]),
        ("석·박사 통합과정 운영 규정", ["통합", "석박사", "석·박사", "전환"]),
    ]
    for common_key, triggers in conditional_commons:
        if common_key in sections and (not q_lower or any(t in q_lower for t in triggers)):
            chosen.append(sections[common_key])

    if "기타 공통 규정" in sections:
        chosen.append(sections["기타 공통 규정"])

    parts = [
        f"====================\n[규정 구분: {sec.title}]\n====================\n{sec.full_text}"
        for sec in chosen
    ]
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

    patterns: List[str] = []
    for item in article_numbers:
        for m in re.findall(r"제\s*\d+\s*조(?:의\s*\d+)?|부\s*칙", item):
            compact = re.sub(r"\s+", "", m)
            if compact not in patterns:
                patterns.append(compact)

    kw = keyword.strip()

    for sec in target_sections:
        for page_no, page_text in sec.pages:
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
