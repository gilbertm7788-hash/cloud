from datetime import date

from src.deadline import extract_deadline, parse_deadline_str

TODAY = date(2026, 8, 29)


def test_full_date_pattern():
    assert extract_deadline("접수기간: 2026.9.15까지", today=TODAY) == date(2026, 9, 15)
    assert extract_deadline("~2026-09-15 마감", today=TODAY) == date(2026, 9, 15)
    assert extract_deadline("2026년 9월 15일 마감", today=TODAY) == date(2026, 9, 15)


def test_range_takes_last_date():
    assert extract_deadline("접수 2026.8.20 ~ 2026.9.15", today=TODAY) == date(2026, 9, 15)


def test_tilde_pattern_without_year():
    assert extract_deadline("위원 모집 (~9.15)", today=TODAY) == date(2026, 9, 15)
    assert extract_deadline("모집공고 ~ 9/15", today=TODAY) == date(2026, 9, 15)


def test_kkaji_pattern():
    assert extract_deadline("9월 15일까지 접수", today=TODAY) == date(2026, 9, 15)
    assert extract_deadline("9.15.까지", today=TODAY) == date(2026, 9, 15)


def test_year_rollover():
    # 12월 말 기준 "~1.10"은 다음 해로 추정
    assert extract_deadline("모집 ~1.10", today=date(2026, 12, 20)) == date(2027, 1, 10)


def test_no_deadline():
    assert extract_deadline("위원회 모집 공고", today=TODAY) is None
    assert extract_deadline("", today=TODAY) is None


def test_invalid_date_ignored():
    assert extract_deadline("~13.45 어쩌구", today=TODAY) is None


def test_parse_deadline_str():
    assert parse_deadline_str("2026-09-15 17:00") == date(2026, 9, 15)
    assert parse_deadline_str("2026.9.15") == date(2026, 9, 15)
    assert parse_deadline_str("") is None
    assert parse_deadline_str("미정") is None


def test_tilde_after_year_start_date_wins():
    # 기간 표기: 연도 있는 시작일이 아니라 뒤의 마감 표기를 잡아야 함
    assert extract_deadline("접수 2026.8.20 시작, ~9.15", today=TODAY) == date(2026, 9, 15)
    assert extract_deadline("공고일 2026.8.20 / 9월 15일까지 접수", today=TODAY) == date(2026, 9, 15)


def test_invalid_year_date_falls_through():
    assert extract_deadline("문서번호 2026.99.99 / ~9.15", today=TODAY) == date(2026, 9, 15)
