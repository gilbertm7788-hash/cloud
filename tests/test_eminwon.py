from src.collectors.eminwon import parse_list_html
from src.config import SourceConfig

HTML = """
<table>
<tr><td><a href="#" onclick="searchDetail(123456); return false;">건설기술심의위원회 위원 공개모집</a></td></tr>
<tr><td><a href="#" onclick="searchDetail(123457)">일반 고시공고</a></td></tr>
<tr><td><a href="#" onclick="searchDetail(123456)">중복 링크</a></td></tr>
<tr><td><a href="/other">무관한 링크</a></td></tr>
</table>
"""


def src() -> SourceConfig:
    return SourceConfig(id="emw1", name="기장군", type="eminwon", category="committee",
                        options={"host": "eminwon.gijang.go.kr"})


def test_parse_list_html():
    items = parse_list_html(HTML, src(), "eminwon.gijang.go.kr")
    assert len(items) == 2  # 중복·무관 링크 제외
    first = items[0]
    assert first.natural_key == "123456"
    assert first.dedup_key == "emw:eminwon.gijang.go.kr:123456"
    assert "eminwon.gijang.go.kr" in first.url
    assert "123456" in first.url
