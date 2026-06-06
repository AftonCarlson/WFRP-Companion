from __future__ import annotations

from pathlib import Path

from wfrp_companion.source_objects import layout


class FakePage:
    def __init__(self, words: list[tuple[object, ...]], blocks: list[tuple[object, ...]]):
        self.words = words
        self.blocks = blocks

    def get_text(self, mode: str) -> list[tuple[object, ...]]:
        if mode == "words":
            return self.words
        if mode == "blocks":
            return self.blocks
        raise AssertionError(f"unexpected mode: {mode}")


class FakeDocument:
    def __init__(self, pages: list[FakePage]):
        self.pages = pages
        self.closed = False

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int) -> FakePage:
        return self.pages[index]

    def close(self) -> None:
        self.closed = True


def test_load_pdf_layout_pages_returns_empty_for_missing_pdf(tmp_path: Path) -> None:
    assert layout.load_pdf_layout_pages(tmp_path / "missing.pdf", page_count=3) == ()


def test_load_pdf_layout_pages_uses_words_and_blocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf_path = tmp_path / "layout.pdf"
    pdf_path.write_bytes(b"%PDF synthetic placeholder")
    fake_document = FakeDocument(
        [
            FakePage(words=[(0, 0, 1, 1, "word")], blocks=[(0, 0, 1, 1, "block")]),
            FakePage(words=[], blocks=[]),
        ]
    )
    monkeypatch.setattr(layout, "open_pdf_document", lambda path: fake_document)

    pages = layout.load_pdf_layout_pages(pdf_path, page_count=5)

    assert pages == (
        layout.LayoutPage(
            page_number=1,
            has_word_geometry=True,
            word_count=1,
            block_count=1,
        ),
        layout.LayoutPage(
            page_number=2,
            has_word_geometry=False,
            word_count=0,
            block_count=0,
        ),
    )
    assert fake_document.closed is True


def test_load_pdf_layout_pages_falls_back_for_unreadable_pdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"not really a pdf")
    monkeypatch.setattr(
        layout,
        "open_pdf_document",
        lambda path: (_ for _ in ()).throw(RuntimeError("cannot open")),
    )

    assert layout.load_pdf_layout_pages(pdf_path, page_count=1) == ()


def test_open_pdf_document_uses_pymupdf(tmp_path: Path) -> None:
    import pymupdf

    pdf_path = tmp_path / "real.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Synthetic layout text")
    document.save(pdf_path)
    document.close()

    opened = layout.open_pdf_document(pdf_path)
    try:
        assert len(opened) == 1
    finally:
        opened.close()
