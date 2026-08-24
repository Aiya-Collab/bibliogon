import re
from pathlib import Path
from dataclasses import dataclass


@dataclass
class DistillationChapter:
    index: int
    title: str
    text: str
    start_offset: int
    end_offset: int


@dataclass
class DistillationInput:
    raw_text: str
    source_format: str
    source_filename: str
    encoding_detected: str
    chapters: list[DistillationChapter]


CHAPTER_PATTERNS = [
    r"^第\s*[\d零一二三四五六七八九十百千]+\s*[章回卷部节].*$",
    r"^【第\s*[\d零一二三四五六七八九十百千]+\s*[章回卷部节].*】$",
    r"^Chapter\s+\d+.*$",
    r"^CHAPTER\s+\d+.*$",
    r"^\d+\.\s*.+$",
    r"^##\s+.+$",
]


def _chapter_key(title: str) -> str:
    """Normalize equivalent decorated headings for duplicate suppression."""
    return title.strip().strip("【】").strip()


def parse_text(raw: bytes | str, filename: str) -> DistillationInput:
    if isinstance(raw, str):
        text, encoding = raw, "utf-8"
    else:
        try:
            text, encoding = raw.decode("utf-8-sig"), "utf-8"
        except UnicodeDecodeError:
            text, encoding = raw.decode("gb18030"), "gb18030"
    source_format = Path(filename).suffix.lower().lstrip(".") or "txt"
    if source_format == "markdown": source_format = "md"
    if source_format not in {"txt", "md", "markdown"}: source_format = "txt"
    lines = text.splitlines(keepends=True)
    matches = []
    seen = set()
    offset = 0
    for line in lines:
        stripped = line.strip()
        if any(re.match(pattern, stripped, re.I) for pattern in CHAPTER_PATTERNS):
            title = stripped.lstrip("# ")
            key = _chapter_key(title)
            if key not in seen:
                seen.add(key)
                matches.append((offset, title))
        offset += len(line)
    if not matches: matches = [(0, "全文")]
    chapters = []
    for index, (start, title) in enumerate(matches):
        end = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        chapter_text = text[start:end]
        chapters.append(DistillationChapter(index, title, chapter_text, start, end))
    return DistillationInput(text, source_format, filename, encoding, chapters)
