import pytest

from rssapi.utils.md import markdown_parse


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("# Title", "<h1>Title</h1>"),
        ("## Sub Title", "<h2>Sub Title</h2>"),
        ("### Third", "<h3>Third</h3>"),
        ("#### Fourth", "<h4>Fourth</h4>"),
        ("##### Fifth", "<h5>Fifth</h5>"),
        ("###### Sixth", "<h6>Sixth</h6>"),
    ],
    ids=["h1", "h2", "h3", "h4", "h5", "h6"],
)
def test_valid_headers_are_parsed(text: str, expected: str):
    assert markdown_parse(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#hashtag", "<p>#hashtag</p>"),
        ("#1 trending", "<p>#1 trending</p>"),
        ("##nosep", "<p>##nosep</p>"),
        ("#100DaysOfCode is fun", "<p>#100DaysOfCode is fun</p>"),
        ("###tagline", "<p>###tagline</p>"),
    ],
    ids=["hashtag", "numbered", "double-hash-no-space", "hashtag-sentence", "triple-hash-no-space"],
)
def test_hash_without_space_is_not_treated_as_header(text: str, expected: str):
    assert markdown_parse(text) == expected


def test_mixed_content_header_and_hashtag():
    text = "# Real Title\n\n#hashtag is not a header"
    assert markdown_parse(text) == "<h1>Real Title</h1>\n<p>#hashtag is not a header</p>"


def test_inline_markdown_features_unaffected():
    assert markdown_parse("**bold**") == "<p><strong>bold</strong></p>"
    assert markdown_parse("*italic*") == "<p><em>italic</em></p>"
    assert markdown_parse("[link](https://example.com)") == '<p><a href="https://example.com">link</a></p>'
    assert markdown_parse("`code`") == "<p><code>code</code></p>"


def test_multiline_with_headers_and_hashtags():
    text = "## Section\n\nSome text with #topic and more\n\n### Another Section"
    assert markdown_parse(text) == "<h2>Section</h2>\n<p>Some text with #topic and more</p>\n<h3>Another Section</h3>"


def test_plain_text_passthrough():
    assert markdown_parse("hello world") == "<p>hello world</p>"


def test_empty_string():
    assert markdown_parse("") == ""


def test_list_not_affected():
    assert markdown_parse("- item1\n- item2") == "<ul>\n<li>item1</li>\n<li>item2</li>\n</ul>"


def test_header_with_trailing_hashes():
    assert markdown_parse("## Title ##") == "<h2>Title</h2>"


def test_twitter_like_text_with_multiple_hashtags():
    text = "Just posted a photo #photography #sunset #nature"
    assert markdown_parse(text) == "<p>Just posted a photo #photography #sunset #nature</p>"


def test_header_after_paragraph():
    text = "Some intro text\n\n# Header Here\n\nMore text"
    assert markdown_parse(text) == "<p>Some intro text</p>\n<h1>Header Here</h1>\n<p>More text</p>"
