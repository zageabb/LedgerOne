from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

BLOCK_SIZE = 512
DIRECTORY_OFFSET = 2 * BLOCK_SIZE
DIRECTORY_ENTRY_SIZE = 26
MAX_NAME_LEN = 15


@dataclass(frozen=True)
class VolumeEntry:
    name: str
    first_block: int
    last_block: int
    allocated_size: int
    logical_size: int
    complete: bool
    raw_directory_entry: bytes


class CashLinkVolume:
    """Reader for the UCSD p-System style volumes used by CashLink."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if len(self.data) < DIRECTORY_OFFSET + DIRECTORY_ENTRY_SIZE:
            raise ValueError(f"{self.path} is too small to be a CashLink volume")
        self.volume_name = self._read_volume_name()
        self._entries = tuple(self._read_entries())
        if not self._entries:
            raise ValueError(f"{self.path} does not contain a valid CashLink directory")

    @classmethod
    def looks_like_volume(cls, path: str | Path) -> bool:
        try:
            cls(path)
            return True
        except (OSError, ValueError):
            return False

    def _read_volume_name(self) -> str:
        raw = self.data[DIRECTORY_OFFSET:DIRECTORY_OFFSET + DIRECTORY_ENTRY_SIZE]
        length = raw[6] & 0x7F
        if not 1 <= length <= MAX_NAME_LEN:
            raise ValueError("invalid volume directory header")
        name = raw[7:7 + length]
        try:
            return name.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid volume name") from exc

    def _read_entries(self) -> Iterator[VolumeEntry]:
        max_entries = min(128, (len(self.data) - DIRECTORY_OFFSET) // DIRECTORY_ENTRY_SIZE)
        for index in range(1, max_entries):
            start = DIRECTORY_OFFSET + index * DIRECTORY_ENTRY_SIZE
            raw = self.data[start:start + DIRECTORY_ENTRY_SIZE]
            first_block = int.from_bytes(raw[0:2], "little")
            last_block = int.from_bytes(raw[2:4], "little")
            name_len = raw[6] & 0x7F
            if not (1 <= name_len <= MAX_NAME_LEN):
                break
            if first_block <= 0 or last_block <= first_block:
                break
            name_bytes = raw[7:7 + name_len]
            if not all(32 <= value < 127 for value in name_bytes):
                break
            name = name_bytes.decode("ascii")
            last_block_bytes = int.from_bytes(raw[22:24], "little")
            blocks = last_block - first_block
            allocated_size = blocks * BLOCK_SIZE
            if 0 < last_block_bytes <= BLOCK_SIZE:
                logical_size = (blocks - 1) * BLOCK_SIZE + last_block_bytes
            else:
                logical_size = allocated_size
            byte_start = first_block * BLOCK_SIZE
            expected_end = byte_start + logical_size
            complete = expected_end <= len(self.data)
            if byte_start >= len(self.data):
                complete = False
            yield VolumeEntry(
                name=name,
                first_block=first_block,
                last_block=last_block,
                allocated_size=allocated_size,
                logical_size=logical_size,
                complete=complete,
                raw_directory_entry=raw,
            )

    @property
    def entries(self) -> tuple[VolumeEntry, ...]:
        return self._entries

    def get_entry(self, name: str) -> VolumeEntry | None:
        target = name.upper()
        return next((entry for entry in self.entries if entry.name.upper() == target), None)

    def read_file(self, name: str, *, allocated: bool = False) -> bytes:
        entry = self.get_entry(name)
        if entry is None:
            raise KeyError(name)
        start = entry.first_block * BLOCK_SIZE
        size = entry.allocated_size if allocated else entry.logical_size
        return self.data[start:min(start + size, len(self.data))]

    def extract_all(self, destination: str | Path) -> list[Path]:
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for entry in self.entries:
            out = destination / entry.name
            out.write_bytes(self.read_file(entry.name))
            written.append(out)
        return written
