"""views/library.py — 3단계: 학년 선택 → 도서 목록 → 도서 상세(생각해볼 문제)"""
import streamlit as st

import catalog
import config
import db
from views.state import go


def show_grades() -> None:
    st.title("📚 학년을 선택하세요")
    st.write(f"{st.session_state.user['nickname']} 님, 오늘은 어떤 책을 함께 생각해 볼까요?")

    grades = catalog.get_grades()

    # 학교급별 그룹핑 (초·중·고 확장 시 자동 분류)
    grouped: dict[str, list[dict]] = {}
    for grade in grades:
        level = catalog.infer_school_level(grade)
        grouped.setdefault(level, []).append(grade)

    level_order = [lv for lv in ("elementary", "middle", "high") if lv in grouped]
    for lv in level_order:
        st.subheader(config.SCHOOL_LEVEL_LABELS.get(lv, lv))
        cols = st.columns(2)
        for i, grade in enumerate(grouped[lv]):
            with cols[i % 2]:
                count = len(grade["books"])
                label = f"{grade['name']}\n\n도서 {count}권" if count else f"{grade['name']}\n\n(준비 중)"
                if st.button(label, key=f"grade_{grade['id']}", use_container_width=True, disabled=(count == 0)):
                    go("books", grade_id=grade["id"])
                    st.rerun()


def show_books() -> None:
    grade = catalog.get_grade(st.session_state.grade_id)
    if grade is None:
        go("grades")
        st.rerun()

    if st.button("← 학년 선택으로"):
        go("grades")
        st.rerun()

    st.title(f"📖 {grade['name']} 도서")
    st.caption("읽은 책을 선택하면 생각해볼 문제가 나옵니다.")

    for book in sorted(grade["books"], key=lambda b: b["session"]):
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.markdown(f"**{book['session']}차시 · {book['theme']}**")
                st.markdown(f"### {book['title']}")
                info = " / ".join(x for x in [book.get("author", ""), book.get("publisher", "")] if x)
                if info:
                    st.caption(info)
            with right:
                st.write("")
                if st.button("선택", key=f"book_{book['id']}", use_container_width=True):
                    go("book", book_id=book["id"])
                    st.rerun()


def show_book_detail() -> None:
    book = catalog.get_book(st.session_state.grade_id, st.session_state.book_id)
    if book is None:
        go("books")
        st.rerun()

    if st.button("← 도서 목록으로"):
        go("books")
        st.rerun()

    st.caption(f"{book['session']}차시 · {book['theme']}")
    st.title(book["title"])
    info = " / ".join(x for x in [book.get("author", ""), book.get("publisher", "")] if x)
    if info:
        st.write(info)
    st.info(f"이번 책에서 기를 사고력: **{book['focus']}**")

    st.subheader("🤔 생각해볼 문제")
    st.write("문제를 하나 골라 먼저 **내 생각**을 써 보세요. 그다음 소크라테스 AI와 대화합니다.")

    answered = db.get_answered_question_ids(st.session_state.user["id"], book["id"])
    chatted = db.get_chatted_question_ids(st.session_state.user["id"], book["id"])
    reflected = db.get_reflected_question_ids(st.session_state.user["id"], book["id"])
    total = len(book["questions"])
    st.progress(
        len(reflected) / total if total else 0,
        text=f"1차 작성 {len(answered)}/{total}  ·  AI 대화 {len(chatted)}/{total}  ·  성찰 완료 {len(reflected)}/{total}",
    )

    for i, q in enumerate(book["questions"], start=1):
        with st.container(border=True):
            color = config.STAGE_COLOR.get(q["stage"], "gray")
            done = q["id"] in answered
            has_chat = q["id"] in chatted
            has_ref = q["id"] in reflected
            badges = (
                ("  ✅ 1차 작성" if done else "")
                + ("  💬 AI 대화" if has_chat else "")
                + ("  📝 성찰 완료" if has_ref else "")
            )
            st.markdown(f":{color}[**{i}. {q['stage']}**]{badges}")
            st.write(q["text"])
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                if st.button(
                    "내 답 고치기 ✏️" if done else "내 생각 쓰기 ✏️",
                    key=f"q_{q['id']}",
                    use_container_width=True,
                ):
                    go("question", question_id=q["id"])
                    st.rerun()
            with col_b:
                if st.button(
                    "AI 대화 이어하기 🤖" if has_chat else "AI 대화하기 🤖",
                    key=f"chat_{q['id']}",
                    use_container_width=True,
                    disabled=not done,
                ):
                    go("chat", question_id=q["id"])
                    st.rerun()
            with col_c:
                if st.button(
                    "성찰일지 보기 📝" if has_ref else "성찰일지 쓰기 📝",
                    key=f"ref_{q['id']}",
                    use_container_width=True,
                    disabled=not has_chat,
                ):
                    go("reflection", question_id=q["id"])
                    st.rerun()
