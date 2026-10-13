"""Split a parsed day file into searchable passages.

One day becomes, in this order: a ``title`` passage, ``facts``, ``journal`` and ``notes``
passages split at Markdown headings (the facts are the day file's "At a glance" text without
its "none" lines, so a passage's heading is "Food", "Places", ... or a family member's name),
and ``transcript``
passages, one or more per capture. Every passage is at most :data:`MAX_CHARS` characters;
longer text is cut at paragraph, then sentence, then word boundaries. ``ordinal`` counts
passages within a section.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from lumitrace.frames.dayfile import CAPTURE_LABELS, DayFile, render_facts_section

MAX_CHARS = 1000
"""Upper bound for one passage: small enough for precise hits, big enough for context."""

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


@dataclass(frozen=True)
class Passage:
    section: str
    """``title`` | ``facts`` | ``journal`` | ``notes`` | ``transcript``"""
    heading: str | None
    capture_id: str | None
    ordinal: int
    text: str

    @property
    def embed_input(self) -> str:
        """What gets embedded: the heading gives short passages their context."""
        return f"{self.heading}\n{self.text}" if self.heading else self.text

    @property
    def text_hash(self) -> str:
        """sha256 of :attr:`embed_input`; an unchanged hash reuses the stored vector."""
        return hashlib.sha256(self.embed_input.encode("utf-8")).hexdigest()


def build_passages(day: DayFile, max_chars: int = MAX_CHARS) -> list[Passage]:
    out: list[Passage] = []
    if day.title.strip():
        out.append(Passage("title", None, None, 0, day.title.strip()))
    facts_text = render_facts_section(day.facts, include_empty=False)
    facts = _markdown_passages("facts", facts_text, max_chars)
    # "### Family" has nothing under it but the members' "####" blocks, which are passages.
    facts = [p for p in facts if not (p.heading == "Family" and p.text == "Family")]
    out.extend(replace(p, ordinal=i) for i, p in enumerate(facts))
    out.extend(_markdown_passages("journal", day.journal, max_chars))
    out.extend(_markdown_passages("notes", day.notes, max_chars))
    ordinal = 0
    for capture in day.captures:
        heading = f"{capture.captured_at:%H:%M} · {CAPTURE_LABELS.get(capture.kind, capture.kind)}"
        for chunk in chunk_text(capture.text, max_chars):
            out.append(Passage("transcript", heading, capture.id, ordinal, chunk))
            ordinal += 1
    return out


def split_by_headings(markdown: str) -> list[tuple[str | None, str]]:
    """``[(heading or None, body)]`` at every Markdown heading outside code fences."""
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    in_fence = False
    for line in markdown.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _HEADING_RE.match(line)
        if m:
            sections.append((m.group(2).strip(), []))
        else:
            sections[-1][1].append(line)
    out: list[tuple[str | None, str]] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if heading is None and not body:
            continue
        out.append((heading, body))
    return out


def _markdown_passages(section: str, markdown: str, max_chars: int) -> list[Passage]:
    out: list[Passage] = []
    for heading, body in split_by_headings(markdown):
        # A heading with nothing under it (e.g. "### Slept 8 hours") is content in itself.
        text = body or (heading or "")
        for chunk in chunk_text(text, max_chars):
            out.append(Passage(section, heading, None, len(out), chunk))
    return out


def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split ``text`` into chunks of at most ``max_chars``, packing whole paragraphs together
    and falling back to sentences, then words, then a hard cut for very long runs."""
    pieces: list[str] = []
    for para in _PARAGRAPH_SPLIT_RE.split(text.strip()):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        sentences: list[str] = []
        for sentence in _SENTENCE_SPLIT_RE.split(para):
            sentences.extend(_split_words(sentence, max_chars))
        pieces.extend(_pack(sentences, max_chars, " "))
    return _pack(pieces, max_chars, "\n\n")


def _split_words(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    words: list[str] = []
    for word in sentence.split():
        while len(word) > max_chars:
            words.append(word[:max_chars])
            word = word[max_chars:]
        if word:
            words.append(word)
    return _pack(words, max_chars, " ")


def _pack(pieces: Iterable[str], max_chars: int, sep: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + len(sep) + len(piece) <= max_chars:
            current = f"{current}{sep}{piece}"
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks
