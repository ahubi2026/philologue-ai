"""config.py — 필로로그 AI 공통 설정 및 상수 (.env 및 Streamlit Secrets 통합 지원)"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
BOOKS_PATH = DATA_DIR / "books.json"
DB_PATH = DATA_DIR / "philologue.db"

# 로컬 개발 시 philologue/.env 자동 로드 (없어도 안전하게 무시됨)
load_dotenv(BASE_DIR / ".env")


def get_setting(key: str, default: str = "") -> str:
    """OS 환경변수(.env) → Streamlit Cloud Secrets 순으로 설정값을 안전하게 읽는다."""
    env_val = os.getenv(key)
    if env_val is not None and env_val.strip() != "":
        return env_val.strip()
    try:
        import streamlit as st

        if key in st.secrets:
            val = st.secrets[key]
            if val is not None and str(val).strip() != "":
                return str(val).strip()
    except Exception:
        pass
    return default


# 데이터베이스 설정: DATABASE_URL이 있으면 클라우드 PostgreSQL(Supabase), 없으면 로컬 SQLite
DATABASE_URL = get_setting("DATABASE_URL", "")

# 사고 단계별 표시 색 (books.json의 question.stage 값과 일치)
STAGE_COLOR = {
    "해석": "blue",
    "근거·추론": "green",
    "반론·평가": "orange",
    "나와 연결하기": "violet",
}

# 학교급별 표시명 및 순서
SCHOOL_LEVEL_LABELS = {
    "elementary": "초등학교",
    "middle": "중학교",
    "high": "고등학교",
}

# 학교급별 1차 해석 최소 글자 수 (학년 발달 수준 반영)
MIN_ANSWER_LEN = {
    "elementary": 20,
    "middle": 30,
    "high": 50,
}
DEFAULT_MIN_ANSWER_LEN = 30

# 5단계 소크라테스 AI 대화 설정
MAX_CHAT_TURNS = int(get_setting("PHILOLOGUE_MAX_TURNS", "8"))

# 7단계 교사·연구자 계정 가입용 초대 코드
TEACHER_ACCESS_CODE = get_setting("PHILOLOGUE_TEACHER_CODE", "teacher2026")

# LLM 제공자 설정 (Gemini / OpenAI 전환 + API 키 없을 때 데모 모드)
LLM_PROVIDERS = {
    "gemini": "Gemini API",
    "openai": "OpenAI API",
    "demo": "데모(모의) 모드",
}
DEFAULT_LLM_PROVIDER = get_setting("PHILOLOGUE_LLM_PROVIDER", "gemini").lower()
if DEFAULT_LLM_PROVIDER not in LLM_PROVIDERS:
    DEFAULT_LLM_PROVIDER = "gemini"

GEMINI_API_KEY = get_setting("GEMINI_API_KEY", "")
GEMINI_MODEL = get_setting("GEMINI_MODEL", "gemini-flash-lite-latest")

OPENAI_API_KEY = get_setting("OPENAI_API_KEY", "")
OPENAI_MODEL = get_setting("OPENAI_MODEL", "gpt-4o-mini")

LLM_TIMEOUT_SECONDS = int(get_setting("PHILOLOGUE_LLM_TIMEOUT", "30"))

# 독해 수준 정의 (연구문제 3: 수준별 질문·비계 조정)
READING_LEVELS = {
    "basic": "기초",
    "standard": "표준",
    "advanced": "심화",
}

# 6단계 성찰일지 생각 변화 유형 (근거자료집 8번 판단 변화 분석 대응)
CHANGE_TYPE_LABELS = {
    "유지": "처음 생각을 유지했어요 (근거가 더 단단해졌어요)",
    "수정": "처음 생각을 일부 수정했어요",
    "확장": "새로운 관점으로 생각이 넓어졌어요",
}

# Streamlit session_state 초기값
SESSION_DEFAULTS = {
    "user": None,
    "page": "grades",
    "grade_id": None,
    "book_id": None,
    "question_id": None,
    "llm_provider": DEFAULT_LLM_PROVIDER,
}
