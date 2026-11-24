"""views/socratic_chat.py — 5단계: 소크라테스 AI 대화 화면"""
import streamlit as st

import catalog
import config
import db
import llm_client
import prompts
from views.state import go


def _build_api_history(logs: list[dict], first_answer: str) -> list[dict]:
    """DB 로그를 LLM API messages 형식으로 변환한다.

    DB의 첫 assistant 메시지 앞에 내부 트리거(user)를 붙여
    Gemini/OpenAI 모두 user → assistant 교대 규칙을 안전하게 지키도록 한다.
    """
    messages = [{"role": "user", "content": prompts.build_opening_user_trigger(first_answer)}]
    for row in logs:
        messages.append({"role": row["role"], "content": row["content"]})
    return messages


def show_chat() -> None:
    book = catalog.get_book(st.session_state.grade_id, st.session_state.book_id)
    q = catalog.get_question(st.session_state.grade_id, st.session_state.book_id, st.session_state.question_id)
    if book is None or q is None:
        go("book")
        st.rerun()

    user = st.session_state.user
    user_id = user["id"]
    reading_level = user.get("reading_level", "standard")
    level_label = config.READING_LEVELS.get(reading_level, "표준")

    # 설계원리 ①: 1차 해석이 저장되어 있지 않으면 4단계로 돌려보낸다
    latest_answer = db.get_latest_answer(user_id, q["id"])
    if latest_answer is None:
        st.warning("AI와 대화하기 전에 먼저 내 생각을 저장해 주세요.")
        go("question", question_id=q["id"])
        st.rerun()

    first_answer_text = latest_answer["answer"]
    preferred_provider = st.session_state.get("llm_provider", config.DEFAULT_LLM_PROVIDER)
    active_provider, active_model, fallback_notice = llm_client.resolve_provider(preferred_provider)

    # 상단 내비게이션
    nav_l, nav_r = st.columns(2)
    with nav_l:
        if st.button("← 내 생각 고치기", use_container_width=True):
            go("question", question_id=q["id"])
            st.rerun()
    with nav_r:
        if st.button("📚 생각해볼 문제 목록", use_container_width=True):
            go("book")
            st.rerun()

    st.caption(f"{book['title']} · {q['stage']}")
    st.subheader(f"🤖 {q['text']}")

    # 현재 모드 및 턴 상태 배지
    logs = db.get_chat_logs(user_id, q["id"])
    user_turns = sum(1 for row in logs if row["role"] == "user")
    max_turns = config.MAX_CHAT_TURNS
    provider_label = config.LLM_PROVIDERS.get(active_provider, active_provider)
    st.caption(
        f"엔진: **{provider_label}** (`{active_model}`)  |  "
        f"독해 수준: **{level_label}**  |  "
        f"대화 진행: **{user_turns} / {max_turns}턴**"
    )
    if fallback_notice:
        st.info(f"ℹ️ {fallback_notice} (실제 API를 쓰려면 `philologue/.env`에 키를 입력하세요.)")

    # 1차 해석 고정 비교 카드
    with st.expander("✏️ 내가 먼저 쓴 1차 생각 보기", expanded=True):
        st.write(first_answer_text)
        st.caption(f"작성 시각: {latest_answer['created_at'].replace('T', ' ')}")

    st.caption("🔒 대화창에 실명·학교·연락처 등 개인정보를 입력하지 마세요.")

    # 최초 진입 시 AI의 첫 소크라테스 질문 자동 생성
    if not logs:
        sys_prompt = prompts.build_system_prompt(
            book=book,
            question=q,
            first_answer=first_answer_text,
            reading_level=reading_level,
            turn_no=0,
            max_turns=max_turns,
        )
        opening_messages = [{"role": "user", "content": prompts.build_opening_user_trigger(first_answer_text)}]
        try:
            with st.spinner("소크라테스 AI가 내 생각을 읽고 첫 질문을 준비하고 있어요..."):
                reply, used_model, _ = llm_client.generate_socratic_reply(
                    system_prompt=sys_prompt,
                    messages=opening_messages,
                    preferred_provider=preferred_provider,
                    book=book,
                    question=q,
                    first_answer=first_answer_text,
                    reading_level=reading_level,
                    turn_no=0,
                    max_turns=max_turns,
                )
            db.save_chat_message(
                user_id=user_id,
                book_id=book["id"],
                question_id=q["id"],
                role="assistant",
                content=reply,
                turn_no=0,
                reading_level=reading_level,
                model_name=used_model,
            )
            st.rerun()
        except Exception as exc:
            st.error(f"AI 응답을 불러오지 못했습니다: {exc}")
            st.info("사이드바에서 **데모(모의) 모드**로 전환하면 API 키 없이도 바로 테스트할 수 있습니다.")
            return

    # 대화 내역 렌더링
    for row in logs:
        avatar = "🤖" if row["role"] == "assistant" else "🧑‍🎓"
        with st.chat_message(row["role"], avatar=avatar):
            st.write(row["content"])
            if row["role"] == "assistant":
                flagged = bool(row["flagged_error"])
                btn_label = "📌 책과 다른 내용으로 표시됨 (취소)" if flagged else "🔍 AI가 책과 다른 말을 했나요? (표시하기)"
                if st.button(btn_label, key=f"flag_{row['id']}", type="secondary"):
                    db.toggle_flag_error(row["id"], user_id)
                    st.rerun()

    # 입력창 또는 대화 종료 안내
    if user_turns >= max_turns:
        st.success(
            f"이 문항의 소크라테스 대화({max_turns}턴)를 마쳤어요! "
            "이제 아래 버튼을 눌러 AI 도움 없이 최종 판단과 성찰일지를 정리해 보세요."
        )
    else:
        user_input = st.chat_input("책의 장면이나 이유를 떠올리며 내 생각을 적어 보세요...")
        if user_input and user_input.strip():
            cleaned = user_input.strip()
            next_turn = user_turns + 1
            sys_prompt = prompts.build_system_prompt(
                book=book,
                question=q,
                first_answer=first_answer_text,
                reading_level=reading_level,
                turn_no=next_turn,
                max_turns=max_turns,
            )
            api_messages = _build_api_history(logs, first_answer_text)
            api_messages.append({"role": "user", "content": cleaned})
            try:
                with st.spinner("소크라테스 AI가 다음 질문을 생각하고 있어요..."):
                    reply, used_model, _ = llm_client.generate_socratic_reply(
                        system_prompt=sys_prompt,
                        messages=api_messages,
                        preferred_provider=preferred_provider,
                        book=book,
                        question=q,
                        first_answer=first_answer_text,
                        reading_level=reading_level,
                        turn_no=next_turn,
                        max_turns=max_turns,
                    )
                db.save_chat_message(
                    user_id=user_id,
                    book_id=book["id"],
                    question_id=q["id"],
                    role="user",
                    content=cleaned,
                    turn_no=next_turn,
                    reading_level=reading_level,
                    model_name="",
                )
                db.save_chat_message(
                    user_id=user_id,
                    book_id=book["id"],
                    question_id=q["id"],
                    role="assistant",
                    content=reply,
                    turn_no=next_turn,
                    reading_level=reading_level,
                    model_name=used_model,
                )
                st.rerun()
            except Exception as exc:
                st.error(f"AI 응답 생성 중 오류가 발생했습니다: {exc}")
                st.info("사이드바에서 **데모(모의) 모드**로 전환하거나 API 키/네트워크 상태를 확인해 주세요.")

    st.divider()
    # 6단계 성찰일지로 이동 (최소 1턴 이상 대화 후 활성화)
    can_reflect = user_turns >= 1
    if st.button(
        "📝 최종 판단·성찰일지 쓰기 →",
        type="primary",
        use_container_width=True,
        disabled=not can_reflect,
    ):
        go("reflection", question_id=q["id"])
        st.rerun()
    if not can_reflect:
        st.caption("소크라테스 AI의 질문에 최소 1번 이상 답한 뒤 최종 판단을 정리할 수 있어요.")

    # 다음 문제 이동 및 교사/연구자용 시스템 프롬프트 확인
    ids = [x["id"] for x in book["questions"]]
    idx = ids.index(q["id"])
    if idx + 1 < len(ids):
        if st.button("다음 문제로 →", use_container_width=True):
            go("question", question_id=ids[idx + 1])
            st.rerun()

    with st.expander("🔍 교사·연구자 확인용: 현재 적용된 소크라테스 프롬프트 보기", expanded=False):
        preview_prompt = prompts.build_system_prompt(
            book=book,
            question=q,
            first_answer=first_answer_text,
            reading_level=reading_level,
            turn_no=user_turns,
            max_turns=max_turns,
        )
        st.code(preview_prompt, language="text")
