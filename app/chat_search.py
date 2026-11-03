"""Thai/English search text for the chat hub.

Thai has no spaces between words. A dictionary segmenter is not stdlib and is
too heavy for an i3 with 8 GB, and FTS5 ``trigram`` cannot match 2-character
Thai words. ``seg`` splits Thai runs into overlapping character bigrams and
folds Latin words (lower case, accents removed). The tokens are stored in a
contentless FTS5 table with the ``ascii`` tokenizer, which splits on ASCII
separators and leaves Thai marks inside the token.

The database file does not call ``lca_seg``. The application registers it on
each connection, so the file still opens in any SQLite tool.
"""

from __future__ import annotations

import re
import unicodedata

THAI = r"\u0E00-\u0E7F"
TOK = re.compile(rf"[{THAI}]+|[^\W_]+")
ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)


def _fold(word: str) -> str:
    """Lower-case and strip Latin accents."""
    folded = unicodedata.normalize("NFKD", word.lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def seg(text) -> str:
    """Thai runs become overlapping bigrams. Other words are folded.

    A one-character Thai run stays as that character. Output is space-separated.
    ``None`` and non-strings are treated as empty.
    """
    if not isinstance(text, str) or not text:
        return ""
    out = []
    normalized = unicodedata.normalize("NFC", text).translate(ZW)
    for match in TOK.finditer(normalized):
        word = match.group()
        if "\u0E00" <= word[0] <= "\u0E7F":
            if len(word) == 1:
                out.append(word)
            else:
                out.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            out.append(_fold(word))
    return " ".join(out)


def is_single_thai_char(user_q: str) -> bool:
    """True when the whole query is one Thai character (not FTS-indexed usefully)."""
    terms = (user_q or "").split()
    if len(terms) != 1:
        return False
    tokens = seg(terms[0]).split()
    return (
        len(tokens) == 1
        and len(tokens[0]) == 1
        and "\u0E00" <= tokens[0] <= "\u0E7F"
    )


def fts_query(user_q: str):
    """Each whitespace term becomes a quoted phrase of its tokens. Terms are ANDed.

    The last ASCII term gets a prefix ``*``. A single Thai character cannot be
    a useful FTS query; the caller uses ``LIKE`` instead and this returns None.
    """
    parts = []
    terms = (user_q or "").split()
    for index, term in enumerate(terms):
        tokens = seg(term).split()
        if not tokens:
            continue
        if (
            len(tokens) == 1
            and len(tokens[0]) == 1
            and "\u0E00" <= tokens[0] <= "\u0E7F"
        ):
            return None
        phrase = '"' + " ".join(tok.replace('"', '""') for tok in tokens) + '"'
        if index == len(terms) - 1 and term.isascii() and term.isalnum():
            phrase += "*"
        parts.append(phrase)
    return " AND ".join(parts) or None


def snippet(content: str, query: str, width: int = 30) -> str:
    """Short Python snippet. Marks the first matching term with brackets."""
    if not content:
        return ""
    low = content.lower()
    for term in (query or "").split():
        found = low.find(term.lower())
        if found >= 0:
            start = max(0, found - width)
            end = found + len(term) + width
            prefix = "…" if start else ""
            suffix = "…" if end < len(content) else ""
            return (
                prefix
                + content[start:found]
                + "["
                + content[found:found + len(term)]
                + "]"
                + content[found + len(term):end]
                + suffix
            )
    return content[: 2 * width]


def like_pattern(text: str) -> str:
    """Escape ``%``, ``_``, and ``\\`` for a ``LIKE ? ESCAPE '\\'`` contains-match."""
    escaped = (text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
