from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib

RECORD_SIZE = 128
ID_OFFSET, ID_MAX = 0, 3
NAME_OFFSET, NAME_MAX = 4, 29
PASSWORD_OFFSET, PASSWORD_MAX = 34, 9
RIGHTS_OFFSET, RIGHTS_LEN = 44, 32
PRINTER_OFFSET = 76


def _short_string(record: bytes, offset: int, max_len: int) -> bytes | None:
    if offset >= len(record):
        return None
    length = record[offset]
    if length == 0 or length > max_len or offset + 1 + length > len(record):
        return None
    value = record[offset + 1:offset + 1 + length]
    if not all(32 <= b < 127 for b in value):
        return None
    return value


def _fingerprint(secret: bytes) -> str:
    return hashlib.sha256(b"LedgerOne/CashLink/security-dat/v1\0" + secret).hexdigest()


@dataclass(frozen=True)
class SecurityDatOperator:
    slot: int
    operator_id: str
    name: str
    password_length: int
    password_fingerprint: str
    masked_password: str
    access_rights_hex: str
    default_printer: int
    reserved_hex: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_security_dat(path: str | Path) -> list[SecurityDatOperator]:
    """Parse the SECURITY.DAT layout inferred from CashLink Security 4.1.

    The executable statically demonstrates a 128-byte file record, and editing code
    addresses Pascal short strings at offsets 0, 4 and 34, a 32-byte access block at
    offset 44, and a printer word at offset 76. Empty/unrecognised records are skipped.
    Plaintext passwords are deliberately never returned by this API.
    """
    data = Path(path).read_bytes()
    operators: list[SecurityDatOperator] = []
    for slot, start in enumerate(range(0, len(data) - RECORD_SIZE + 1, RECORD_SIZE)):
        record = data[start:start + RECORD_SIZE]
        operator_id = _short_string(record, ID_OFFSET, ID_MAX)
        name = _short_string(record, NAME_OFFSET, NAME_MAX)
        password = _short_string(record, PASSWORD_OFFSET, PASSWORD_MAX)
        if operator_id is None or name is None or password is None:
            continue
        printer = int.from_bytes(record[PRINTER_OFFSET:PRINTER_OFFSET + 2], "little")
        operators.append(
            SecurityDatOperator(
                slot=slot,
                operator_id=operator_id.decode("ascii"),
                name=name.decode("latin1"),
                password_length=len(password),
                password_fingerprint=_fingerprint(password),
                masked_password="*" * len(password),
                access_rights_hex=record[RIGHTS_OFFSET:RIGHTS_OFFSET + RIGHTS_LEN].hex(),
                default_printer=printer,
                reserved_hex=record[78:].hex(),
            )
        )
    return operators


def read_password_for_migration(path: str | Path, slot: int) -> bytes | None:
    """Read one operator password only for an in-memory trusted migration step."""
    data = Path(path).read_bytes()
    start = slot * RECORD_SIZE
    if start < 0 or start + RECORD_SIZE > len(data):
        return None
    return _short_string(data[start:start + RECORD_SIZE], PASSWORD_OFFSET, PASSWORD_MAX)
