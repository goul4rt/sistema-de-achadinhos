"""Normalização de texto para busca e deduplicação."""

from __future__ import annotations

import hashlib
import re
import unicodedata

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "com", "para", "pra", "em", "a", "o", "as", "os",
    "the", "and", "for", "with", "kit", "novo", "nova", "original", "oferta", "promocao",
}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str | None) -> str:
    """Minúsculas, sem acento, só [a-z0-9] separados por espaço."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def tokens(text: str | None) -> list[str]:
    return [t for t in normalize(text).split() if t]


def contains_term(haystack_tokens: set[str], haystack_text: str, term: str) -> bool:
    """Um termo casa se todas as suas palavras aparecem no texto.

    Palavras com 3+ letras também casam como prefixo ("fone" casa "fones"), e termos
    entre aspas exigem a frase exata, ex.: '"air fryer"'.
    """
    term = term.strip()
    if not term:
        return False
    if len(term) >= 2 and term[0] == term[-1] == '"':
        phrase = normalize(term[1:-1])
        return bool(phrase) and f" {phrase} " in f" {haystack_text} "
    words = tokens(term)
    if not words:
        return False
    for w in words:
        if w in haystack_tokens:
            continue
        if len(w) >= 3 and any(t.startswith(w) for t in haystack_tokens):
            continue
        return False
    return True


def fingerprint(title: str, store: str = "") -> str:
    """Chave para agrupar o mesmo produto repostado (mesma loja, mesmo título "essencial")."""
    words = sorted({t for t in tokens(title) if t not in _STOPWORDS and len(t) > 1})
    base = normalize(store) + "|" + " ".join(words[:16])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()
