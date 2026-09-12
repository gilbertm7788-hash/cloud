import time

import pytest

from src import robots


@pytest.fixture(autouse=True)
def _clear():
    robots.reset_cache()
    yield
    robots.reset_cache()


def _stub(monkeypatch, body: bytes | None, *, fail: bool = False):
    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        if fail:
            raise RuntimeError("연결 실패")
        return body, "utf-8"

    monkeypatch.setattr(robots, "fetch_bytes", fake_fetch)
    return calls


def test_disallowed_path_is_blocked(monkeypatch):
    _stub(monkeypatch, b"User-agent: *\nDisallow: /board/\n")
    assert robots.can_fetch("https://ex.com/board/list.jsp") is False
    assert robots.can_fetch("https://ex.com/news/1") is True


def test_missing_robots_means_allowed(monkeypatch):
    _stub(monkeypatch, None, fail=True)
    assert robots.can_fetch("https://ex.com/board/list.jsp") is True


def test_unparseable_robots_means_allowed(monkeypatch):
    _stub(monkeypatch, b"\xff\xfe not a robots file at all")
    assert robots.can_fetch("https://ex.com/anything") is True


def test_robots_fetched_once_per_host(monkeypatch):
    calls = _stub(monkeypatch, b"User-agent: *\nDisallow:\n")
    for path in ("/a", "/b", "/c"):
        robots.can_fetch(f"https://ex.com{path}")
    assert calls == ["https://ex.com/robots.txt"]


def test_hosts_are_cached_separately(monkeypatch):
    calls = _stub(monkeypatch, b"User-agent: *\nDisallow:\n")
    robots.can_fetch("https://a.com/x")
    robots.can_fetch("https://b.com/x")
    assert calls == ["https://a.com/robots.txt", "https://b.com/robots.txt"]


def test_crawl_delay_is_honored_and_capped(monkeypatch):
    _stub(monkeypatch, b"User-agent: *\nCrawl-delay: 999\n")
    robots.can_fetch("https://ex.com/x")  # 파서 캐시 채우기
    assert robots.crawl_delay("https://ex.com/x") == robots.MAX_DELAY


def test_crawl_delay_defaults_when_unspecified(monkeypatch):
    _stub(monkeypatch, b"User-agent: *\nDisallow:\n")
    robots.can_fetch("https://ex.com/x")
    assert robots.crawl_delay("https://ex.com/x") == robots.DEFAULT_DELAY


def test_wait_for_host_spaces_requests(monkeypatch):
    _stub(monkeypatch, b"User-agent: *\nCrawl-delay: 0.05\n")
    robots.can_fetch("https://ex.com/x")
    start = time.monotonic()
    robots.wait_for_host("https://ex.com/a")  # 첫 요청은 대기 없음
    robots.wait_for_host("https://ex.com/b")  # 두 번째는 간격만큼 대기
    assert time.monotonic() - start >= 0.05


def test_wait_is_per_host(monkeypatch):
    _stub(monkeypatch, b"User-agent: *\nCrawl-delay: 5\n")
    robots.can_fetch("https://a.com/x")
    robots.can_fetch("https://b.com/x")
    start = time.monotonic()
    robots.wait_for_host("https://a.com/1")
    robots.wait_for_host("https://b.com/1")  # 다른 호스트라 대기 없음
    assert time.monotonic() - start < 1.0
