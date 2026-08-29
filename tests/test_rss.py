from src.collectors.rss import parse_feed
from src.config import SourceConfig

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Test Feed</title>
<item>
  <title>건설 뉴스 1</title>
  <link>https://www.ikld.kr/news/articleView.html?idxno=12345</link>
  <description>&lt;p&gt;요약 &lt;b&gt;본문&lt;/b&gt;&lt;/p&gt;</description>
  <pubDate>Fri, 28 Aug 2026 09:00:00 +0900</pubDate>
</item>
<item>
  <title>건설 뉴스 2</title>
  <link>https://www.ikld.kr/news/articleView.html?idxno=12346</link>
</item>
</channel></rss>
""".encode("utf-8")


def rss_source() -> SourceConfig:
    return SourceConfig(
        id="ikld", name="국토일보", type="rss", category="news",
        options={"url": "https://www.ikld.kr/rss/allArticle.xml",
                 "id_pattern": r"idxno=(\d+)"},
    )


def test_parse_feed_extracts_idxno_and_strips_html():
    items = parse_feed(RSS_XML, rss_source())
    assert len(items) == 2
    assert items[0].natural_key == "12345"
    assert items[0].dedup_key == "rss:ikld:12345"
    assert items[0].summary == "요약 본문"
    assert items[0].published_at is not None
    assert items[1].natural_key == "12346"


def test_parse_feed_bozo_with_entries_ok():
    # 약간 깨진 XML이라도 엔트리가 있으면 수용
    broken = RSS_XML.replace(b"</rss>", b"")  # noqa: 약간 깨진 XML
    items = parse_feed(broken, rss_source())
    assert len(items) == 2
