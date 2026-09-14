from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import hmac
import os

from .volume import CashLinkVolume

LEGACY_MODULE_PASSWORD_FIELDS = {
    "purchase": ("INFO.PURCH", 2, 15),
    "sales": ("INFO.SALES", 2, 15),
    "nominal": ("INFO.NOM", 64, 15),
}


@dataclass(frozen=True)
class SecurityFinding:
    source: str
    module: str
    internal_file: str
    offset: int
    present: bool
    storage: str
    length: int
    fingerprint: str | None
    masked: str
    confidence: str

    def to_dict(self) -> dict:
        return asdict(self)


def _read_pascal_secret(data: bytes, offset: int, max_len: int) -> bytes | None:
    if offset >= len(data):
        return None
    length = data[offset]
    if length == 0 or length > max_len or offset + 1 + length > len(data):
        return None
    secret = data[offset + 1:offset + 1 + length]
    if not all(32 <= value < 127 for value in secret):
        return None
    return secret


def _fingerprint(secret: bytes) -> str:
    return hashlib.sha256(b"LedgerOne/CashLink/fingerprint/v1\0" + secret).hexdigest()


def audit_volume_security(volume: CashLinkVolume) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for module, (internal_file, offset, max_len) in LEGACY_MODULE_PASSWORD_FIELDS.items():
        if volume.get_entry(internal_file) is None:
            continue
        secret = _read_pascal_secret(volume.read_file(internal_file), offset, max_len)
        findings.append(
            SecurityFinding(
                source=str(volume.path),
                module=module,
                internal_file=internal_file,
                offset=offset,
                present=secret is not None,
                storage="cleartext_pascal" if secret is not None else "empty_or_unknown",
                length=len(secret) if secret else 0,
                fingerprint=_fingerprint(secret) if secret else None,
                masked=("*" * len(secret)) if secret else "",
                confidence="high",
            )
        )
    return findings


def read_secret_for_migration(volume: CashLinkVolume, module: str) -> bytes | None:
    """Read a legacy module secret only for trusted in-memory migration."""
    try:
        internal_file, offset, max_len = LEGACY_MODULE_PASSWORD_FIELDS[module]
    except KeyError as exc:
        raise ValueError(f"unknown CashLink module: {module}") from exc
    if volume.get_entry(internal_file) is None:
        return None
    return _read_pascal_secret(volume.read_file(internal_file), offset, max_len)


def modern_password_hash(secret: bytes) -> str:
    """Convert a legacy secret directly into a salted scrypt hash."""
    salt = os.urandom(16)
    n, r, p = 16384, 8, 1
    derived = hashlib.scrypt(secret, salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt$N={n},r={r},p={p}${salt.hex()}${derived.hex()}"


def verify_modern_password(candidate: bytes, encoded: str) -> bool:
    try:
        scheme, params, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "scrypt":
            return False
        settings = dict(item.split("=", 1) for item in params.split(","))
        n, r, p = int(settings["N"]), int(settings["r"]), int(settings["p"])
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, KeyError):
        return False
    actual = hashlib.scrypt(candidate, salt=salt, n=n, r=r, p=p, dklen=len(expected))
    return hmac.compare_digest(actual, expected)
