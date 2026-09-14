from __future__ import annotations

import argparse
import json
from pathlib import Path

from .exporter import export_accounts_csv, export_to_sqlite
from .security import audit_volume_security
from .volume import CashLinkVolume


def _scan(path: Path) -> dict:
    volume = CashLinkVolume(path)
    return {
        "path": str(path),
        "volume_name": volume.volume_name,
        "size_bytes": path.stat().st_size,
        "files": [
            {
                "name": e.name,
                "first_block": e.first_block,
                "last_block": e.last_block,
                "logical_size": e.logical_size,
                "complete": e.complete,
            }
            for e in volume.entries
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cashlink-recover",
        description="Recover and migrate legacy CashLink Accountant data safely.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Inspect one or more CashLink volumes")
    scan.add_argument("sources", nargs="+", type=Path)

    extract = sub.add_parser("extract", help="Extract logical files from a volume")
    extract.add_argument("source", type=Path)
    extract.add_argument("--out", required=True, type=Path)

    accounts = sub.add_parser("export-accounts", help="Export known account master fields to CSV")
    accounts.add_argument("source", type=Path)
    accounts.add_argument("--out", required=True, type=Path)

    security = sub.add_parser("security-audit", help="Report password presence without disclosing secrets")
    security.add_argument("sources", nargs="+", type=Path)

    sqlite_cmd = sub.add_parser("to-sqlite", help="Preserve raw data and decoded fields in SQLite")
    sqlite_cmd.add_argument("output", type=Path)
    sqlite_cmd.add_argument("sources", nargs="+", type=Path)
    sqlite_cmd.add_argument(
        "--migrate-legacy-passwords",
        action="store_true",
        help="Re-hash detected module passwords directly into SQLite; plaintext is never printed or stored.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        print(json.dumps([_scan(path) for path in args.sources], indent=2))
        return 0
    if args.command == "extract":
        volume = CashLinkVolume(args.source)
        for path in volume.extract_all(args.out):
            print(path)
        return 0
    if args.command == "export-accounts":
        volume = CashLinkVolume(args.source)
        for path in export_accounts_csv(volume, args.out):
            print(path)
        return 0
    if args.command == "security-audit":
        findings = []
        for source in args.sources:
            volume = CashLinkVolume(source)
            findings.extend(finding.to_dict() for finding in audit_volume_security(volume))
        print(json.dumps(findings, indent=2))
        return 0
    if args.command == "to-sqlite":
        export_to_sqlite(
            args.sources,
            args.output,
            migrate_legacy_passwords=args.migrate_legacy_passwords,
        )
        print(args.output)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
