"""views/writing.py — 4단계: 문항별 내 생각 쓰기(1차 해석 저장)"""
import streamlit as st

import catalog
import db
from views.state import go


def show_question() -> None:
    book = catalog.get_book(st.session_state.grade_id, st.session_state.book_id)
    q = catalog.get_question(st.session_state.grade_id, st.session_state.book_id, st.session_state.question_id)
    if book is None or q is None:
        go("book")
        st.rerun()

    user_id = st.session_state.user["id"]
    min_len = catalog.get_min_answer_len(st.session_state.grade_id)

    if st.button("← 생각해볼 문제로"):
        go("book")
        st.rerun()

    st.caption(f"{book['title']} · {q['stage']}")
    st.subheader(q["text"])

    st.markdown("#### ✏️ 내 생각 쓰기")
    st.write(
        "AI와 대화하기 전에 **먼저 내 생각을** 써 보세요. "
        "책의 어느 장면에서 그렇게 생각했는지 **근거**도 함께 쓰면 좋아요."
    )

    latest = db.get_latest_answer(user_id, q["id"])
    with st.form(f"answer_form_{q['id']}"):
        text = st.text_area(
            "내 생각",
            value=latest["answer"] if latest else "",
            height=220,
            placeholder="나는 ~라고 생각한다. 왜냐하면 책에서 ~ 장면이 있기 때문이다.",
            label_visibility="collapsed",
        )
        saved = st.form_submit_button("저장하기 💾", use_container_width=True)

    if saved:
        cleaned = text.strip()
        if len(cleaned) < min_len:
            st.warning(f"조금 더 자세히 써 볼까요? 최소 {min_len}자 이상 써 주세요. (지금 {len(cleaned)}자)")
        else:
            db.save_answer(user_id, book["id"], q["id"], cleaned)
            st.success("저장되었습니다!")
            latest = db.get_latest_answer(user_id, q["id"])

    if latest:
        st.caption(f"마지막 저장: {latest['created_at'].replace('T', ' ')}")

    st.divider()
    # 설계원리 ①: 자기 읽기·자기 해석 선행 — 답을 저장해야 AI 대화 진입 가능
    if st.button(
        "🤖 소크라테스 AI와 대화하기 →",
        use_container_width=True,
        type="primary",
        disabled=latest is None,
    ):
        go("chat", question_id=q["id"])
        st.rerun()
    if latest is None:
        st.caption("내 생각을 저장하면 AI와 대화할 수 있어요.")

    # 같은 책의 다음 문제로 이동
    ids = [x["id"] for x in book["questions"]]
    idx = ids.index(q["id"])
    if idx + 1 < len(ids):
        if st.button("다음 문제로 →", use_container_width=True):
            go("question", question_id=ids[idx + 1])
            st.rerun()
