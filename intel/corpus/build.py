"""Builds the SQLite FTS5 full-text search index from local statutory markdown files."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Final

CORPUS_ROOT: Final[Path] = Path(__file__).resolve().parent
DB_PATH: Final[Path] = CORPUS_ROOT / "corpus.db"

_FRONTMATTER_RE: Final = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()

    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"\'')
    content = match.group(2).strip()
    return meta, content


def build_corpus_db(db_path: Path = DB_PATH, root: Path = CORPUS_ROOT) -> int:
    """Build or rebuild SQLite FTS5 index for statutory corpus records."""
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Use FTS5 for full-text search and BM25 ranking
    cursor.execute("""
        CREATE VIRTUAL TABLE corpus_fts USING fts5(
            source,
            section,
            title,
            content,
            path UNINDEXED
        )
    """)

    count = 0
    for md_file in root.rglob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        meta, content = parse_frontmatter(text)
        source = meta.get("source", "Unknown")
        section = meta.get("section", md_file.stem.upper())
        title = meta.get("title", "")

        cursor.execute(
            "INSERT INTO corpus_fts (source, section, title, content, path) VALUES (?, ?, ?, ?, ?)",
            (source, section, title, content, str(md_file.relative_to(root))),
        )
        count += 1

    conn.commit()
    conn.close()
    return count


if __name__ == "__main__":
    total = build_corpus_db()
    print(f"Built corpus database at {DB_PATH} with {total} entries.")
