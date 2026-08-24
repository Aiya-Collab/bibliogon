from pathlib import Path

from app.services.distillation.parser import parse_text


MATERIALS = Path(r"E:\Desktop\小说")


def test_utf8_bom_is_removed_and_bracket_heading_is_supported():
    result = parse_text("\ufeff【第1章 开始】\n正文\n第1章 开始\n重复正文".encode("utf-8"), "book.txt")
    assert result.encoding_detected == "utf-8"
    assert result.chapters[0].title == "【第1章 开始】"
    assert len(result.chapters) == 1
    assert not result.raw_text.startswith("\ufeff")


def test_numeric_quoted_heading_without_space_is_supported():
    result = parse_text('1."想要成为轻小说女主角的美少女"\n正文', "book.txt")
    assert len(result.chapters) == 1


def test_real_materials_have_expected_heading_detection():
    files = list(MATERIALS.glob("*.txt"))
    assert len(files) == 4
    for path in files:
        result = parse_text(path.read_bytes(), path.name)
        assert result.raw_text and result.chapters
        assert not result.raw_text.startswith("\ufeff")


def test_double_marked_heading_does_not_duplicate_adjacent_chapters():
    result = parse_text("【第1章 开始】\nA\n第1章 开始\nB\n第2章 继续\nC", "book.txt")
    assert [chapter.title for chapter in result.chapters] == ["【第1章 开始】", "第2章 继续"]
