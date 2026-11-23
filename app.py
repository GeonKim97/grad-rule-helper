"""
대학원 학사 규정 Q&A 및 상담 메모 앱 (메인 화면)
실행 방법:
    .venv\\Scripts\\streamlit.exe run app.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

import streamlit as st

from consultations import (
    append_consultation,
    dataframe_to_excel_csv_bytes,
    load_consultations,
)
from gemini_helper import QAResponse, ask_regulation_qa, get_api_key_status
from regulations import (
    GRAD_SCHOOL_OPTIONS,
    build_context_for_school,
    extract_matching_original_clauses,
    load_regulation_sections,
)

# 경로 설정 (항상 현재 작업 폴더 grad-rule-helper 내부만 사용)
BASE_DIR = Path(__file__).resolve().parent
REGULATIONS_DIR = BASE_DIR / "data" / "regulations"
SAMPLE_CSV_PATH = BASE_DIR / "data" / "sample_consultations.csv"
WORKING_CSV_PATH = BASE_DIR / "data" / "consultations.csv"

# 빈출 민원 질문 퀵 버튼 목록
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


@st.cache_data(show_spinner=False)
def cached_load_regulations(dir_path_str: str):
    """PDF 규정을 앱 실행 시 한 번만 읽어 빠르게 재사용합니다."""
    return load_regulation_sections(Path(dir_path_str))


def init_session_state() -> None:
    """화면에서 기억해야 할 입력값·검색 결과 초기값을 준비합니다."""
    defaults = {
        "question_input": "",
        "trigger_search": False,
        "last_result": None,
        "last_school": "일반대학원",
        "last_year": "미지정 (전체 기준)",
        "last_question": "",
        "last_target_sections": [],
        # 메모 폼 상태
        "memo_student_id": "",
        "memo_name": "",
        "memo_school": "일반대학원",
        "memo_dept": "",
        "memo_question": "",
        "memo_summary": "",
        "memo_citations": "",
        "memo_notes": "",
        "memo_applied_notice": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def apply_styles() -> None:
    """전화 응대 중 눈이 편안하도록 3단 답변 카드 스타일을 적용합니다."""
    st.markdown(
        """
        <style>
        .main-header {
            background: linear-gradient(135deg, #1b365d 0%, #2c5282 100%);
            color: white;
            padding: 1.25rem 1.5rem;
            border-radius: 12px;
            margin-bottom: 1.2rem;
        }
        .main-header h2 {
            margin: 0 0 0.25rem 0;
            font-size: 1.45rem;
            color: white;
        }
        .main-header p {
            margin: 0;
            font-size: 0.92rem;
            opacity: 0.92;
        }
        .conclusion-card {
            background-color: #eef6ff;
            border-left: 6px solid #1d4ed8;
            padding: 1rem 1.2rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        .conclusion-title {
            font-weight: 700;
            color: #1e3a8a;
            font-size: 0.95rem;
            margin-bottom: 0.35rem;
        }
        .conclusion-body {
            font-size: 1.08rem;
            font-weight: 600;
            color: #0f172a;
            line-height: 1.55;
        }
        .caution-box {
            background-color: #fffbeb;
            border-left: 5px solid #d97706;
            padding: 0.85rem 1rem;
            border-radius: 8px;
            margin-top: 0.6rem;
        }
        .citation-pill {
            display: inline-block;
            background-color: #f1f5f9;
            border: 1px solid #cbd5e1;
            color: #1e293b;
            padding: 0.25rem 0.65rem;
            border-radius: 999px;
            font-size: 0.86rem;
            margin: 0.15rem 0.3rem 0.15rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_citations_brief(result: QAResponse) -> str:
    """근거 조항 목록을 메모란에 넣기 좋은 한 줄 문자열로 정리합니다."""
    if not result.citations:
        return "규정 원문 확인 필요"
    items = []
    for c in result.citations:
        label = " ".join(part for part in [c.document, c.article] if part).strip()
        if c.page:
            label = f"{label} ({c.page})" if label else c.page
        if label and label not in items:
            items.append(label)
    return "; ".join(items)


def main() -> None:
    st.set_page_config(
        page_title="대학원 학사 규정 Q&A 및 상담 메모 앱",
        page_icon="🎓",
        layout="wide",
    )
    init_session_state()
    apply_styles()

    # 규정 문서 불러오기
    with st.spinner("학칙·시행세칙 규정 문서를 불러오는 중입니다..."):
        sections, loaded_files = cached_load_regulations(str(REGULATIONS_DIR))

    # 상단 배너
    st.markdown(
        """
        <div class="main-header">
            <h2>🎓 대학원 학사 규정 Q&amp;A 및 상담 메모 앱</h2>
            <p>전화 응대 중 학칙·시행세칙을 3단 구조로 빠르게 확인하고, 원클릭으로 상담 메모를 남겨 엑셀(CSV)로 저장하세요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 사이드바: 현재 상태 및 사용 안내 (비밀 키 값은 절대 표시하지 않음)
    with st.sidebar:
        st.subheader("📌 시스템 연결 상태")
        if get_api_key_status():
            st.success("Gemini API 키 연결 준비 완료 (.env 확인됨)")
        else:
            st.warning(
                "`.env` 파일에 API 키가 아직 없거나 예시 문구 그대로입니다. "
                "키를 입력한 뒤 새로고침(F5)해 주세요."
            )

        st.divider()
        st.subheader("📚 불러온 규정 파일")
        if loaded_files:
            for fname in loaded_files:
                st.caption(f"• {fname}")
            st.caption(f"인식된 규정 영역: 총 {len(sections)}개")
        else:
            st.warning("`data/regulations/` 폴더에 규정 파일이 없습니다.")

        if st.button("🔄 규정 파일 다시 불러오기", use_container_width=True):
            cached_load_regulations.clear()
            st.rerun()

        st.divider()
        st.info(
            "**개인정보 보호 안내**\n\n"
            "테스트할 때는 실제 학생의 이름·학번·연락처를 넣지 말고, "
            "가상 학번과 가명(예: `2025-G0099`, `김가상`)만 입력해 주세요."
        )

    # ==========================================================
    # 1. 상단 검색 조건 (대학원 구분 + 입학년도) & 질문 입력
    # ==========================================================
    st.subheader("1️⃣ 상담 조건 선택 및 질문 검색")

    col_school, col_year, col_custom_year = st.columns([2.2, 1.5, 1.3])
    with col_school:
        selected_school = st.selectbox(
            "대학원 구분",
            options=GRAD_SCHOOL_OPTIONS,
            index=1,  # 기본값: 일반대학원
            help="특정 대학원을 선택하면 해당 대학원 시행세칙과 학칙을 집중적으로 찾습니다.",
        )

    with col_year:
        selected_year_option = st.selectbox(
            "입학년도 (부칙·경과조치 확인용)",
            options=ADMISSION_YEAR_OPTIONS,
            index=0,
        )

    with col_custom_year:
        if selected_year_option == "직접 입력":
            custom_year = st.text_input(
                "입학년도 직접 입력",
                placeholder="예: 2019학년도",
            )
            admission_year = custom_year.strip() or "미지정 (전체 기준)"
        else:
            admission_year = selected_year_option
            st.text_input(
                "선택된 기준",
                value=admission_year,
                disabled=True,
            )

    # 빈출 질문 퀵 버튼
    st.caption("⚡ 빈출 질문 퀵 버튼 (누르면 바로 검색됩니다)")
    q_cols = st.columns(3)
    for idx, q_text in enumerate(QUICK_QUESTIONS):
        with q_cols[idx % 3]:
            if st.button(f"💬 {q_text}", key=f"quick_q_{idx}", use_container_width=True):
                st.session_state.question_input = q_text
                st.session_state.trigger_search = True

    # 질문 검색창 + [답변 검색] 버튼
    search_col, btn_col = st.columns([4.5, 1.2])
    with search_col:
        question = st.text_input(
            "민원 질문 또는 키워드 입력",
            key="question_input",
            placeholder="예: 논문 대신 학점으로 졸업할 수 있나요?",
            label_visibility="collapsed",
        )
    with btn_col:
        search_clicked = st.button(
            "🔍 답변 검색",
            type="primary",
            use_container_width=True,
        )

    should_run_search = search_clicked or st.session_state.trigger_search
    if should_run_search:
        st.session_state.trigger_search = False
        cleaned_question = question.strip()
        if not cleaned_question:
            st.warning("질문이나 키워드를 먼저 입력해 주세요.")
        else:
            context_text, target_sections = build_context_for_school(sections, selected_school)
            with st.spinner(f"[{selected_school}] 규정을 꼼꼼히 찾아 3단 답변을 정리하고 있습니다..."):
                result = ask_regulation_qa(
                    question=cleaned_question,
                    selected_school=selected_school,
                    admission_year=admission_year,
                    regulation_context=context_text,
                )
            st.session_state.last_result = result
            st.session_state.last_school = selected_school
            st.session_state.last_year = admission_year
            st.session_state.last_question = cleaned_question
            st.session_state.last_target_sections = target_sections
            st.session_state.memo_applied_notice = False

    # ==========================================================
    # 2. 3단 답변 결과 영역
    # ==========================================================
    result: QAResponse | None = st.session_state.last_result
    if result is not None:
        st.divider()
        st.subheader(
            f"2️⃣ 규정 검색 결과 — [{st.session_state.last_school} / {st.session_state.last_year}]"
        )

        if not result.ok:
            st.error(result.error_message)
        else:
            # ① 한 줄 결론 (즉답)
            st.markdown(
                f"""
                <div class="conclusion-card">
                    <div class="conclusion-title">① 한 줄 결론 (전화 즉답용)</div>
                    <div class="conclusion-body">{result.one_line_conclusion}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # ② 세부 요건 · 구비서류 · 부칙(경과조치) 주의사항
            with st.container(border=True):
                st.markdown("#### ② 세부 요건 · 구비서류 · 부칙(경과조치) 주의사항")

                detail_col, doc_col = st.columns(2)
                with detail_col:
                    st.markdown("**✔ 세부 요건**")
                    if result.details:
                        for item in result.details:
                            st.markdown(f"- {item}")
                    else:
                        st.caption("세부 요건 정보가 없습니다.")

                with doc_col:
                    st.markdown("**📄 구비서류 및 신청 절차**")
                    if result.required_documents:
                        for item in result.required_documents:
                            st.markdown(f"- {item}")
                    else:
                        st.caption("규정 원문에 별도 명시 없음 (소속 대학원/학과 확인 필요)")

                if result.comparison_note:
                    st.markdown("**⚖️ 대학원별 비교 핵심 포인트**")
                    st.info(result.comparison_note)

                if result.addendum_caution:
                    st.markdown(
                        f"""
                        <div class="caution-box">
                            <strong>⚠️ 부칙(경과조치) 및 입학년도 주의사항</strong><br/>
                            {result.addendum_caution}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            # ③ 근거 조항 및 원문 펼쳐보기
            with st.container(border=True):
                st.markdown("#### ③ 근거 조항 및 원문 대조")

                if result.citations:
                    pills_html = "".join(
                        f'<span class="citation-pill">📌 {c.document} {c.article} ({c.page})</span>'
                        for c in result.citations
                    )
                    st.markdown(pills_html, unsafe_allow_html=True)
                else:
                    st.caption("명시된 근거 조항이 없습니다.")

                with st.expander("📖 근거 조항 원문 펼쳐보기", expanded=False):
                    st.markdown("**[AI가 인용한 근거 조항 발췌]**")
                    if result.citations:
                        for idx, c in enumerate(result.citations, start=1):
                            st.markdown(f"**{idx}. {c.document} — {c.article}** (`{c.page}`)")
                            st.code(c.excerpt or "(원문 발췌 없음)", language=None)
                    else:
                        st.caption("인용된 조항이 없습니다.")

                    st.divider()
                    st.markdown("**[실제 PDF 규정 원문 직접 대조]**")
                    manual_kw = st.text_input(
                        "원문 안에서 찾을 단어 (비워두면 위 근거 조항 번호로 자동 검색)",
                        key="raw_verify_kw",
                        placeholder="예: 학점, 대체, 부칙, 제24조",
                    )
                    article_hints = [c.article for c in result.citations]
                    raw_matches = extract_matching_original_clauses(
                        target_sections=st.session_state.last_target_sections,
                        article_numbers=article_hints,
                        keyword=manual_kw,
                        max_items=8,
                    )
                    if raw_matches:
                        for m in raw_matches:
                            st.caption(
                                f"📄 {m['source_file']} | {m['section']} | p.{m['page']} (일치: {m['match']})"
                            )
                            st.text(m["text"])
                    else:
                        st.caption(
                            "일치하는 원문 단락을 찾지 못했습니다. 위 입력칸에 핵심 단어(예: 논문, 휴학, 부칙)를 넣어 직접 대조해 보세요."
                        )

            # [메모에 반영] 원클릭 버튼
            action_col1, action_col2 = st.columns([1.4, 3.6])
            with action_col1:
                if st.button("📋 메모에 반영", type="primary", use_container_width=True):
                    st.session_state.memo_school = st.session_state.last_school
                    st.session_state.memo_question = st.session_state.last_question
                    st.session_state.memo_summary = (
                        result.memo_summary or result.one_line_conclusion
                    )
                    st.session_state.memo_citations = format_citations_brief(result)
                    st.session_state.memo_applied_notice = True
                    st.rerun()
            with action_col2:
                if st.session_state.memo_applied_notice:
                    st.success("아래 상담 메모란에 답변 요약과 근거 조항을 옮겼습니다! 이름·학과·특이사항을 적고 [상담 저장]을 눌러 주세요.")
                else:
                    st.caption("응대 내용을 상담 일지에 바로 남기려면 [메모에 반영] 버튼을 누르세요.")

    # ==========================================================
    # 3. 상담 메모 작성 및 저장
    # ==========================================================
    st.divider()
    st.subheader("3️⃣ 상담 메모 작성 및 저장")

    with st.container(border=True):
        m_row1_1, m_row1_2, m_row1_3, m_row1_4 = st.columns([1.2, 1.1, 1.3, 1.4])
        with m_row1_1:
            memo_name = st.text_input(
                "상담자 이름 (가명 권장)",
                key="memo_name",
                placeholder="예: 김가상",
            )
        with m_row1_2:
            memo_student_id = st.text_input(
                "가상 학번",
                key="memo_student_id",
                placeholder="예: 2025-G0099",
            )
        with m_row1_3:
            memo_school = st.text_input(
                "소속 대학원",
                key="memo_school",
                placeholder="예: 공학대학원",
            )
        with m_row1_4:
            memo_dept = st.text_input(
                "학과 / 전공",
                key="memo_dept",
                placeholder="예: 컴퓨터공학과",
            )

        memo_question = st.text_input(
            "상담 질문 내용",
            key="memo_question",
            placeholder="예: 논문 대신 학점 대체 가능 여부",
        )
        memo_summary = st.text_area(
            "안내 요약 (메모에 반영 버튼으로 자동 입력)",
            key="memo_summary",
            height=78,
            placeholder="핵심 안내 내용이 여기에 채워집니다.",
        )
        memo_citations = st.text_input(
            "근거 조항 (메모에 반영 버튼으로 자동 입력)",
            key="memo_citations",
            placeholder="예: 공학대학원 학칙시행세칙 제24조",
        )
        memo_notes = st.text_area(
            "특이사항 메모",
            key="memo_notes",
            height=78,
            placeholder="예: 지도교수 승인서 제출 일정 안내함 / 다음 주 재문의 예정",
        )

        save_col, hint_col = st.columns([1.3, 3.7])
        with save_col:
            save_clicked = st.button("💾 상담 저장", type="primary", use_container_width=True)
        with hint_col:
            st.caption("저장된 내역은 아래 상담 이력 표에 즉시 쌓이며, CSV 파일로 내려받아 엑셀에서 열 수 있습니다.")

        if save_clicked:
            if not memo_name.strip() and not memo_summary.strip() and not memo_notes.strip():
                st.warning("상담자 이름이나 상담 내용을 한 가지 이상 입력해 주세요.")
            else:
                append_consultation(
                    sample_path=SAMPLE_CSV_PATH,
                    working_path=WORKING_CSV_PATH,
                    record={
                        "대학원구분": memo_school or st.session_state.last_school,
                        "입학년도": st.session_state.last_year,
                        "가상학번": memo_student_id or "미입력",
                        "상담자이름": memo_name or "미입력",
                        "학과": memo_dept or "미입력",
                        "질문내용": memo_question or st.session_state.last_question,
                        "답변요약": memo_summary,
                        "근거조항": memo_citations,
                        "특이사항": memo_notes,
                    },
                )
                st.success("상담 내역이 저장되었습니다! 아래 목록에서 바로 확인하실 수 있어요.")

    # ==========================================================
    # 4. 누적 상담 이력 목록 표 + [CSV 다운로드]
    # ==========================================================
    st.divider()
    header_col, download_col = st.columns([3.5, 1.5])
    df_consultations = load_consultations(SAMPLE_CSV_PATH, WORKING_CSV_PATH)

    with header_col:
        st.subheader(f"4️⃣ 저장된 상담 이력 목록 (총 {len(df_consultations)}건)")

    with download_col:
        csv_bytes = dataframe_to_excel_csv_bytes(df_consultations)
        today_str = datetime.now().strftime("%Y%m%d")
        st.download_button(
            label="📥 CSV 다운로드 (엑셀용)",
            data=csv_bytes,
            file_name=f"대학원_상담이력_{today_str}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    filter_kw = st.text_input(
        "상담 이력 빠른 찾기",
        placeholder="이름, 대학원, 학과, 키워드로 이력 필터링...",
        label_visibility="collapsed",
    )
    if filter_kw.strip():
        mask = df_consultations.apply(
            lambda row: filter_kw.strip().lower() in " ".join(row.values).lower(),
            axis=1,
        )
        view_df = df_consultations[mask]
    else:
        view_df = df_consultations

    st.dataframe(view_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
