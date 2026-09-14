from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterator

ACCOUNT_RECORD_SIZE = 380
NOMINAL_RECORD_SIZE = 64


def _pascal_string(data: bytes, offset: int, max_len: int) -> str:
    if offset >= len(data):
        return ""
    length = data[offset]
    if length == 0 or length > max_len or offset + 1 + length > len(data):
        return ""
    raw = data[offset + 1:offset + 1 + length]
    if not all(value == 126 or 32 <= value < 127 for value in raw):
        return ""
    return raw.decode("latin1").strip("\x00")


@dataclass(frozen=True)
class LedgerAccount:
    ledger: str
    account_number: int
    name: str
    address_lines: tuple[str, ...]
    phone_1: str
    phone_2: str
    alpha_code: str
    raw_hex: str

    def to_dict(self) -> dict:
        result = asdict(self)
        result["address_lines"] = list(self.address_lines)
        return result


@dataclass(frozen=True)
class NominalAccount:
    account_number: int
    name: str
    raw_hex: str

    def to_dict(self) -> dict:
        return asdict(self)


def iter_ledger_accounts(data: bytes, ledger: str) -> Iterator[LedgerAccount]:
    ledger = ledger.lower()
    if ledger not in {"purchase", "sales"}:
        raise ValueError("ledger must be 'purchase' or 'sales'")
    record_count = len(data) // ACCOUNT_RECORD_SIZE
    for account_number in range(record_count):
        record = data[account_number * ACCOUNT_RECORD_SIZE:(account_number + 1) * ACCOUNT_RECORD_SIZE]
        identity = _pascal_string(record, 0, 149)
        if not identity:
            continue
        parts = [part.strip() for part in identity.split("~")]
        while parts and not parts[-1]:
            parts.pop()
        if not parts:
            continue
        yield LedgerAccount(
            ledger=ledger,
            account_number=account_number,
            name=parts[0],
            address_lines=tuple(parts[1:]),
            phone_1=_pascal_string(record, 150, 19),
            phone_2=_pascal_string(record, 170, 39),
            alpha_code=_pascal_string(record, 210, 15),
            raw_hex=record.hex(),
        )


def iter_nominal_accounts(data: bytes) -> Iterator[NominalAccount]:
    record_count = len(data) // NOMINAL_RECORD_SIZE
    for account_number in range(record_count):
        record = data[account_number * NOMINAL_RECORD_SIZE:(account_number + 1) * NOMINAL_RECORD_SIZE]
        name = _pascal_string(record, 0, 31)
        if not name:
            continue
        yield NominalAccount(account_number=account_number, name=name, raw_hex=record.hex())
