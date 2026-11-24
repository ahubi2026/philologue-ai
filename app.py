"""app.py — 필로로그 AI 진입점 및 화면 라우터

현재 구현 범위:
- 0~2단계: 회원가입 · 로그인 · AI 사용 약속 (views/auth.py)
- 3단계  : 학년 선택 → 도서 목록 → 도서 상세 (views/library.py)
- 4단계  : 문항별 내 생각 쓰기·저장 (views/writing.py)
- 5단계  : 소크라테스 AI 문답 · 수준별 비계 · 오류 신고 (views/socratic_chat.py)
- 6단계  : 성찰일지 및 독립적 최종 판단 (views/reflection.py)
- 7단계  : 교사·연구자 대시보드 및 연구용 익명 CSV 추출 (views/teacher.py)

실행:
    cd philologue
    streamlit run app.py
"""
import streamlit as st

import config
import db
import llm_client
from views import auth, library, reflection, socratic_chat, teacher, writing
from views.state import go, init_session_state, logout_session, restore_session_from_url

st.set_page_config(page_title="필로로그 AI", page_icon="📖", layout="wide")


def show_sidebar() -> None:
    user = st.session_state.user
    with st.sidebar:
        role_badge = " 👩‍🏫(교사)" if user.get("role") == "teacher" else ""
        st.write(f"👋 **{user['nickname']}** 님{role_badge}")

        if user.get("role") == "teacher":
            if st.button("👩‍🏫 교사·연구자 대시보드", type="primary", use_container_width=True):
                go("teacher", grade_id=None, book_id=None, question_id=None)
                st.rerun()

        if st.button("🏠 처음으로(학년 선택)", use_container_width=True):
            go("grades", grade_id=None, book_id=None, question_id=None)
            st.rerun()

        st.divider()
        st.markdown("##### ⚙️ 대화 설정")

        # LLM 엔진 전환 (Gemini / OpenAI / 데모 모드)
        provider_keys = list(config.LLM_PROVIDERS.keys())
        current_provider = st.session_state.get("llm_provider", config.DEFAULT_LLM_PROVIDER)
        if current_provider not in provider_keys:
            current_provider = config.DEFAULT_LLM_PROVIDER
        chosen_provider = st.selectbox(
            "AI 엔진",
            options=provider_keys,
            index=provider_keys.index(current_provider),
            format_func=lambda k: config.LLM_PROVIDERS[k],
        )
        st.session_state.llm_provider = chosen_provider
        _, status_msg = llm_client.get_provider_status(chosen_provider)
        st.caption(status_msg)

        # 독해 수준 전환 (연구문제 3: 수준별 비계 테스트·조정)
        level_keys = list(config.READING_LEVELS.keys())
        current_level = user.get("reading_level", "standard")
        if current_level not in level_keys:
            current_level = "standard"
        chosen_level = st.selectbox(
            "독해 수준(질문 난이도)",
            options=level_keys,
            index=level_keys.index(current_level),
            format_func=lambda k: config.READING_LEVELS[k],
        )
        if chosen_level != current_level:
            db.update_reading_level(user["id"], chosen_level)
            st.session_state.user["reading_level"] = chosen_level
            st.rerun()

        st.divider()
        if st.button("로그아웃", use_container_width=True):
            logout_session()
            st.rerun()


PAGES = {
    "grades": library.show_grades,
    "books": library.show_books,
    "book": library.show_book_detail,
    "question": writing.show_question,
    "chat": socratic_chat.show_chat,
    "reflection": reflection.show_reflection,
    "teacher": teacher.show_dashboard,
}


def main() -> None:
    db.init_db()
    init_session_state()
    restore_session_from_url()

    user = st.session_state.user
    if user is None:
        auth.show_login()
        return

    show_sidebar()
    if user.get("role") != "teacher" and not user.get("pledge_agreed", False):
        auth.show_pledge()
        return

    default_page = teacher.show_dashboard if user.get("role") == "teacher" else library.show_grades
    PAGES.get(st.session_state.page, default_page)()


if __name__ == "__main__":
    main()
