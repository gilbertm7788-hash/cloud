from src.httpio import normalize_url, redact_secrets


def test_normalize_removes_jsessionid_path_segment():
    url = "https://www.pps.go.kr/kor/board.do;jsessionid=ABC123?boardId=1"
    assert normalize_url(url) == "https://www.pps.go.kr/kor/board.do?boardId=1"


def test_normalize_removes_tracking_and_session_params():
    url = "https://ex.com/a?utm_source=x&id=3&fbclid=y&JSESSIONID=z"
    assert normalize_url(url) == "https://ex.com/a?id=3"


def test_normalize_sorts_query_and_drops_fragment():
    assert normalize_url("https://EX.com/p?b=2&a=1#frag") == "https://ex.com/p?a=1&b=2"


def test_normalize_same_article_different_sessions():
    a = "https://ex.com/view.do;jsessionid=AAA?id=9&utm_campaign=c"
    b = "https://ex.com/view.do;jsessionid=BBB?id=9"
    assert normalize_url(a) == normalize_url(b)


def test_redact_secrets():
    masked = redact_secrets("https://api?serviceKey=SECRET123&x=1 bot123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    assert "SECRET123" not in masked
    assert "AAAAAAAA" not in masked


def test_normalize_preserves_non_utf8_percent_encoding():
    # EUC-KR 퍼센트 인코딩(%C7%D1%B1%DB = "한글")이 왕복 손상 없이 보존돼야 함
    url = "https://ex.go.kr/OfrAction.do?title=%C7%D1%B1%DB&b=1"
    assert "%C7%D1%B1%DB" in normalize_url(url)


def test_normalize_rejects_non_http_schemes():
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("data:text/html,x") == ""
    assert normalize_url("ftp://ex.com/a") == ""


def test_normalize_keeps_blank_values():
    assert normalize_url("https://ex.com/p?a=&b=2") == "https://ex.com/p?a=&b=2"
