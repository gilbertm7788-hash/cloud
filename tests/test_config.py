import pytest

from src.config import ConfigError, load_config

VALID = """
defaults: {timeout: 15, max_new_per_run: 5}
site:
  base_url: "https://ex.github.io/cloud/"
  title: "테스트"
sources:
  - id: a
    name: 소스A
    type: rss
    category: news
    rss: {url: "https://ex.com/rss.xml"}
  - id: b
    name: 소스B
    type: board
    category: committee
    enabled: false
    slots: [morning]
    board: {list_url: "https://ex.com/l", row_selector: "tr", fields: {}}
"""


def write(tmp_path, text):
    p = tmp_path / "sources.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_valid(tmp_path):
    cfg = load_config(write(tmp_path, VALID))
    assert len(cfg.sources) == 2
    a = cfg.sources[0]
    assert a.timeout == 15 and a.max_new_per_run == 5
    assert a.slots == ["evening", "morning", "noon"]  # 기본: 전체 슬롯(정렬)
    assert cfg.sources[1].enabled is False
    assert cfg.site.base_url == "https://ex.github.io/cloud"  # 후행 슬래시 제거
    assert cfg.site.title == "테스트"


def test_duplicate_id_rejected(tmp_path):
    text = VALID + """
  - id: a
    name: 중복
    type: rss
    category: news
    rss: {url: "https://ex.com/rss2.xml"}
"""
    with pytest.raises(ConfigError, match="중복"):
        load_config(write(tmp_path, text))


def test_unknown_type_rejected(tmp_path):
    text = """
sources:
  - {id: x, name: X, type: wat, category: news}
"""
    with pytest.raises(ConfigError, match="type"):
        load_config(write(tmp_path, text))


def test_unknown_slot_rejected(tmp_path):
    text = """
sources:
  - {id: x, name: X, type: rss, category: news, slots: [midnight], rss: {url: u}}
"""
    with pytest.raises(ConfigError, match="slot"):
        load_config(write(tmp_path, text))


def test_missing_required_field(tmp_path):
    with pytest.raises(ConfigError, match="category"):
        load_config(write(tmp_path, "sources:\n  - {id: x, name: X, type: rss}\n"))


def test_repo_config_is_valid():
    # 저장소에 실제로 커밋된 설정 파일이 스키마를 통과하는지
    cfg = load_config("config/sources.yaml")
    assert any(s.type == "rss" and s.enabled for s in cfg.sources)
    assert any(s.type == "narajangteo" for s in cfg.sources)
