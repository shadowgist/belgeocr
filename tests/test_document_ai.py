import json

import pytest
from pypdf import PdfReader

from belgeocr import ai, tables
from belgeocr.document import Document, build_pdf
from tests.conftest import make_text_image


def test_document_ops_and_undo(multi_page_pdf, text_png, tmp_path):
    doc = Document()
    doc.add_file(multi_page_pdf)
    doc.add_file(text_png)
    assert len(doc.pages) == 6
    doc.rotate([doc.pages[0]], -90)
    assert doc.pages[0].rotation == 270
    doc.delete(doc.pages[1:3])
    assert len(doc.pages) == 4
    doc.reorder(list(reversed(doc.pages)))
    out = build_pdf(doc.pages, tmp_path / "o.pdf")
    reader = PdfReader(str(out))
    assert len(reader.pages) == 4
    assert reader.pages[3].rotation == 270
    doc.undo()
    doc.undo()
    doc.undo()
    assert len(doc.pages) == 6 and doc.pages[0].rotation == 0


    img = make_text_image(size=(800, 400))
    assert img.size == (800, 400)


def test_merge_tables_rules():
    a = tables.Table.from_grid([["Ad", "No"], ["x", "1"]], page=0)
    b = tables.Table.from_grid([["Ad", "No"], ["y", "2"]], page=1)
    c = tables.Table.from_grid([["k", "l", "m"]], page=2)
    d = tables.Table.from_grid([["z", "3"]], page=4)
    merged = tables.merge_tables([a, b, c, d])
    assert [t.to_grid() for t in merged] == [
        [["Ad", "No"], ["x", "1"], ["y", "2"]],
        [["k", "l", "m"]],
        [["z", "3"]],
    ]
    assert merged[0].page_label == "1-2"
    assert a.to_grid() == [["Ad", "No"], ["x", "1"]]
    # second table on a page is not merged into the previous page's table
    e = tables.Table.from_grid([["q", "1"]], page=1)
    assert len(tables.merge_tables([a, e, b])) == 3 - 1


@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic"])
def test_ai_providers_request_and_parse(provider, monkeypatch):
    payload = {"text": "Merhaba dünya", "tables": [{"title": "T", "rows": [["A", "B"], ["1"]]}]}
    raw = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    responses = {
        "gemini": {"candidates": [{"content": {"parts": [{"text": raw}]}}]},
        "openai": {"choices": [{"message": {"content": raw}}]},
        "anthropic": {"content": [{"type": "text", "text": raw}]},
    }
    calls = []

    def fake_post(url, headers, body):
        calls.append((url, headers, body))
        return responses[provider]

    monkeypatch.setattr(ai, "_post", fake_post)
    result = ai.analyze_page(make_text_image(size=(600, 300)), ai.AiSettings(provider, "KEY"))
    assert result.text == "Merhaba dünya"
    assert result.tables == [[["A", "B"], ["1", ""]]]
    url, headers, body = calls[0]
    assert "KEY" in json.dumps(headers)
    assert ai.PROVIDERS[provider].default_model in url + json.dumps(body)


def test_ai_requires_key():
    with pytest.raises(ai.AiError):
        ai.analyze_page(make_text_image(size=(100, 100)), ai.AiSettings("gemini", ""))


def test_ai_bad_json(monkeypatch):
    monkeypatch.setattr(ai, "_post", lambda *a: {"choices": [{"message": {"content": "üzgünüm"}}]})
    with pytest.raises(ai.AiError):
        ai.analyze_page(make_text_image(size=(100, 100)), ai.AiSettings("openai", "k"))
