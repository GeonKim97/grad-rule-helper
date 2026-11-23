"""
Gemini AI에게 학사 규정 질문을 보내고 3단 구조로 답변을 받아오는 모듈입니다.
비유하자면, 방대한 규정집을 빠르게 읽고 전화 응대용 요약 메모를
딱 맞게 정리해 주는 '규정 전문 비서' 역할을 합니다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv
from google import genai
from google.genai import types

# 우선 사용할 Gemini 모델 목록 (가장 빠르고 문서 이해력이 좋은 Flash 계열)
PREFERRED_MODELS: List[str] = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

PLACEHOLDER_KEYS = {
    "",
    "여기에_발급받은_API_키를_입력하세요",
    "여기에_제미나이_API_키를_입력하세요",
    "YOUR_API_KEY",
    "your_api_key_here",
}


@dataclass
class CitationItem:
    """근거 조항 1건의 정보"""

    document: str  # 예: 공학대학원 학칙시행세칙
    article: str  # 예: 제24조(논문대체 학점이수)
    page: str  # 예: p.53
    excerpt: str  # 원문 발췌


@dataclass
class QAResponse:
    """전화 응대용 3단 구조 답변 결과"""

    ok: bool
    one_line_conclusion: str = ""
    details: List[str] = field(default_factory=list)
    required_documents: List[str] = field(default_factory=list)
    addendum_caution: str = ""
    comparison_note: str = ""
    citations: List[CitationItem] = field(default_factory=list)
    memo_summary: str = ""
    used_model: str = ""
    error_message: str = ""


def get_api_key_status() -> bool:
    """
    .env 파일에서 GEMINI_API_KEY가 정상적으로 설정되어 있는지만 확인합니다.
    보안을 위해 실제 키 값은 절대 반환하거나 화면에 출력하지 않습니다.
    """
    load_dotenv(override=True)
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    return bool(key) and key not in PLACEHOLDER_KEYS


def _friendly_error_message(exc: Exception) -> str:
    """어려운 영어 오류 메시지를 행정 직원이 이해하기 쉬운 안내 문구로 바꿉니다."""
    raw = str(exc).lower()

    if any(k in raw for k in ["api_key_invalid", "api key not valid", "invalid api key", "permission_denied", "401", "403"]):
        return (
            "잠시 연결이 원활하지 않아요. `.env` 파일에 입력한 Gemini API 키가 올바른지 "
            "(앞뒤 공백이나 따옴표가 들어가지 않았는지) 다시 한 번 확인해 주세요."
        )
    if any(k in raw for k in ["resource_exhausted", "quota", "429", "rate limit"]):
        return (
            "잠시 요청이 몰려 AI 응답 한도에 도달했어요. "
            "1분 정도 뒤에 다시 [답변 검색] 버튼을 눌러 주세요."
        )
    if any(k in raw for k in ["connection", "timeout", "deadline", "dns", "getaddrinfo", "network", "ssl"]):
        return (
            "잠시 인터넷 연결이 원활하지 않아요. "
            "네트워크 연결 상태를 확인하신 뒤 다시 시도해 주세요."
        )
    return (
        "잠시 연결이 원활하지 않아요. `.env` 파일의 API 키나 인터넷 연결을 확인해 주세요. "
        "(문제가 계속되면 잠시 후 다시 시도해 주세요.)"
    )


def _extract_json_payload(text: str) -> dict:
    """AI 응답 텍스트에서 JSON 객체만 안전하게 꺼냅니다."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def ask_regulation_qa(
    question: str,
    selected_school: str,
    admission_year: str,
    regulation_context: str,
) -> QAResponse:
    """
    규정 본문과 사용자 질문(대학원 구분, 입학년도 포함)을 바탕으로
    Gemini에게 3단 구조 답변을 요청합니다.
    """
    load_dotenv(override=True)
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()

    if not api_key or api_key in PLACEHOLDER_KEYS:
        return QAResponse(
            ok=False,
            error_message=(
                "잠시 연결이 원활하지 않아요. `.env` 파일(또는 Vercel의 Environment Variables)에 "
                "GEMINI_API_KEY가 올바르게 입력되어 있는지 확인해 주세요."
            ),
        )

    if not regulation_context.strip():
        return QAResponse(
            ok=False,
            error_message=(
                "`data/regulations/` 폴더에서 읽을 수 있는 규정 문서를 찾지 못했어요. "
                "학칙·시행세칙 PDF 또는 텍스트 파일이 들어 있는지 확인해 주세요."
            ),
        )

    system_instruction = """
당신은 수원대학교 대학원 교학팀 행정 직원의 전화 민원 응대를 돕는 '학사 규정 전문 보조 AI'입니다.
반드시 아래 규칙을 철저히 지키세요.

[핵심 원칙]
1. 제공된 [규정 원문]에 있는 내용만 근거로 답변하세요. 원문에 없는 규정을 지어내거나 추측하지 마세요.
2. 원문에 명확히 나와 있지 않은 세부 사항(예: 양식 파일 위치, 부서별 내부 접수 마감일 등)은 "규정 원문에 별도 명시 없음 (소속 대학원/학과 사무실 확인 필요)"으로 정직하게 안내하세요.
3. 선택한 대학원 구분을 엄격히 구분하세요.
   - 특정 대학원(예: 일반대학원, 공학대학원, 교육대학원 등)이 선택된 경우, 반드시 해당 대학원 학칙시행세칙과 공통 학칙을 기준으로 답하고 다른 대학원 규정과 혼동하지 마세요.
   - '전체 비교'가 선택된 경우, 일반대학원과 특수대학원(가능한 경우 각 대학원별 차이점 포함)의 규정을 비교해서 명확히 정리하세요.
4. 입학년도가 지정된 경우, 해당 규정의 [부칙(경과조치, 적용례, 시행일)]을 반드시 확인하여 해당 입학년도 학생에게 개정 전/후 규정 중 어느 기준이 적용되는지 주의사항에 명시하세요. 입학년도가 '미지정'인 경우에도 부칙에 입학년도별 적용 차이가 있으면 꼭 짚어 주세요.
5. 전화 응대 중 3초 안에 읽고 답할 수 있도록, 쉬운 한국어와 간결한 문장으로 작성하세요.
6. 근거 조항의 원문 발췌(excerpt)는 제공된 [규정 원문]에서 핵심 문장을 최대한 그대로 옮겨 적으세요.

[출력 형식]
반드시 아래 키를 가진 순수 JSON 객체 하나만 반환하세요.
{
  "one_line_conclusion": "전화 응대 시 바로 말할 수 있는 1~2문장의 명쾌한 한 줄 결론",
  "details": [
    "세부 요건 1 (숫자·학점·성적·기한 등 구체적 기준 포함)",
    "세부 요건 2"
  ],
  "required_documents": [
    "구비서류 또는 신청 절차 1 (원문에 명시된 경우 구체적으로, 없으면 확인 필요 안내)"
  ],
  "addendum_caution": "부칙(경과조치·시행일·입학년도별 적용 차이) 및 대학원별 차이 주의사항. 특별한 경과조치가 없으면 '해당 조항과 관련하여 별도의 부칙 경과조치 주의사항은 확인되지 않으나, 최신 개정일 기준 적용 여부를 함께 확인하세요.'처럼 안내.",
  "comparison_note": "'전체 비교'일 때 일반대학원 vs 특수대학원 차이 요약 (단일 대학원 선택 시 빈 문자열 \"\")",
  "citations": [
    {
      "document": "문서명 (예: 공학대학원 학칙시행세칙)",
      "article": "조항 번호 및 제목 (예: 제24조(논문대체))",
      "page": "출처 쪽번호 (예: p.53)",
      "excerpt": "원문에서 그대로 발췌한 핵심 조항 문구"
    }
  ],
  "memo_summary": "상담 메모란에 바로 붙여넣을 1~2줄 요약 (핵심 결론 + 안내 포인트)"
}
""".strip()

    user_prompt = f"""
[상담 조건]
- 선택 대학원: {selected_school}
- 학생 입학년도: {admission_year}
- 민원 질문: {question}

[규정 원문]
{regulation_context}
""".strip()

    client = genai.Client(api_key=api_key)
    last_error: Exception | None = None

    for model_name in PREFERRED_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            raw_text = (response.text or "").strip()
            if not raw_text:
                raise ValueError("Empty response from Gemini")

            data = _extract_json_payload(raw_text)

            citations: List[CitationItem] = []
            for c in data.get("citations", []):
                if isinstance(c, dict):
                    citations.append(
                        CitationItem(
                            document=str(c.get("document", "")).strip(),
                            article=str(c.get("article", "")).strip(),
                            page=str(c.get("page", "")).strip(),
                            excerpt=str(c.get("excerpt", "")).strip(),
                        )
                    )

            details = [str(x).strip() for x in data.get("details", []) if str(x).strip()]
            req_docs = [str(x).strip() for x in data.get("required_documents", []) if str(x).strip()]

            return QAResponse(
                ok=True,
                one_line_conclusion=str(data.get("one_line_conclusion", "")).strip(),
                details=details,
                required_documents=req_docs,
                addendum_caution=str(data.get("addendum_caution", "")).strip(),
                comparison_note=str(data.get("comparison_note", "")).strip(),
                citations=citations,
                memo_summary=str(data.get("memo_summary", "")).strip(),
                used_model=model_name,
            )
        except Exception as exc:
            last_error = exc
            err_lower = str(exc).lower()
            # 모델 이름 미지원(404/not found)일 때만 다음 예비 모델로 자동 전환
            if "not found" in err_lower or "404" in err_lower or "unsupported" in err_lower:
                continue
            return QAResponse(ok=False, error_message=_friendly_error_message(exc))

    return QAResponse(
        ok=False,
        error_message=_friendly_error_message(last_error or RuntimeError("Unknown error")),
    )
