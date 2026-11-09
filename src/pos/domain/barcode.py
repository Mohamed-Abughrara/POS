from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidBarcode


def check_digit(body: str) -> int:
    """GS1 check digit for EAN-13 / EAN-8 / UPC-A bodies (digits without the check digit)."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


@dataclass(frozen=True)
class Barcode:
    value: str

    def __post_init__(self):
        v = self.value.strip()
        object.__setattr__(self, "value", v)
        if not v.isdigit():
            raise InvalidBarcode("barcode must be digits")
        if len(v) == 13 and v.startswith("2"):
            return  # internal code, checksum not enforced
        if len(v) not in (8, 12, 13):
            raise InvalidBarcode("barcode must be EAN-13, EAN-8 or UPC-A")
        if int(v[-1]) != check_digit(v[:-1]):
            raise InvalidBarcode("bad barcode checksum")
