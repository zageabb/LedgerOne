from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .accounts import iter_ledger_accounts, iter_nominal_accounts
from .security import audit_volume_security, modern_password_hash, read_secret_for_migration
from .volume import CashLinkVolume


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_accounts_csv(volume: CashLinkVolume, destination: str | Path) -> list[Path]:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    for internal_file, ledger in (("ACCS.PURCH", "purchase"), ("ACCS.SALES", "sales")):
        if volume.get_entry(internal_file) is None:
            continue
        output = destination / f"{ledger}_accounts.csv"
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "ledger", "account_number", "name", "address_lines", "phone_1", "phone_2", "alpha_code", "raw_hex"
            ])
            writer.writeheader()
            for row in iter_ledger_accounts(volume.read_file(internal_file), ledger):
                item = row.to_dict()
                item["address_lines"] = " | ".join(item["address_lines"])
                writer.writerow(item)
        outputs.append(output)

    if volume.get_entry("ACCS.NOM") is not None:
        output = destination / "nominal_accounts.csv"
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["account_number", "name", "raw_hex"])
            writer.writeheader()
            for row in iter_nominal_accounts(volume.read_file("ACCS.NOM")):
                writer.writerow(row.to_dict())
        outputs.append(output)
    return outputs


def export_to_sqlite(
    sources: Iterable[str | Path],
    output_path: str | Path,
    *,
    migrate_legacy_passwords: bool = False,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS legacy_sources (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL, filename TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE, size_bytes INTEGER NOT NULL, volume_name TEXT
        );
        CREATE TABLE IF NOT EXISTS legacy_files (
            id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES legacy_sources(id),
            name TEXT NOT NULL, first_block INTEGER NOT NULL, last_block INTEGER NOT NULL,
            logical_size INTEGER NOT NULL, complete INTEGER NOT NULL, data BLOB NOT NULL,
            UNIQUE(source_id, name)
        );
        CREATE TABLE IF NOT EXISTS legacy_accounts (
            id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES legacy_sources(id),
            ledger TEXT NOT NULL, account_number INTEGER NOT NULL, name TEXT NOT NULL,
            address_json TEXT NOT NULL, phone_1 TEXT NOT NULL, phone_2 TEXT NOT NULL,
            alpha_code TEXT NOT NULL, raw_hex TEXT NOT NULL,
            UNIQUE(source_id, ledger, account_number)
        );
        CREATE TABLE IF NOT EXISTS legacy_nominal_accounts (
            id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES legacy_sources(id),
            account_number INTEGER NOT NULL, name TEXT NOT NULL, raw_hex TEXT NOT NULL,
            UNIQUE(source_id, account_number)
        );
        CREATE TABLE IF NOT EXISTS legacy_security (
            id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES legacy_sources(id),
            module TEXT NOT NULL, internal_file TEXT NOT NULL, offset INTEGER NOT NULL,
            secret_present INTEGER NOT NULL, storage TEXT NOT NULL, secret_length INTEGER NOT NULL,
            fingerprint TEXT, modern_hash TEXT, reset_required INTEGER NOT NULL DEFAULT 0,
            UNIQUE(source_id, module)
        );
        CREATE TABLE IF NOT EXISTS legacy_fixed_records (
            id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES legacy_sources(id),
            internal_file TEXT NOT NULL, record_number INTEGER NOT NULL,
            record_size INTEGER NOT NULL, data BLOB NOT NULL,
            UNIQUE(source_id, internal_file, record_number)
        );
        """
    )

    record_sizes = {
        "TRANS.PURCH": 128,
        "TRANS.SALES": 128,
        "TRANS.NOM": 56,
        "ACCS.PURCH": 380,
        "ACCS.SALES": 380,
        "ACCS.NOM": 64,
    }

    for source in sources:
        path = Path(source)
        volume = CashLinkVolume(path)
        digest = sha256_path(path)
        conn.execute(
            "INSERT OR IGNORE INTO legacy_sources(path,filename,sha256,size_bytes,volume_name) VALUES(?,?,?,?,?)",
            (str(path), path.name, digest, path.stat().st_size, volume.volume_name),
        )
        source_id = int(conn.execute("SELECT id FROM legacy_sources WHERE sha256=?", (digest,)).fetchone()[0])

        for entry in volume.entries:
            data = volume.read_file(entry.name)
            conn.execute(
                """INSERT OR REPLACE INTO legacy_files
                   (source_id,name,first_block,last_block,logical_size,complete,data)
                   VALUES(?,?,?,?,?,?,?)""",
                (source_id, entry.name, entry.first_block, entry.last_block,
                 entry.logical_size, int(entry.complete), data),
            )
            rec_size = record_sizes.get(entry.name.upper())
            if rec_size:
                for record_number in range(len(data) // rec_size):
                    record = data[record_number * rec_size:(record_number + 1) * rec_size]
                    conn.execute(
                        """INSERT OR REPLACE INTO legacy_fixed_records
                           (source_id,internal_file,record_number,record_size,data)
                           VALUES(?,?,?,?,?)""",
                        (source_id, entry.name, record_number, rec_size, record),
                    )

        for internal_file, ledger in (("ACCS.PURCH", "purchase"), ("ACCS.SALES", "sales")):
            if volume.get_entry(internal_file) is None:
                continue
            for account in iter_ledger_accounts(volume.read_file(internal_file), ledger):
                conn.execute(
                    """INSERT OR REPLACE INTO legacy_accounts
                       (source_id,ledger,account_number,name,address_json,phone_1,phone_2,alpha_code,raw_hex)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (source_id, account.ledger, account.account_number, account.name,
                     json.dumps(account.address_lines), account.phone_1, account.phone_2,
                     account.alpha_code, account.raw_hex),
                )

        if volume.get_entry("ACCS.NOM") is not None:
            for account in iter_nominal_accounts(volume.read_file("ACCS.NOM")):
                conn.execute(
                    "INSERT OR REPLACE INTO legacy_nominal_accounts(source_id,account_number,name,raw_hex) VALUES(?,?,?,?)",
                    (source_id, account.account_number, account.name, account.raw_hex),
                )

        for finding in audit_volume_security(volume):
            modern_hash = None
            reset_required = 0
            if finding.present and migrate_legacy_passwords:
                secret = read_secret_for_migration(volume, finding.module)
                if secret:
                    modern_hash = modern_password_hash(secret)
            elif finding.present:
                reset_required = 1
            conn.execute(
                """INSERT OR REPLACE INTO legacy_security
                   (source_id,module,internal_file,offset,secret_present,storage,secret_length,fingerprint,modern_hash,reset_required)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (source_id, finding.module, finding.internal_file, finding.offset,
                 int(finding.present), finding.storage, finding.length, finding.fingerprint,
                 modern_hash, reset_required),
            )
        conn.commit()

    conn.close()
    return output_path
