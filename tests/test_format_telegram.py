from src.format_telegram import escape_html, split_blocks


def test_escape_html():
    assert escape_html("<b> & 'x'") == "&lt;b&gt; &amp; 'x'"


def test_escape_html_quotes():
    """href 속성 안에 들어가므로 큰따옴표도 반드시 이스케이프되어야 한다."""
    assert escape_html('a "b"') == "a &quot;b&quot;"


def test_split_blocks_never_cuts_a_block():
    blocks = [f"줄{i} " + "x" * 100 for i in range(100)]
    msgs = split_blocks(blocks, limit=1000)
    assert all(len(m) <= 1000 for m in msgs)
    joined = "\n".join(msgs)
    for b in blocks:
        assert b in joined
