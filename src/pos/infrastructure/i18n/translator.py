from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def _load(locale: str) -> dict[str, str]:
    return json.loads((_DIR / f"{locale}.json").read_text(encoding="utf-8"))


class JsonTranslator:
    """All UI strings live in en.json / ar.json (NFR-13). Missing Arabic keys fall back to English."""

    def __init__(self, locale: str = "en"):
        self.locale = locale if locale in ("en", "ar") else "en"
        self._strings = _load(self.locale)
        self._fallback = _load("en")

    def has(self, key: str) -> bool:
        return key in self._strings or key in self._fallback

    def t(self, key: str, **kw) -> str:
        text = self._strings.get(key) or self._fallback.get(key) or key
        try:
            return text.format(**kw) if kw else text
        except (KeyError, IndexError):
            return text


def translator_factory(locale: str) -> JsonTranslator:
    return JsonTranslator(locale)
