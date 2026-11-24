"""Shared FTS5 tokenizer for the search index and its queries.

Named _tokenizer, not _tokenize: CPython ships a C builtin module named
_tokenize, and the builtin importer wins over sys.path, so a sibling
_tokenize.py would never be importable.
"""


def tokenize_chinese(text):
    """Convert Chinese text to space-separated overlapping bigrams + unigrams for FTS5."""
    if not text:
        return ""
    chars = list(text)
    tokens = []
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    tokens.extend(chars)
    return " ".join(tokens)
