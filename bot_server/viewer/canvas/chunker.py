"""Sentence-based chunking for transcript input.

Lifted verbatim from /home/tan_t/workspace/canvas/canvas/chunker.py.
"""
from __future__ import annotations

import re

_SENT_BREAK = re.compile(r"(?<=[。．！？\n])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_BREAK.split(text)]
    return [p for p in parts if p]


def chunk_text(text: str, target_chars: int = 90) -> list[str]:
    chunks: list[str] = []
    buf: list[str] = []
    cur_len = 0
    for s in split_sentences(text):
        buf.append(s)
        cur_len += len(s)
        if cur_len >= target_chars:
            chunks.append(" ".join(buf))
            buf = []
            cur_len = 0
    if buf:
        chunks.append(" ".join(buf))
    return chunks


class StreamingChunker:
    """Buffer for character-by-character / line-by-line transcript input.

    Emits a chunk when:
      - the buffer hits `flush_chars` characters, OR
      - a sentence terminator is seen and the buffer >= `min_chars`.
    """

    def __init__(self, min_chars: int = 60, flush_chars: int = 140) -> None:
        self.min_chars = min_chars
        self.flush_chars = flush_chars
        self._buf: str = ""

    def feed(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        while True:
            if len(self._buf) >= self.flush_chars:
                out.append(self._buf.strip())
                self._buf = ""
                continue
            for m in _SENT_BREAK.finditer(self._buf):
                idx = m.end()
                if idx >= self.min_chars:
                    out.append(self._buf[:idx].strip())
                    self._buf = self._buf[idx:]
                    break
            else:
                break
        return [c for c in out if c]

    def drain(self) -> str:
        remaining = self._buf.strip()
        self._buf = ""
        return remaining
