import json
import logging

import pytest

from rssapi.utils.nga import NGA_IMAGE_CDN_BASE_URL, NgaToolkit


def section_script(details: dict[str, object]) -> str:
    data = {"data": {"0": {"all": {"0": {"content": {"0": {"content": details}}}}}}}
    return "x" * 33 + json.dumps(data)


def test_parse_sections_preserves_normal_and_child_sections(caplog: pytest.LogCaptureFixture):
    script = section_script(
        {
            "normal": {"fid": 708, "name": "Normal", "info": "Description"},
            "child": {"fid": 708, "stid": 123, "name": "Child"},
            "string_id": {"fid": "456", "name": "String ID", "info": 42},
        }
    )

    result = NgaToolkit.parse_sections(script)

    assert [section.model_dump() for section in result.sections] == [
        {
            "fid": 708,
            "name": "Normal",
            "stid": None,
            "info": "Description",
            "icon": f"{NGA_IMAGE_CDN_BASE_URL}/proxy/cache_attach/ficon/708u.png",
        },
        {
            "fid": 708,
            "name": "Child",
            "stid": 123,
            "info": "None",
            "icon": f"{NGA_IMAGE_CDN_BASE_URL}/proxy/cache_attach/ficon/123u.png",
        },
        {
            "fid": 456,
            "name": "String ID",
            "stid": None,
            "info": "42",
            "icon": f"{NGA_IMAGE_CDN_BASE_URL}/proxy/cache_attach/ficon/456u.png",
        },
    ]
    assert not caplog.records


@pytest.mark.parametrize(
    "invalid_detail",
    [
        pytest.param({"stid": 29182350, "name": "/"}, id="reported-stid-only-entry"),
        pytest.param({}, id="empty-entry"),
        pytest.param(None, id="null-entry"),
        pytest.param("not an object", id="non-object-entry"),
        pytest.param({"fid": None, "name": "Null ID"}, id="null-fid"),
        pytest.param({"fid": "invalid", "name": "Invalid ID"}, id="invalid-fid"),
        pytest.param({"fid": 708}, id="missing-name"),
        pytest.param({"fid": 708, "name": None}, id="null-name"),
        pytest.param({"fid": 708, "name": ["Invalid"]}, id="invalid-name"),
        pytest.param({"fid": 708, "name": "Invalid child", "stid": "invalid"}, id="invalid-stid"),
    ],
)
def test_parse_sections_skips_invalid_entries(invalid_detail: object, caplog: pytest.LogCaptureFixture):
    script = section_script(
        {
            "before": {"fid": 708, "name": "Before"},
            "invalid": invalid_detail,
            "after": {"fid": 456, "stid": 123, "name": "After"},
        }
    )

    with caplog.at_level(logging.WARNING, logger="rssapi.utils.nga"):
        result = NgaToolkit.parse_sections(script)

    assert [(section.fid, section.stid, section.name) for section in result.sections] == [
        (708, None, "Before"),
        (456, 123, "After"),
    ]
    assert len(caplog.records) == 1
    assert "Skipped 1 invalid NGA section entries" in caplog.text


def test_parse_sections_summarizes_skipped_entries(caplog: pytest.LogCaptureFixture):
    script = section_script(
        {
            "valid": {"fid": 708, "name": "Normal"},
            "no_fid": {"stid": 29182350, "name": "/"},
            "no_name": {"fid": 456},
            "not_object": None,
        }
    )

    with caplog.at_level(logging.WARNING, logger="rssapi.utils.nga"):
        result = NgaToolkit.parse_sections(script)

    assert len(result.sections) == 1
    assert result.sections[0].fid == 708
    assert len(caplog.records) == 1
    assert "Skipped 3 invalid NGA section entries" in caplog.text


def test_parse_sections_accepts_empty_index(caplog: pytest.LogCaptureFixture):
    result = NgaToolkit.parse_sections("x" * 33 + '{"data":{"0":{"all":{}}}}')

    assert result.sections == []
    assert not caplog.records


@pytest.mark.parametrize(
    ("body", "error"),
    [
        pytest.param("not JSON", json.JSONDecodeError, id="invalid-json"),
        pytest.param("{}", KeyError, id="missing-data"),
        pytest.param('{"data":{"0":{}}}', KeyError, id="missing-index"),
        pytest.param('{"data":{"0":{"all":[]}}}', AttributeError, id="invalid-index-type"),
        pytest.param(
            '{"data":{"0":{"all":{"0":{"content":null}}}}}',
            AttributeError,
            id="invalid-content-type",
        ),
    ],
)
def test_parse_sections_does_not_hide_invalid_response_structure(body: str, error: type[Exception]):
    with pytest.raises(error):
        NgaToolkit.parse_sections("x" * 33 + body)
