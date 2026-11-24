"""views/teacher.py — 7단계: 교사·연구자 대시보드 및 연구용 익명 CSV 추출

설계 근거:
- 논문 IV장(교사와 AI의 역할 분담): 교사는 AI 대화 로그 표본 점검, 오독 검증,
  수준별 비계 배정, 공동체 토론 촉진을 책임진다.
- 근거자료집 7~8번: 익명 참여번호(S001...) 부여, 1차 해석·AI 대화·최종 성찰문 수집,
  질적 코딩 작업지(AI 질문 Q1~Q5/QX/QR + 학생 응답 E0~E3) 추출을 지원한다.
"""
import csv
import io
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

import catalog
import charts
import config
import db
from views.state import go


def _to_csv_bytes(rows: list[dict], fieldnames: list[str]) -> bytes:
    """Excel에서 한글이 깨지지 않도록 UTF-8 BOM(utf-8-sig) CSV 바이트로 변환한다."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig")


def _book_label(book_id: str) -> str:
    grade, book = catalog.get_book_by_id(book_id)
    if grade and book:
        return f"[{grade['name']}] {book['title']}"
    return book_id


def _question_label(question_id: str) -> str:
    _, book, q = catalog.get_question_by_id(question_id)
    if book and q:
        return f"{book['title']} · ({q['stage']}) {q['text']}"
    return question_id


STAGES_ORDER = ("해석", "근거·추론", "반론·평가", "나와 연결하기")

STAGE_PEDAGOGY_FOCUS = {
    "해석": "텍스트의 핵심 개념·상징과 인물의 의도를 스스로 언어화하는 초기 의미 구성 단계",
    "근거·추론": "본문의 구체적 장면·표현을 인용하고 주장과 논리적으로 연결하는 텍스트 근거 검증 단계",
    "반론·평가": "숨은 전제와 대안 관점·반례를 검토하며 최초 판단의 타당성을 점검·수정하는 비판적 사고 핵심 단계",
    "나와 연결하기": "텍스트의 쟁점을 자신의 경험과 오늘날 사회·AI 맥락으로 확장해 주체적 판단으로 통합하는 성찰 단계",
}


def _stage_score(recs: list[dict], use_final: bool) -> float:
    """특정 사고 단계 레코드 집합을 0~100 지수로 정규화한다(레이더 차트용)."""
    if not recs:
        return 0.0
    lens = [r["final_len"] if use_final else r["answer_len"] for r in recs]
    avg_len = sum(lens) / len(lens)
    # 분량 충실도(최대 60점, 140자 기준 만점) + 사고 변화·대화 참여 반영(최대 40점)
    len_part = min(60.0, (avg_len / 140.0) * 60.0)
    if not use_final:
        return round(min(100.0, len_part + 20.0), 1)
    shift_rate = sum(1 for r in recs if r["changed_mind"] in ("수정", "확장")) / len(recs)
    turn_avg = sum(r["user_turns"] for r in recs) / len(recs)
    depth_part = min(22.0, shift_rate * 22.0) + min(18.0, (turn_avg / 3.0) * 18.0)
    return round(min(100.0, len_part + depth_part), 1)


def _build_radar_series(records: list[dict], mode: str) -> tuple[list[str], list[dict]]:
    axes = ["1. 해석", "2. 근거·추론", "3. 반론·평가", "4. 나와 연결하기", "대화 깊이", "비판적 점검"]

    def extra_axes(sub: list[dict]) -> tuple[float, float]:
        if not sub:
            return 0.0, 0.0
        avg_turns = sum(r["user_turns"] for r in sub) / len(sub)
        depth_score = round(min(100.0, (avg_turns / 3.0) * 100.0), 1)
        flag_rate = sum(r["flagged_cnt"] for r in sub) / len(sub)
        # 문항당 15% 내외 오류 점검을 100점 척도로 가시화 + 수정/확장 반영
        shift_rate = sum(1 for r in sub if r["changed_mind"] in ("수정", "확장")) / len(sub)
        audit_score = round(min(100.0, shift_rate * 55.0 + min(45.0, flag_rate * 300.0)), 1)
        return depth_score, audit_score

    if mode == "전후 비교 (1차 해석 vs 최종 판단)":
        before_vals = [_stage_score([r for r in records if r["stage"] == s], False) for s in STAGES_ORDER]
        after_vals = [_stage_score([r for r in records if r["stage"] == s], True) for s in STAGES_ORDER]
        d_sc, a_sc = extra_axes(records)
        before_vals += [round(d_sc * 0.45, 1), round(a_sc * 0.4, 1)]
        after_vals += [d_sc, a_sc]
        return axes, [
            {"name": "1차 해석 (AI 대화 전)", "color": "#5470C6", "values": before_vals},
            {"name": "최종 판단 (AI 대화 후)", "color": "#73C0DE", "values": after_vals},
        ]

    # 독해 수준별 비교 (기초 / 표준 / 심화)
    level_styles = [
        ("basic", "기초 수준", "#91CC75"),
        ("standard", "표준 수준", "#5470C6"),
        ("advanced", "심화 수준", "#EE6666"),
    ]
    series = []
    for lv_key, lv_name, color in level_styles:
        sub = [r for r in records if r["reading_level"] == lv_key]
        if not sub:
            continue
        vals = [_stage_score([r for r in sub if r["stage"] == s], True) for s in STAGES_ORDER]
        d_sc, a_sc = extra_axes(sub)
        vals += [d_sc, a_sc]
        series.append({"name": lv_name, "color": color, "values": vals})
    return axes, series


def _build_sunburst_tree(records: list[dict]) -> list[dict]:
    palettes = [
        ("초등학교", "#5CB3F6", "#8CCBF8", "#CBE7FD"),
        ("중학교", "#73D2B6", "#9CE2CE", "#D3F4EA"),
        ("고등학교", "#F4B96B", "#F8CE96", "#FCE7C9"),
    ]
    tree = []
    for lv_ko, c1, c2, c3 in palettes:
        lv_recs = [r for r in records if r["school_level_ko"] == lv_ko]
        if not lv_recs:
            continue
        stage_nodes = []
        for stg in STAGES_ORDER:
            s_recs = [r for r in lv_recs if r["stage"] == stg]
            if not s_recs:
                continue
            chg_nodes = []
            for chg in ("유지", "수정", "확장"):
                cnt = sum(1 for r in s_recs if r["changed_mind"] == chg)
                if cnt > 0:
                    chg_nodes.append({"name": chg, "value": cnt})
            if chg_nodes:
                stage_nodes.append({"name": stg, "children": chg_nodes})
        if stage_nodes:
            tree.append(
                {"name": lv_ko, "color": c1, "mid_color": c2, "outer_color": c3, "children": stage_nodes}
            )
    return tree


def _render_stage_deep_analysis(records: list[dict], stage: str, stage_num: int) -> None:
    """4대 사고 단계 중 1개 단계에 대한 정량 지표·자동 해석 리포트·시각화·우수 사례를 출력한다."""
    sub = [r for r in records if r["stage"] == stage]
    if not sub:
        st.info(f"{stage_num}. {stage} 단계의 응답 데이터가 아직 없습니다.")
        return

    n = len(sub)
    avg_a = round(sum(r["answer_len"] for r in sub) / n, 1)
    avg_f = round(sum(r["final_len"] for r in sub) / n, 1)
    growth = round(((avg_f - avg_a) / avg_a) * 100, 1) if avg_a > 0 else 0.0
    avg_t = round(sum(r["user_turns"] for r in sub) / n, 2)
    keep = sum(1 for r in sub if r["changed_mind"] == "유지")
    mod = sum(1 for r in sub if r["changed_mind"] == "수정")
    ext = sum(1 for r in sub if r["changed_mind"] == "확장")
    shift_pct = round(((mod + ext) / n) * 100, 1)
    flags = sum(r["flagged_cnt"] for r in sub)

    st.caption(f"단계 교육 목표: {STAGE_PEDAGOGY_FOCUS[stage]}")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("분석 문항 수", f"{n}건")
    k2.metric("1차 → 최종 평균 분량", f"{avg_f}자", delta=f"{growth:+.1f}% (1차 {avg_a}자)")
    k3.metric("평균 AI 대화 턴", f"{avg_t}턴")
    k4.metric("사고 변화율(수정+확장)", f"{shift_pct}%", delta=f"유지 {keep} · 수정 {mod} · 확장 {ext}")

    # 수준별·학교급별 핵심 통계 산출
    lv_summary = []
    for lv_key, lv_ko in (("basic", "기초"), ("standard", "표준"), ("advanced", "심화")):
        ls = [r for r in sub if r["reading_level"] == lv_key]
        if ls:
            la = round(sum(r["answer_len"] for r in ls) / len(ls), 1)
            lf = round(sum(r["final_len"] for r in ls) / len(ls), 1)
            lg = round(((lf - la) / la) * 100, 1) if la > 0 else 0.0
            lshift = round(sum(1 for r in ls if r["changed_mind"] in ("수정", "확장")) / len(ls) * 100, 1)
            lv_summary.append(
                {
                    "독해 수준": lv_ko,
                    "문항 수": len(ls),
                    "1차 평균(자)": la,
                    "최종 평균(자)": lf,
                    "분량 변화(%)": lg,
                    "사고 변화율(%)": lshift,
                }
            )

    sch_summary = []
    for sch_ko in ("초등학교", "중학교", "고등학교"):
        ss = [r for r in sub if r["school_level_ko"] == sch_ko]
        if ss:
            sch_summary.append(
                {
                    "학교급": sch_ko,
                    "유지": sum(1 for r in ss if r["changed_mind"] == "유지"),
                    "수정": sum(1 for r in ss if r["changed_mind"] == "수정"),
                    "확장": sum(1 for r in ss if r["changed_mind"] == "확장"),
                }
            )

    # 자동 작성 심층 분석 서술문
    dominant = max((("유지", keep), ("수정", mod), ("확장", ext)), key=lambda x: x[1])[0]
    top_growth_lv = max(lv_summary, key=lambda x: x["분량 변화(%)"]) if lv_summary else None
    growth_desc = (
        f"1차 해석 평균 **{avg_a}자**에서 AI 소크라테스 문답 후 최종 판단 평균 **{avg_f}자**로 **{growth:+.1f}%** 변화했습니다."
    )
    lv_desc = (
        f" 독해 수준별로는 **{top_growth_lv['독해 수준']} 집단**에서 1차 대비 최종 분량 변화가 **{top_growth_lv['분량 변화(%)']:+.1f}%**로 가장 두드러졌습니다."
        if top_growth_lv
        else ""
    )
    flag_desc = (
        f" 또한 이 단계에서 학생이 AI 발화의 원문 일치 여부를 점검해 오류로 표시한 사례가 **{flags}건** 기록되었습니다."
        if flags > 0
        else " 이 단계에서는 학생이 보고한 AI 환각·오류 의심 사례가 0건으로 안정적이었습니다."
    )
    with st.container(border=True):
        st.markdown(f"##### 📝 {stage_num}. {stage} 단계 자동 분석 요약")
        st.write(
            f"• **분량·구체화 추이**: 총 {n}개 응답에서 {growth_desc}{lv_desc}\n\n"
            f"• **사고 변화 패턴**: 전체의 **{shift_pct}%**({mod + ext}/{n}건)에서 기존 생각의 **수정({mod}건)** 또는 **확장({ext}건)**이 나타났으며, "
            f"가장 지배적인 변화 유형은 **`{dominant}`**입니다. 평균 대화 턴 수는 **{avg_t}턴**입니다.\n\n"
            f"• **비판적 AI 활용 점검**:{flag_desc}"
        )

    # 단계별 시각화 차트 2종
    vc1, vc2 = st.columns(2)
    with vc1:
        st.markdown(f"**[{stage}] 독해 수준별 1차 vs 최종 평균 분량(자)**")
        if lv_summary:
            st.bar_chart(lv_summary, x="독해 수준", y=["1차 평균(자)", "최종 평균(자)"])
    with vc2:
        st.markdown(f"**[{stage}] 학교급별 생각 변화 유형(유지·수정·확장)**")
        if sch_summary:
            st.bar_chart(sch_summary, x="학교급", y=["유지", "수정", "확장"])

    # 대표 사고 변화 사례 2건 (수정/확장 우선 + 분량 증가폭 순)
    featured = sorted(
        sub,
        key=lambda r: (1 if r["changed_mind"] in ("수정", "확장") else 0, r["final_len"] - r["answer_len"]),
        reverse=True,
    )[:2]
    with st.expander(f"🌱 [{stage}] 대표 사고 변화 사례 보기 ({len(featured)}건)", expanded=False):
        for ex in featured:
            st.markdown(
                f"**{ex['anon_id']} ({ex['nickname']})** · `{ex['school_level_ko']}` · "
                f"『{ex['book_title']}』 · 수준 `{config.READING_LEVELS.get(ex['reading_level'], ex['reading_level'])}` · "
                f"변화 **`{ex['changed_mind']}`**"
            )
            c_a, c_b = st.columns(2)
            with c_a:
                st.caption(f"1차 해석 ({ex['answer_len']}자)")
                st.write(ex["answer"])
            with c_b:
                st.caption(f"최종 판단 ({ex['final_len']}자 · 대화 {ex['user_turns']}턴)")
                st.write(ex["final_judgment"])
            st.divider()


def show_dashboard() -> None:
    user = st.session_state.user
    if not user or user.get("role") != "teacher":
        st.error("교사·연구자 계정만 접근할 수 있는 화면입니다.")
        go("grades")
        st.rerun()

    st.title("👩‍🏫 교사·연구자 대시보드")
    st.caption(f"학생 활동 감독 · 독해 수준 조정 · AI 오류 점검 · 연구용 익명 데이터 추출  |  저장소: **{db.get_db_status_label()}**")

    students = db.list_students_with_stats()
    flagged_logs = db.get_flagged_chat_logs()
    discussions = db.get_latest_discussion_questions()

    # 상단 요약 지표
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("참여 학생", f"{len(students)}명")
    m2.metric("1차 작성 문항", f"{sum(s['answered_q'] for s in students)}건")
    m3.metric("AI 대화 턴", f"{sum(s['user_turns'] for s in students)}턴")
    m4.metric("성찰 완료 / 오류 표시", f"{sum(s['reflected_q'] for s in students)}건 / {len(flagged_logs)}건")

    tab_students, tab_review, tab_compare, tab_audit, tab_export = st.tabs(
        [
            "👥 학생·수준 관리",
            "🔎 학생 사고 과정 열람",
            "📈 학생 비교·통계 분석",
            "📌 오류 점검 · 토론 질문",
            "📊 연구용 CSV 내보내기",
        ]
    )

    # ---------- 탭 1: 학생 현황 및 독해 수준 관리 ----------
    with tab_students:
        st.subheader("참여 학생 현황")
        if not students:
            st.info("아직 가입한 학생 계정이 없습니다.")
        else:
            table_rows = [
                {
                    "익명번호": s["anon_id"],
                    "별명": s["nickname"],
                    "아이디": s["username"],
                    "독해 수준": config.READING_LEVELS.get(s["reading_level"], s["reading_level"]),
                    "약속 동의": "완료" if s["pledge_agreed"] else "미완료",
                    "1차 작성(문항)": s["answered_q"],
                    "AI 대화(턴)": s["user_turns"],
                    "성찰 완료(문항)": s["reflected_q"],
                    "오류 표시": s["flagged_cnt"],
                }
                for s in students
            ]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("독해 수준(비계 난이도) 조정")
            st.caption("사전 독해 검사나 대화 수행에 따라 학생별 AI 질문 비계 수준(기초·표준·심화)을 배정합니다.")
            stu_map = {f"{s['anon_id']} · {s['nickname']} ({s['username']})": s for s in students}
            selected_label = st.selectbox("수준을 조정할 학생 선택", list(stu_map.keys()), key="lvl_stu_sel")
            target = stu_map[selected_label]
            level_keys = list(config.READING_LEVELS.keys())
            cur_lv = target["reading_level"] if target["reading_level"] in level_keys else "standard"

            col_l, col_btn = st.columns([3, 1])
            with col_l:
                new_lv = st.selectbox(
                    "적용할 독해 수준",
                    options=level_keys,
                    index=level_keys.index(cur_lv),
                    format_func=lambda k: f"{config.READING_LEVELS[k]} ({k})",
                    key="lvl_val_sel",
                )
            with col_btn:
                st.write("")
                st.write("")
                if st.button("수준 저장", type="primary", use_container_width=True):
                    db.update_reading_level(target["id"], new_lv)
                    st.success(f"{target['nickname']}({target['anon_id']}) 학생의 독해 수준을 '{config.READING_LEVELS[new_lv]}'(으)로 변경했습니다.")
                    st.rerun()

    # ---------- 탭 2: 학생별 사고 과정(1차 생각 → AI 대화 → 최종 판단) 열람 ----------
    with tab_review:
        st.subheader("학생별 사고 변화 열람 (1차 해석 → AI 문답 → 최종 판단)")
        if not students:
            st.info("열람할 학생 기록이 없습니다.")
        else:
            stu_map = {f"{s['anon_id']} · {s['nickname']} ({s['username']})": s for s in students}
            sel_stu_label = st.selectbox("학생 선택", list(stu_map.keys()), key="rev_stu_sel")
            sel_stu = stu_map[sel_stu_label]
            q_list = db.get_student_questions_summary(sel_stu["id"])

            if not q_list:
                st.info("이 학생은 아직 작성한 답안이나 대화 기록이 없습니다.")
            else:
                q_map = {
                    f"{_question_label(item['question_id'])}  [1차 {item['answer_revs']}회 · 대화 {item['user_turns']}턴 · 성찰 {item['reflection_revs']}회]": item
                    for item in q_list
                }
                sel_q_label = st.selectbox("문항 선택", list(q_map.keys()), key="rev_q_sel")
                sel_item = q_map[sel_q_label]
                qid = sel_item["question_id"]

                ans_hist = db.get_answer_history(sel_stu["id"], qid)
                chat_hist = db.get_chat_logs(sel_stu["id"], qid)
                ref_hist = db.get_reflection_history(sel_stu["id"], qid)

                c1, c2 = st.columns(2)
                with c1:
                    with st.container(border=True):
                        st.markdown("##### ✏️ 1차 해석 (AI 대화 전)")
                        if not ans_hist:
                            st.caption("기록 없음")
                        else:
                            st.write(ans_hist[-1]["answer"])
                            st.caption(f"최신 저장: {ans_hist[-1]['created_at'].replace('T', ' ')} (총 {len(ans_hist)}회 저장)")
                            if len(ans_hist) > 1:
                                with st.expander(f"이전 수정 이력 보기 ({len(ans_hist) - 1}건)"):
                                    for idx, old in enumerate(ans_hist[:-1], start=1):
                                        st.markdown(f"**{idx}차** ({old['created_at'].replace('T', ' ')})")
                                        st.write(old["answer"])
                with c2:
                    with st.container(border=True):
                        st.markdown("##### 📝 최종 판단 및 성찰일지")
                        if not ref_hist:
                            st.caption("아직 성찰일지를 작성하지 않았습니다.")
                        else:
                            latest_r = ref_hist[-1]
                            st.markdown(f"**생각 변화:** `{latest_r['changed_mind']}`")
                            st.write(latest_r["content"])
                            if latest_r["discussion_question"]:
                                st.success(f"💬 **토론 질문:** {latest_r['discussion_question']}")
                            st.caption(f"최신 저장: {latest_r['created_at'].replace('T', ' ')} (총 {len(ref_hist)}회 저장)")

                st.markdown(f"##### 🤖 소크라테스 AI 대화 로그 (학생 발화 {sel_item['user_turns']}턴)")
                if not chat_hist:
                    st.caption("아직 AI 대화 기록이 없습니다.")
                else:
                    for row in chat_hist:
                        who = "🤖 **AI**" if row["role"] == "assistant" else f"🧑‍🎓 **{sel_stu['nickname']}**"
                        meta = f"`{row['model_name']}`" if row["model_name"] else ""
                        flag = "  `📌 책과 다른 내용 표시됨`" if row["flagged_error"] else ""
                        with st.container(border=True):
                            st.markdown(f"{who} (턴 {row['turn_no']} · 수준 {config.READING_LEVELS.get(row['reading_level'], row['reading_level'])}) {meta}{flag}")
                            st.write(row["content"])
                            st.caption(row["created_at"].replace("T", " "))

    # ---------- 탭 3: 학생 비교·통계 분석 ----------
    with tab_compare:
        st.subheader("📈 참여 학생 비교·통계 분석")
        st.caption("선택한 학생들의 1차 해석→AI 대화→최종 판단 변화량, 학교급·사고 단계별 분포, 동일 문항 1:1 비교를 수행합니다.")

        if not students:
            st.info("분석할 학생 데이터가 아직 없습니다.")
        else:
            stu_opt_map = {f"{s['anon_id']} · {s['nickname']} ({s['username']})": s for s in students}
            selected_labels = st.multiselect(
                "분석할 학생 선택",
                options=list(stu_opt_map.keys()),
                default=list(stu_opt_map.keys()),
                key="cmp_stu_multi",
            )
            if not selected_labels:
                st.warning("분석할 학생을 1명 이상 선택해 주세요.")
            else:
                sel_ids = [stu_opt_map[lb]["id"] for lb in selected_labels]
                records = db.get_comparison_records(sel_ids)

                # 각 레코드에 학교급·사고 단계 메타데이터 보강
                for r in records:
                    g, b, q = catalog.get_question_by_id(r["question_id"])
                    lv = catalog.infer_school_level(g)
                    r["school_level_ko"] = config.SCHOOL_LEVEL_LABELS.get(lv, lv)
                    r["stage"] = q["stage"] if q else ""
                    r["book_title"] = b["title"] if b else r["book_id"]

                # 1) 학생별 핵심 지표 요약표
                by_user: dict[int, list[dict]] = {}
                for r in records:
                    by_user.setdefault(r["user_id"], []).append(r)

                summary_rows = []
                len_chart_data: dict[str, dict[str, float]] = {}
                change_chart_data: dict[str, dict[str, int]] = {}

                for lb in selected_labels:
                    s = stu_opt_map[lb]
                    recs = by_user.get(s["id"], [])
                    books_cnt = len({r["book_id"] for r in recs})
                    ans_lens = [r["answer_len"] for r in recs if r["answer_len"] > 0]
                    ref_lens = [r["final_len"] for r in recs if r["final_len"] > 0]
                    avg_ans = round(sum(ans_lens) / len(ans_lens), 1) if ans_lens else 0.0
                    avg_ref = round(sum(ref_lens) / len(ref_lens), 1) if ref_lens else 0.0
                    growth_pct = round(((avg_ref - avg_ans) / avg_ans) * 100, 1) if avg_ans > 0 else 0.0
                    total_turns = sum(r["user_turns"] for r in recs)
                    avg_turns = round(total_turns / len(recs), 2) if recs else 0.0
                    cnt_keep = sum(1 for r in recs if r["changed_mind"] == "유지")
                    cnt_mod = sum(1 for r in recs if r["changed_mind"] == "수정")
                    cnt_ext = sum(1 for r in recs if r["changed_mind"] == "확장")
                    ref_total = cnt_keep + cnt_mod + cnt_ext
                    shift_rate = round(((cnt_mod + cnt_ext) / ref_total) * 100, 1) if ref_total else 0.0
                    flags = sum(r["flagged_cnt"] for r in recs)

                    label_short = f"{s['anon_id']}({s['username']})"
                    summary_rows.append(
                        {
                            "익명번호": s["anon_id"],
                            "아이디(별명)": f"{s['username']} ({s['nickname']})",
                            "독해 수준": config.READING_LEVELS.get(s["reading_level"], s["reading_level"]),
                            "참여 도서": books_cnt,
                            "완료 문항": ref_total,
                            "1차 평균(자)": avg_ans,
                            "최종 평균(자)": avg_ref,
                            "글자수 변화(%)": growth_pct,
                            "평균 대화(턴)": avg_turns,
                            "유지": cnt_keep,
                            "수정": cnt_mod,
                            "확장": cnt_ext,
                            "사고 변화율(%)": shift_rate,
                            "오류 점검": flags,
                        }
                    )
                    len_chart_data[label_short] = {"1차 해석 평균(자)": avg_ans, "최종 판단 평균(자)": avg_ref}
                    change_chart_data[label_short] = {"유지": cnt_keep, "수정": cnt_mod, "확장": cnt_ext}

                st.markdown("##### 1) 학생별 사고 변화 핵심 지표 비교")
                st.dataframe(summary_rows, use_container_width=True, hide_index=True)

                # 분석 요약 CSV 다운로드 (익명화)
                anon_summary_rows = [
                    {
                        "anon_id": row["익명번호"],
                        "reading_level": row["독해 수준"],
                        "books_count": row["참여 도서"],
                        "reflected_questions": row["완료 문항"],
                        "avg_first_answer_chars": row["1차 평균(자)"],
                        "avg_final_judgment_chars": row["최종 평균(자)"],
                        "char_growth_pct": row["글자수 변화(%)"],
                        "avg_chat_turns": row["평균 대화(턴)"],
                        "mind_keep": row["유지"],
                        "mind_modify": row["수정"],
                        "mind_expand": row["확장"],
                        "mind_shift_rate_pct": row["사고 변화율(%)"],
                        "flagged_errors": row["오류 점검"],
                    }
                    for row in summary_rows
                ]
                stamp = datetime.now().strftime("%Y%m%d_%H%M")
                st.download_button(
                    "📥 학생 비교 분석 요약 CSV 다운로드",
                    data=_to_csv_bytes(anon_summary_rows, list(anon_summary_rows[0].keys())),
                    file_name=f"philologue_student_comparison_{stamp}.csv",
                    mime="text/csv",
                )

                # 2) 기본 막대 차트 2종
                ch1, ch2 = st.columns(2)
                with ch1:
                    st.markdown("##### 2) 1차 해석 vs 최종 판단 평균 분량(자)")
                    chart_rows_1 = [
                        {"학생": k, "1차 해석 평균(자)": v["1차 해석 평균(자)"], "최종 판단 평균(자)": v["최종 판단 평균(자)"]}
                        for k, v in len_chart_data.items()
                    ]
                    st.bar_chart(chart_rows_1, x="학생", y=["1차 해석 평균(자)", "최종 판단 평균(자)"])
                with ch2:
                    st.markdown("##### 3) 학생별 생각 변화 유형(유지·수정·확장)")
                    chart_rows_2 = [
                        {"학생": k, "유지": v["유지"], "수정": v["수정"], "확장": v["확장"]}
                        for k, v in change_chart_data.items()
                    ]
                    st.bar_chart(chart_rows_2, x="학생", y=["유지", "수정", "확장"])

                # 2-B) 신규 인터랙티브 시각화 차트 2종 (레이더 차트 + 선버스트 차트)
                st.divider()
                st.markdown("##### 4) 다차원 역량 레이더 차트 & 계층별 선버스트 차트")
                radar_mode = st.radio(
                    "레이더 차트 비교 기준",
                    options=["전후 비교 (1차 해석 vs 최종 판단)", "독해 수준별 비교 (기초 vs 표준 vs 심화)"],
                    horizontal=True,
                    key="radar_mode_radio",
                )
                viz_l, viz_r = st.columns(2)
                with viz_l:
                    r_axes, r_series = _build_radar_series(records, radar_mode)
                    radar_html = charts.build_radar_chart_html(
                        title=f"필로로그 AI 6대 역량 레이더 ({radar_mode})",
                        axes=r_axes,
                        series=r_series,
                        max_val=100.0,
                        height=440,
                    )
                    components.html(radar_html, height=450)
                with viz_r:
                    sb_tree = _build_sunburst_tree(records)
                    sb_html = charts.build_sunburst_chart_html(
                        title="학교급 › 사고 단계 › 생각 변화 선버스트 분포",
                        tree=sb_tree,
                        height=440,
                    )
                    components.html(sb_html, height=450)

                # 3) 학교급별 · 사고 단계별 전체 집계표
                st.divider()
                col_lv, col_st = st.columns(2)
                with col_lv:
                    st.markdown("##### 5) 학교급별 참여·변화 요약")
                    lv_rows = []
                    for lv_ko in ("초등학교", "중학교", "고등학교"):
                        sub = [r for r in records if r["school_level_ko"] == lv_ko]
                        if sub:
                            a_avg = round(sum(r["answer_len"] for r in sub) / len(sub), 1)
                            f_avg = round(sum(r["final_len"] for r in sub) / len(sub), 1)
                            lv_rows.append(
                                {
                                    "학교급": lv_ko,
                                    "문항 수": len(sub),
                                    "1차 평균(자)": a_avg,
                                    "최종 평균(자)": f_avg,
                                    "유지/수정/확장": f"{sum(1 for r in sub if r['changed_mind']=='유지')}/"
                                                    f"{sum(1 for r in sub if r['changed_mind']=='수정')}/"
                                                    f"{sum(1 for r in sub if r['changed_mind']=='확장')}",
                                }
                            )
                    st.dataframe(lv_rows, use_container_width=True, hide_index=True)

                with col_st:
                    st.markdown("##### 6) 사고 단계별 참여·변화 요약")
                    st_rows = []
                    for stg in STAGES_ORDER:
                        sub = [r for r in records if r["stage"] == stg]
                        if sub:
                            a_avg = round(sum(r["answer_len"] for r in sub) / len(sub), 1)
                            f_avg = round(sum(r["final_len"] for r in sub) / len(sub), 1)
                            st_rows.append(
                                {
                                    "사고 단계": stg,
                                    "문항 수": len(sub),
                                    "1차 평균(자)": a_avg,
                                    "최종 평균(자)": f_avg,
                                    "유지/수정/확장": f"{sum(1 for r in sub if r['changed_mind']=='유지')}/"
                                                    f"{sum(1 for r in sub if r['changed_mind']=='수정')}/"
                                                    f"{sum(1 for r in sub if r['changed_mind']=='확장')}",
                                }
                            )
                    st.dataframe(st_rows, use_container_width=True, hide_index=True)

                # 3-B) 4대 사고 단계별 개별 심층 분석 & 시각화
                st.divider()
                st.markdown("##### 🎯 4대 사고 단계별 개별 심층 분석 및 시각화")
                st_tabs = st.tabs(["1. 해석", "2. 근거·추론", "3. 반론·평가", "4. 나와 연결하기"])
                for idx_s, (s_tab, stg_name) in enumerate(zip(st_tabs, STAGES_ORDER), start=1):
                    with s_tab:
                        _render_stage_deep_analysis(records, stg_name, idx_s)

                # 4) 동일 문항 학생 비교기
                st.divider()
                st.markdown("##### 🤝 동일 문항 학생 답변 비교")
                if len(sel_ids) < 2:
                    st.info("2명 이상의 학생을 선택하면 공통으로 응답한 문항을 나란히 비교할 수 있습니다.")
                else:
                    # 2명 이상이 함께 응답한 문항(최소 2명 교집합) 모두 표시
                    q_counts: dict[str, list[dict]] = {}
                    for lb in selected_labels:
                        s = stu_opt_map[lb]
                        for r in by_user.get(s["id"], []):
                            q_counts.setdefault(r["question_id"], []).append((s, r))
                    shared_qids = sorted(qid for qid, lst in q_counts.items() if len(lst) >= 2)
                    if not shared_qids:
                        st.info("선택한 학생들 중 2명 이상이 공통으로 응답한 문항이 아직 없습니다.")
                    else:
                        common_map = {
                            f"{_question_label(qid)} ({len(q_counts[qid])}명 참여)": qid for qid in shared_qids
                        }
                        chosen_q_label = st.selectbox(
                            f"공통 문항 선택 (2명 이상 참여 문항 {len(shared_qids)}개)",
                            options=list(common_map.keys()),
                            key="cmp_common_q",
                        )
                        chosen_qid = common_map[chosen_q_label]
                        participants = q_counts[chosen_qid]
                        cols = st.columns(min(3, len(participants)))
                        for p_idx, (s, rec) in enumerate(participants):
                            with cols[p_idx % len(cols)]:
                                with st.container(border=True):
                                    lv_txt = config.READING_LEVELS.get(s["reading_level"], s["reading_level"])
                                    st.markdown(f"**{s['anon_id']} · {s['nickname']} (`{s['username']}`)**")
                                    st.caption(f"독해 수준: {lv_txt} · 대화 {rec['user_turns']}턴 · 변화: {rec['changed_mind'] or '미작성'}")
                                    st.markdown("**✏️ 1차 해석**")
                                    st.write(rec["answer"] or "(없음)")
                                    st.markdown("**📝 최종 판단**")
                                    st.write(rec["final_judgment"] or "(미작성)")
                                    if rec["discussion_question"]:
                                        st.success(f"💬 {rec['discussion_question']}")

    # ---------- 탭 4: AI 오류 점검 & 공동체 토론 질문 모아보기 ----------
    with tab_audit:
        st.subheader("📌 학생이 표시한 AI 오류·환각 의심 로그")
        st.caption("교사가 원문과 대조해 AI 오독 여부를 최종 검증하고 프롬프트/맥락을 보완하는 영역입니다.")
        if not flagged_logs:
            st.success("현재 오류로 표시된 AI 응답이 없습니다.")
        else:
            for item in flagged_logs:
                with st.container(border=True):
                    st.markdown(
                        f"**{item['anon_id']} ({item['nickname']})** · {_question_label(item['question_id'])}"
                    )
                    st.write(item["content"])
                    st.caption(
                        f"모델: {item['model_name'] or '미기록'} · 턴 {item['turn_no']} · {item['created_at'].replace('T', ' ')}"
                    )

        st.divider()
        st.subheader("💬 공동체 토론 질문 모아보기 (4단계 수업 활용)")
        st.caption("학생들이 성찰일지에서 만든 토론 질문을 도서별로 모아 교실 토론 발제로 활용할 수 있습니다.")
        if not discussions:
            st.info("아직 학생들이 등록한 토론 질문이 없습니다.")
        else:
            book_ids = sorted({d["book_id"] for d in discussions})
            book_options = ["전체 도서"] + book_ids
            chosen_bid = st.selectbox(
                "도서 필터",
                options=book_options,
                format_func=lambda x: x if x == "전체 도서" else _book_label(x),
                key="disc_book_filter",
            )
            filtered = discussions if chosen_bid == "전체 도서" else [d for d in discussions if d["book_id"] == chosen_bid]
            for d in filtered:
                with st.container(border=True):
                    st.markdown(f"**💬 {d['discussion_question']}**")
                    st.caption(
                        f"작성자: {d['anon_id']} ({d['nickname']}) · {_book_label(d['book_id'])} · 생각 변화: {d['changed_mind']} · {d['created_at'].replace('T', ' ')}"
                    )

    # ---------- 탭 4: 연구용 익명 CSV 다운로드 ----------
    with tab_export:
        st.subheader("📊 연구 분석용 익명 데이터 내보내기")
        st.info(
            "모든 파일은 **학생 계정(`role='student'`)만 포함**하며, 아이디와 별명을 제거하고 "
            "**익명 참여번호(`S001`, `S002`…)**로 자동 변환합니다. (Excel 한글 호환 UTF-8 BOM CSV)"
        )
        datasets = db.export_anonymized_datasets()
        stamp = datetime.now().strftime("%Y%m%d_%H%M")

        export_specs = [
            (
                "1) 1차 해석 전체 (answers)",
                f"philologue_answers_{stamp}.csv",
                datasets["answers"],
                ["record_id", "anon_id", "reading_level", "book_id", "question_id", "char_len", "answer", "created_at"],
                "학생이 AI 대화 전에 작성한 1차 해석과 수정 이력 전체",
            ),
            (
                "2) AI 대화 로그 전체 (chat_logs)",
                f"philologue_chat_logs_{stamp}.csv",
                datasets["chat_logs"],
                ["log_id", "anon_id", "book_id", "question_id", "turn_no", "role", "reading_level", "model_name", "flagged_error", "content", "created_at"],
                "턴별 AI 발문·학생 응답·사용 모델·독해 수준·오류 표시 로그 전체",
            ),
            (
                "3) 최종 판단·성찰일지 전체 (reflections)",
                f"philologue_reflections_{stamp}.csv",
                datasets["reflections"],
                ["record_id", "anon_id", "reading_level", "book_id", "question_id", "changed_mind", "char_len", "final_judgment", "discussion_question", "created_at"],
                "AI 개입 없이 작성한 최종 판단, 생각 변화 유형(유지/수정/확장), 토론 질문",
            ),
            (
                "4) 질적 코딩 작업지 (근거자료집 8번 Q·E 코딩용)",
                f"philologue_coding_sheet_QE_{stamp}.csv",
                datasets["coding_pairs"],
                [
                    "anon_id", "book_id", "question_id", "pair_no", "reading_level", "model_name",
                    "flagged_error", "ai_question", "student_response",
                    "ai_code_Q1_Q5_QX_QR", "student_code_E0_E3", "coder_memo",
                ],
                "AI 질문 1개 + 직후 학생 응답 1개 페어링 시트 (Q1~Q5/QX/QR, E0~E3 빈 코딩 열 포함)",
            ),
        ]

        for title, fname, rows, cols, desc in export_specs:
            with st.container(border=True):
                left, right = st.columns([3, 1])
                with left:
                    st.markdown(f"**{title}** (`{len(rows)}행`)")
                    st.caption(desc)
                with right:
                    st.download_button(
                        "CSV 다운로드 ⬇️",
                        data=_to_csv_bytes(rows, cols),
                        file_name=fname,
                        mime="text/csv",
                        use_container_width=True,
                        key=f"dl_{fname}",
                    )
