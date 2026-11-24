"""views/auth.py — 0~2단계: 로그인, 회원가입, AI 사용 약속(사전 준비)"""
import streamlit as st

import config
import db
from views.state import go, set_logged_in_session


def show_login() -> None:
    st.title("📖 필로로그 AI")
    st.caption("읽고, 철학적으로 묻고, 스스로 판단하다")

    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("아이디")
            password = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("로그인", use_container_width=True)
        if submitted:
            user = db.verify_user(username, password)
            if user:
                set_logged_in_session(user)
                start_page = "teacher" if user.get("role") == "teacher" else "grades"
                go(start_page, grade_id=None, book_id=None, question_id=None)
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

    with tab_signup:
        st.info("진짜 이름 대신 **별명(닉네임)**을 써 주세요. 비밀번호는 다른 사람이 볼 수 없도록 안전하게 보관합니다.")
        with st.form("signup_form", clear_on_submit=False):
            new_id = st.text_input("아이디 (영문·숫자·밑줄 4~20자)")
            nickname = st.text_input("별명 (화면에 표시될 이름, 1~10자)")
            pw1 = st.text_input("비밀번호 (6자 이상)", type="password")
            pw2 = st.text_input("비밀번호 확인", type="password")
            with st.expander("👩‍🏫 교사·연구자 계정으로 가입하기 (학생은 비워 두세요)"):
                teacher_code = st.text_input("교사 초대 코드", type="password")
            signup = st.form_submit_button("회원가입", use_container_width=True)
        if signup:
            if pw1 != pw2:
                st.error("비밀번호와 비밀번호 확인이 다릅니다.")
            elif teacher_code.strip() and teacher_code.strip() != config.TEACHER_ACCESS_CODE:
                st.error("교사 초대 코드가 올바르지 않습니다.")
            else:
                role = "teacher" if teacher_code.strip() == config.TEACHER_ACCESS_CODE else "student"
                ok, msg = db.create_user(new_id, nickname, pw1, role=role)
                if ok and role == "teacher":
                    u = db.verify_user(new_id, pw1)
                    if u:
                        db.set_pledge_agreed(u["id"])
                    msg = "교사·연구자 회원가입이 완료되었습니다. 로그인해 주세요."
                (st.success if ok else st.error)(msg)


def show_pledge() -> None:
    """0단계(사전 준비): 최초 로그인 시 AI 한계와 사용 규칙을 확인한다."""
    user = st.session_state.user
    st.title("🧭 필로로그 AI 사용 약속")
    st.write(f"**{user['nickname']}** 님, 소크라테스 AI와 함께 읽기 전에 세 가지 약속을 확인해 주세요.")

    with st.container(border=True):
        c1 = st.checkbox("1. AI와 대화하기 전에 책을 직접 읽고 **내 생각을 먼저** 적겠습니다.")
        c2 = st.checkbox("2. AI는 정답을 알려주는 선생님이 아니며, **책에 없는 내용을 틀리게 말할 수도 있음**을 알고 원문과 대조하겠습니다.")
        c3 = st.checkbox("3. 대화창에 내 **실명·학교·연락처 등 개인정보를 입력하지 않겠습니다.**")

    if st.button("약속하고 시작하기 →", type="primary", use_container_width=True, disabled=not (c1 and c2 and c3)):
        db.set_pledge_agreed(user["id"])
        st.session_state.user["pledge_agreed"] = True
        go("grades")
        st.rerun()
