"""views/reflection.py — 6단계: 성찰일지 및 독립적 최종 판단

설계 근거:
- 설계원리 ④(판단의 귀속성): 최종 결론과 수정 이유는 AI 도움 없이 학습자가 스스로 작성한다.
- 논문 4단계(토론·판단): 1차 해석과 AI 대화 기록을 비교하며 최종 판단을 정리하고,
  동료들과 나눌 공동체 토론 질문을 직접 만든다.
"""
import streamlit as st

import catalog
import config
import db
from views.state import go


def show_reflection() -> None:
    book = catalog.get_book(st.session_state.grade_id, st.session_state.book_id)
    q = catalog.get_question(st.session_state.grade_id, st.session_state.book_id, st.session_state.question_id)
    if book is None or q is None:
        go("book")
        st.rerun()

    user_id = st.session_state.user["id"]
    latest_answer = db.get_latest_answer(user_id, q["id"])
    if latest_answer is None:
        st.warning("성찰일지를 쓰기 전에 먼저 1차 생각을 저장해 주세요.")
        go("question", question_id=q["id"])
        st.rerun()

    logs = db.get_chat_logs(user_id, q["id"])
    user_turns = sum(1 for row in logs if row["role"] == "user")
    latest_ref = db.get_latest_reflection(user_id, q["id"])
    min_len = catalog.get_min_answer_len(st.session_state.grade_id)

    # 상단 내비게이션
    nav_l, nav_r = st.columns(2)
    with nav_l:
        if st.button("← 소크라테스 대화로 돌아가기", use_container_width=True):
            go("chat", question_id=q["id"])
            st.rerun()
    with nav_r:
        if st.button("📚 생각해볼 문제 목록", use_container_width=True):
            go("book")
            st.rerun()

    st.caption(f"{book['title']} · {q['stage']}")
    st.subheader(f"📝 최종 판단과 성찰일지")
    st.write(f"**문제:** {q['text']}")

    # 1. 비교 영역: 처음 생각 vs AI 대화 기록
    with st.container(border=True):
        st.markdown("##### 1) 처음에 내가 썼던 1차 생각")
        st.write(latest_answer["answer"])
        st.caption(f"작성 시각: {latest_answer['created_at'].replace('T', ' ')}")

    with st.expander(f"2) 소크라테스 AI와 나눈 대화 돌아보기 ({user_turns}턴)", expanded=False):
        if not logs:
            st.caption("아직 AI 대화 기록이 없습니다.")
        else:
            for row in logs:
                prefix = "🤖 **필로로그 AI**" if row["role"] == "assistant" else "🧑‍🎓 **나**"
                flag_badge = "  `📌 책과 다른 내용으로 표시됨`" if row["flagged_error"] else ""
                st.markdown(f"{prefix}{flag_badge}")
                st.write(row["content"])
                st.divider()

    # 2. 독립 판단 및 성찰 작성 폼 (AI 개입 없음)
    st.markdown("#### ✍️ 스스로 내리는 최종 판단")
    st.info(
        "이 단계에서는 **AI의 도움 없이** 스스로 결론을 정리합니다. "
        "AI의 표현을 그대로 옮기지 말고, 책의 근거와 내 말로 생각을 써 보세요."
    )

    change_keys = list(config.CHANGE_TYPE_LABELS.keys())
    default_change = latest_ref["changed_mind"] if latest_ref and latest_ref["changed_mind"] in change_keys else "수정"

    with st.form(f"reflection_form_{q['id']}"):
        changed_mind = st.radio(
            "AI와 대화한 뒤 처음 생각은 어떻게 달라졌나요?",
            options=change_keys,
            index=change_keys.index(default_change),
            format_func=lambda k: config.CHANGE_TYPE_LABELS[k],
        )
        final_text = st.text_area(
            "최종 판단과 그 이유 (처음 생각에서 바뀐 점이나 더 단단해진 근거를 함께 써 보세요)",
            value=latest_ref["content"] if latest_ref else "",
            height=200,
            placeholder="처음에는 ~라고 생각했지만, 책의 ~ 장면과 반대 입장을 다시 생각해 보니 최종적으로는 ~라고 판단한다. 왜냐하면...",
        )
        discussion_q = st.text_input(
            "💬 친구들과 함께 토론해 보고 싶은 나만의 질문 1개",
            value=latest_ref["discussion_question"] if latest_ref else "",
            placeholder="예: 만약 내가 주인공의 친구였다면 같은 선택을 응원했을까?",
        )
        submitted = st.form_submit_button("최종 판단·성찰일지 저장하기 💾", type="primary", use_container_width=True)

    if submitted:
        cleaned_final = final_text.strip()
        cleaned_dq = discussion_q.strip()
        if len(cleaned_final) < min_len:
            st.warning(f"최종 판단과 이유를 최소 {min_len}자 이상 적어 주세요. (지금 {len(cleaned_final)}자)")
        elif len(cleaned_dq) < 8:
            st.warning("친구들과 나눌 토론 질문을 8자 이상으로 한 문장 적어 주세요.")
        else:
            db.save_reflection(
                user_id=user_id,
                book_id=book["id"],
                question_id=q["id"],
                content=cleaned_final,
                changed_mind=changed_mind,
                discussion_question=cleaned_dq,
            )
            st.success("최종 판단과 성찰일지가 저장되었습니다!")
            latest_ref = db.get_latest_reflection(user_id, q["id"])

    # 3. 저장 완료 후 '나의 사고 변화 카드' 요약 표시
    if latest_ref:
        st.caption(f"마지막 저장: {latest_ref['created_at'].replace('T', ' ')}")
        st.divider()
        st.markdown("#### 🌱 나의 사고 변화 요약 카드")
        col_before, col_after = st.columns(2)
        with col_before:
            with st.container(border=True):
                st.markdown("**처음 생각 (1차 해석)**")
                st.write(latest_answer["answer"])
        with col_after:
            with st.container(border=True):
                st.markdown(f"**최종 판단 (`{latest_ref['changed_mind']}`)**")
                st.write(latest_ref["content"])
        if latest_ref["discussion_question"]:
            st.success(f"💬 **공동체 토론에 가져갈 내 질문:** {latest_ref['discussion_question']}")

        # 이 책 전체 성찰 완료 여부 체크
        reflected_ids = db.get_reflected_question_ids(user_id, book["id"])
        if len(reflected_ids) >= len(book["questions"]):
            st.balloons()
            st.success(f"🎉 『{book['title']}』의 모든 생각해볼 문제(4/4) 성찰을 완료했어요! 이제 친구들과 토론을 나눠 보세요.")

    st.divider()
    ids = [x["id"] for x in book["questions"]]
    idx = ids.index(q["id"])
    if idx + 1 < len(ids):
        if st.button("다음 문제로 →", use_container_width=True):
            go("question", question_id=ids[idx + 1])
            st.rerun()
