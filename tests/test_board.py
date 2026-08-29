from src.collectors.board import parse_list_page
from src.config import SourceConfig, apply_keyword_filters
from src.httpio import decode_body

BOARD_HTML = """
<html><body>
<table class="board">
  <tr><th>번호</th><th>제목</th><th>작성일</th></tr>
  <tr>
    <td>2</td>
    <td class="subject"><a href="view.asp?bidx=102&page=1">[창원시] 평가위원 모집 공고</a></td>
    <td class="date">2026-08-28</td>
  </tr>
  <tr>
    <td>1</td>
    <td class="subject"><a href="view.asp?bidx=101">기술자문위원회 위원 공개모집</a></td>
    <td class="date">2026.08.27</td>
  </tr>
</table>
</body></html>
"""

ONCLICK_HTML = """
<table><tr>
  <td><a href="#" onclick="fnView('555'); return false;">심의위원 모집</a></td>
</tr></table>
"""


def board_source(**board_overrides) -> SourceConfig:
    board = {
        "list_url": "https://ex.or.kr/not/list.asp?page={page}",
        "row_selector": "table tr:has(a)",
        "url_base": "https://ex.or.kr/not/",
        "id_pattern": r"bidx=(\d+)",
        "fields": {
            "title": {"selector": "td.subject a", "attr": "text"},
            "link": {"selector": "td.subject a", "attr": "href"},
            "date": {"selector": "td.date", "attr": "text"},
        },
    }
    board.update(board_overrides)
    return SourceConfig(id="b1", name="게시판", type="board", category="committee",
                        options=board)


def test_parse_list_page_basic():
    items = parse_list_page(BOARD_HTML, board_source(), "https://ex.or.kr/not/list.asp")
    assert len(items) == 2
    first = items[0]
    assert first.title == "[창원시] 평가위원 모집 공고"
    assert first.url == "https://ex.or.kr/not/view.asp?bidx=102&page=1"
    assert first.natural_key == "102"
    assert first.dedup_key == "board:b1:102"
    assert first.published_at is not None
    # 점 구분 날짜도 파싱
    assert items[1].published_at is not None


def test_parse_onclick_link_template():
    src = board_source(fields={
        "title": {"selector": "a", "attr": "text"},
        "link": {"selector": "a", "attr": "onclick",
                 "pattern": r"fnView\('(\d+)'\)",
                 "template": "https://ex.or.kr/view.do?id={value}"},
    }, id_pattern=r"id=(\d+)")
    items = parse_list_page(ONCLICK_HTML, src, "https://ex.or.kr/")
    assert len(items) == 1
    assert items[0].url == "https://ex.or.kr/view.do?id=555"
    assert items[0].natural_key == "555"


def test_euc_kr_decode_roundtrip():
    text = "<html><meta charset='euc-kr'><body>한글 게시판 제목</body></html>"
    raw = text.encode("cp949")
    assert "한글 게시판 제목" in decode_body(raw, None, "auto")
    assert "한글 게시판 제목" in decode_body(raw, "euc-kr", "auto")
    assert "한글 게시판 제목" in decode_body(raw, None, "cp949")


def test_keyword_filters():
    filters = {"keyword_include": ["위원", "모집"], "keyword_exclude": ["채용"]}
    assert apply_keyword_filters("평가위원 모집 공고", filters)
    assert not apply_keyword_filters("직원 채용 위원회", filters)  # exclude 우선
    assert not apply_keyword_filters("일반 공지", filters)
    assert apply_keyword_filters("아무 제목", {})  # 필터 없으면 통과


def test_declared_utf8_with_stray_byte_stays_utf8():
    # 선언 인코딩이 맞고 일부 바이트만 깨진 경우 — 전체를 cp949로 오판하지 않고
    # 선언 인코딩 + replace로 처리해 나머지 본문이 살아남아야 함
    good = "<html><body>건설 뉴스 제목입니다</body></html>".encode("utf-8")
    boundary = len("<html><body>건설".encode("utf-8"))  # 문자 경계에 삽입
    decoded = decode_body(good[:boundary] + b"\xff" + good[boundary:], "utf-8", "auto")
    assert "건설" in decoded
    assert "뉴스 제목입니다" in decoded
    assert "�" in decoded  # 깨진 바이트만 대체 문자로
