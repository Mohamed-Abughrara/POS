"""Locale-aware formatting and parsing. Money formatting lives here, never in the domain."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from ..application.errors import InvalidInput

_ARABIC_INDIC = str.maketrans("0123456789.,", "٠١٢٣٤٥٦٧٨٩٫٬")
_TO_ASCII = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬،", "0123456789.,,")


def normalize_digits(text: str) -> str:
    """Accept Arabic-Indic digits typed by users."""
    return text.translate(_TO_ASCII).strip()


class Formatter:
    def __init__(self, locale: str = "en", arabic_digits: bool = False):
        self.locale = locale
        self.arabic_digits = arabic_digits

    def _digits(self, text: str) -> str:
        return text.translate(_ARABIC_INDIC) if self.arabic_digits and self.locale == "ar" else text

    def money(self, dirhams: int, with_currency: bool = True) -> str:
        sign = "-" if dirhams < 0 else ""
        d = abs(dirhams)
        text = f"{sign}{d // 1000}.{d % 1000:03d}"
        if with_currency:
            text += " د.ل" if self.locale == "ar" else " LYD"
        return self._digits(text)

    def qty(self, q: Decimal) -> str:
        return self._digits(str(int(q)) if q == q.to_integral_value() else f"{q:.3f}")

    def number(self, n) -> str:
        return self._digits(str(n))

    def datetime(self, dt: datetime) -> str:
        return self._digits(dt.strftime("%Y-%m-%d %H:%M"))

    def date(self, d: date) -> str:
        return self._digits(d.isoformat())


def parse_money(text: str) -> int:
    """'12.5' -> 12500 dirhams. Rejects more than 3 decimals and negatives."""
    value = parse_decimal(text)
    if value < 0 or value != value.quantize(Decimal("0.001")):
        raise InvalidInput(f"invalid amount: {text}")
    return int(value * 1000)


def parse_decimal(text: str) -> Decimal:
    try:
        return Decimal(normalize_digits(text).replace(",", ""))
    except InvalidOperation:
        raise InvalidInput(f"not a number: {text}") from None


def parse_signed_money(text: str) -> int:
    value = parse_decimal(text)
    if value != value.quantize(Decimal("0.001")):
        raise InvalidInput(f"invalid amount: {text}")
    return int(value * 1000)


def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(normalize_digits(text))
    except ValueError:
        raise InvalidInput(f"invalid date (use YYYY-MM-DD): {text}") from None


def opt(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip()
    return text or None
