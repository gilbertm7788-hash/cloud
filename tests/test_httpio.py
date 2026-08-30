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


def test_redact_masks_generic_credential_params():
    leak = "403 Forbidden for url 'https://googleapis.com/v3/search?key=AIzaSyREAL123&part=x'"
    assert "AIzaSyREAL123" not in redact_secrets(leak)


def test_redact_masks_configured_secret_values():
    # 정규식이 모르는 형태(릴레이 호스트)도 값 자체로 마스킹돼야 함
    relay = "https://g2b-relay.acme.workers.dev"
    assert relay not in redact_secrets(f"500 for url '{relay}/1230000/x'", [relay])


def test_redact_ignores_short_values():
    assert redact_secrets("hello world", ["a", "xy"]) == "hello world"


def test_sid_is_not_stripped():
    # sid는 한국 게시판에서 글 식별자 — 제거하면 링크가 깨지고 dedup이 충돌한다
    assert "sid=12345" in normalize_url("https://molit.go.kr/b.do?sid=12345&id=7")


def test_mislabeled_charset_falls_back_to_meta():
    from src.httpio import decode_body
    raw = "<html><meta charset='euc-kr'><body>한국건설신문 위원 모집</body></html>".encode("cp949")
    assert "한국건설신문 위원 모집" in decode_body(raw, "utf-8", "auto")  # 헤더가 틀려도 meta로 복구
