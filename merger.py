import argparse
import html
import math
import re
import uuid

import ebooklib
from bs4 import BeautifulSoup # html/xml parser
from ebooklib import epub 

BLOCK_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"]

# Allowed alignment moves: (items taken from side A, items taken from side B) -> penalty
MOVES = {(1, 1): 0.0, (2, 1): 1.0, (1, 2): 1.0, (2, 2): 1.5, (1, 0): 3.0, (0, 1): 3.0}

SENTENCE_RE = re.compile(r'[^.!?…]+(?:[.!?…]+[»"”’)\]]*|$)')

CSS = """
.l1 { }
.l2 { color: #666; font-style: italic; }
"""


# Read the flags
def parse_args():
    parser = argparse.ArgumentParser(description="Merge two translations of a book into one bilingual EPUB.")
    parser.add_argument("epub1", help="path to the first EPUB (language 1)")
    parser.add_argument("epub2", help="path to the second EPUB (language 2)")
    parser.add_argument("output", help="path for the merged EPUB")
    parser.add_argument("--lang1", default="fr", help="language code of epub1 (default: fr)")
    parser.add_argument("--lang2", default="en", help="language code of epub2 (default: en)")
    return parser.parse_args()


# Load Epubs
def load_chapters(path):
    """Return (book, chapters), where each chapter is a list of paragraph strings, in spine order."""
    book = epub.read_epub(path)
    chapters = []
    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        paragraphs = []
        for tag in soup.find_all(BLOCK_TAGS):
            # Skip containers whose text is already captured by a nested block tag
            if tag.find(BLOCK_TAGS):
                continue
            text = tag.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
        if paragraphs:
            chapters.append(paragraphs)
    return book, chapters


def align(a, b, length):
    """Length-based (Gale-Church style) alignment of two sequences.

    Returns a list of (a_group, b_group) pairs, where each group is a list of
    consecutive items (possibly empty when one side has no counterpart).
    """
    la = [length(x) for x in a]
    lb = [length(x) for x in b]
    ratio = (sum(lb) or 1) / (sum(la) or 1)
    n, m = len(a), len(b)

    cost = [[math.inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if cost[i][j] == math.inf:
                continue
            for (di, dj), penalty in MOVES.items():
                ni, nj = i + di, j + dj
                if ni > n or nj > m:
                    continue
                c = penalty
                if di and dj:
                    expected = sum(la[i:ni]) * ratio
                    c += abs(math.log((expected + 1) / (sum(lb[j:nj]) + 1)))
                if cost[i][j] + c < cost[ni][nj]:
                    cost[ni][nj] = cost[i][j] + c
                    back[ni][nj] = (di, dj)

    pairs = []
    i, j = n, m
    while i or j:
        di, dj = back[i][j]
        pairs.append((a[i - di:i], b[j - dj:j]))
        i, j = i - di, j - dj
    pairs.reverse()
    return pairs


def chapter_length(chapter):
    return sum(len(p) for p in chapter)


# Match chapters
def match_chapters(chapters1, chapters2):
    pairs = align(chapters1, chapters2, chapter_length)
    # Flatten grouped chapters so each side is a single list of paragraphs
    return [([p for ch in g1 for p in ch], [p for ch in g2 for p in ch]) for g1, g2 in pairs]


# Match paragraphs
def match_paragraphs(paragraphs1, paragraphs2):
    return [(" ".join(g1), " ".join(g2)) for g1, g2 in align(paragraphs1, paragraphs2, len)]


# Match sentences
def split_sentences(text):
    return [s.strip() for s in SENTENCE_RE.findall(text) if s.strip()]


def match_sentences(paragraph1, paragraph2):
    pairs = align(split_sentences(paragraph1), split_sentences(paragraph2), len)
    return [(" ".join(g1), " ".join(g2)) for g1, g2 in pairs]


# Combine paragraphs
def combine_paragraph(sentence_pairs, lang1, lang2):
    parts = []
    for s1, s2 in sentence_pairs:
        if s1:
            parts.append(f'<span class="l1" lang="{lang1}">{html.escape(s1)}</span>')
        if s2:
            parts.append(f'<span class="l2" lang="{lang2}">({html.escape(s2)})</span>')
    return "<p>" + " ".join(parts) + "</p>"


def first_title(book, fallback):
    titles = book.get_metadata("DC", "title")
    return titles[0][0] if titles else fallback


# Merge into a single Epub
def build_epub(book1, book2, chapter_pairs, lang1, lang2):
    merged = epub.EpubBook()
    merged.set_identifier(str(uuid.uuid4()))
    merged.set_title(f"{first_title(book1, lang1)} / {first_title(book2, lang2)}")
    merged.set_language(lang1)

    style = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    merged.add_item(style)

    chapters = []
    for index, (paragraphs1, paragraphs2) in enumerate(chapter_pairs, start=1):
        body = [
            combine_paragraph(match_sentences(p1, p2), lang1, lang2)
            for p1, p2 in match_paragraphs(paragraphs1, paragraphs2)
        ]
        chapter = epub.EpubHtml(title=f"Chapter {index}", file_name=f"chapter_{index:03}.xhtml", lang=lang1)
        chapter.content = "\n".join(body)
        chapter.add_item(style)
        merged.add_item(chapter)
        chapters.append(chapter)

    merged.toc = chapters
    merged.add_item(epub.EpubNcx())
    merged.add_item(epub.EpubNav())
    merged.spine = ["nav"] + chapters
    return merged


def main():
    args = parse_args()
    book1, chapters1 = load_chapters(args.epub1)
    book2, chapters2 = load_chapters(args.epub2)

    chapter_pairs = match_chapters(chapters1, chapters2)
    merged = build_epub(book1, book2, chapter_pairs, args.lang1, args.lang2)

    # Export the final Epub
    epub.write_epub(args.output, merged)
    print(f"Wrote {len(chapter_pairs)} chapters to {args.output}")


if __name__ == "__main__":
    main()
