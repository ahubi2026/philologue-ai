"""catalog.py — 도서·문항 메타데이터(books.json) 로딩 및 조회"""
import json

import streamlit as st

import config


@st.cache_data
def load_books() -> dict:
    with open(config.BOOKS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_grades() -> list:
    return load_books().get("grades", [])


def get_grade(grade_id: str | None) -> dict | None:
    if not grade_id:
        return None
    return next((g for g in get_grades() if g["id"] == grade_id), None)


def get_book(grade_id: str | None, book_id: str | None) -> dict | None:
    grade = get_grade(grade_id)
    if grade is None or not book_id:
        return None
    return next((b for b in grade["books"] if b["id"] == book_id), None)


def get_question(grade_id: str | None, book_id: str | None, question_id: str | None) -> dict | None:
    book = get_book(grade_id, book_id)
    if book is None or not question_id:
        return None
    return next((q for q in book["questions"] if q["id"] == question_id), None)


def infer_school_level(grade: dict | None) -> str:
    """학년 객체에서 학교급('elementary'/'middle'/'high')을 판별한다."""
    if not grade:
        return "middle"
    if "school_level" in grade:
        return grade["school_level"]
    gid = grade.get("id", "")
    if gid.startswith("e"):
        return "elementary"
    if gid.startswith("h"):
        return "high"
    return "middle"


def get_min_answer_len(grade_id: str | None) -> int:
    level = infer_school_level(get_grade(grade_id))
    return config.MIN_ANSWER_LEN.get(level, config.DEFAULT_MIN_ANSWER_LEN)


def get_book_by_id(book_id: str | None) -> tuple[dict | None, dict | None]:
    """book_id만으로 (grade, book)을 찾는다 (교사 대시보드·CSV 내보내기용)."""
    if not book_id:
        return None, None
    for g in get_grades():
        for b in g["books"]:
            if b["id"] == book_id:
                return g, b
    return None, None


def get_question_by_id(question_id: str | None) -> tuple[dict | None, dict | None, dict | None]:
    """question_id만으로 (grade, book, question)을 찾는다."""
    if not question_id:
        return None, None, None
    for g in get_grades():
        for b in g["books"]:
            for q in b["questions"]:
                if q["id"] == question_id:
                    return g, b, q
    return None, None, None
