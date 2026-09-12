import pytest

from src.topics import DEFAULT_TOPIC, classify, topic_order


@pytest.mark.parametrize("title,expected", [
    ("국토부, 건설기술 진흥법 시행령 개정안 입법예고", "정책·제도"),
    ("재개발·재건축 공사비 검증 과태료 신설 추진", "정책·제도"),
    ("1조원대 마천5구역 재개발…현대건설 수주 참여 검토", "수주·계약"),
    ("금호건설, 563억 킨텍스 주차복합빌딩 수주", "수주·계약"),
    ("HD현대중공업, 차세대 발전엔진과 SMR에 1조 투자", "플랜트·에너지"),
    ("서해선 복선전철 교량 상부공 착공", "수주·계약"),
    ("GTX-B 노선 터널 굴착 본격화", "토목·인프라"),
    ("목동윤슬자이 견본주택 3일 오픈", "건축·주택"),
    ("중대재해처벌법 시행 이후 건설현장 사고 감소", "안전·품질"),
    ("스마트건설 기술 아이디어 공모전 시상", "기술·디지털"),
    ("건설기술인協, 한국실내건축가협회와 업무협약 체결", "수주·계약"),
    ("건설업계 하반기 채용 동향", DEFAULT_TOPIC),
])
def test_classification(title, expected):
    assert classify(title) == expected


def test_empty_title_falls_back():
    assert classify("") == DEFAULT_TOPIC
    assert classify(None or "") == DEFAULT_TOPIC


def test_rule_order_is_priority():
    """정책 신호가 있으면 공종 키워드가 있어도 정책으로 간다."""
    assert classify("국토부, 도로 설계기준 개정") == "정책·제도"


def test_topic_order_ends_with_default():
    order = topic_order()
    assert order[-1] == DEFAULT_TOPIC
    assert len(order) == len(set(order))
