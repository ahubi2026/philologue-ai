"""views/state.py — Streamlit session_state 초기화, 화면 이동 및 F5 세션 유지"""
import streamlit as st

import config
import db

VALID_PAGES = {"grades", "books", "book", "question", "chat", "reflection", "teacher"}


def init_session_state() -> None:
    for key, value in config.SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_session_state() -> None:
    for key, value in config.SESSION_DEFAULTS.items():
        st.session_state[key] = value


def _sync_nav_params() -> None:
    """현재 화면 위치(page, grade, book, q)를 URL 쿼리 파라미터에 동기화한다."""
    mapping = {
        "page": st.session_state.get("page"),
        "grade": st.session_state.get("grade_id"),
        "book": st.session_state.get("book_id"),
        "q": st.session_state.get("question_id"),
    }
    for param, val in mapping.items():
        if val:
            st.query_params[param] = str(val)
        elif param in st.query_params:
            del st.query_params[param]


def set_logged_in_session(user: dict) -> None:
    """로그인 성공 시 DB 세션 토큰을 발급하고 URL 쿼리 파라미터에 저장한다."""
    token = db.create_session(user["id"])
    st.session_state.user = user
    st.query_params["sid"] = token


def restore_session_from_url() -> None:
    """F5 새로고침으로 session_state가 초기화되었을 때 DB 세션 토큰으로 로그인·화면을 복원한다."""
    if st.session_state.user is not None:
        return
    token = st.query_params.get("sid")
    if not token:
        return
    user = db.get_user_by_session(token)
    if user is None:
        st.query_params.clear()
        return

    st.session_state.user = user
    page = st.query_params.get("page")
    if page in VALID_PAGES:
        st.session_state.page = page
    st.session_state.grade_id = st.query_params.get("grade") or None
    st.session_state.book_id = st.query_params.get("book") or None
    st.session_state.question_id = st.query_params.get("q") or None


def logout_session() -> None:
    """로그아웃 시 DB 세션 토큰과 URL 파라미터·세션 상태를 모두 정리한다."""
    token = st.query_params.get("sid")
    if token:
        db.delete_session(token)
    st.query_params.clear()
    reset_session_state()


def go(page: str, **kwargs) -> None:
    """다른 화면으로 이동한다. kwargs로 선택한 학년·도서·문항을 함께 기억한다."""
    st.session_state.page = page
    for key, value in kwargs.items():
        st.session_state[key] = value
    if st.session_state.user is not None:
        _sync_nav_params()
