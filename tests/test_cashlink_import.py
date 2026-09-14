from pathlib import Path

import pytest

from legacy_import.cashlink.accounts import iter_ledger_accounts, iter_nominal_accounts
from legacy_import.cashlink.security import audit_volume_security
from legacy_import.cashlink.volume import CashLinkVolume


def _fixture(name: str) -> Path:
    path = Path(__file__).parent / "fixtures" / name
    if not path.exists():
        pytest.skip(f"CashLink fixture not present: {name}")
    return path


def test_journal_directory():
    volume = CashLinkVolume(_fixture("JOURNAL.VOL"))
    names = {entry.name for entry in volume.entries}
    assert {"ACCS.PURCH", "ACCS.SALES", "ACCS.NOM", "TRANS.NOM"} <= names


def test_accounts_decode():
    volume = CashLinkVolume(_fixture("JOURNAL.VOL"))
    purchase = list(iter_ledger_accounts(volume.read_file("ACCS.PURCH"), "purchase"))
    sales = list(iter_ledger_accounts(volume.read_file("ACCS.SALES"), "sales"))
    nominal = list(iter_nominal_accounts(volume.read_file("ACCS.NOM")))
    assert purchase
    assert sales
    assert nominal


def test_security_report_never_contains_plaintext_field():
    volume = CashLinkVolume(_fixture("JOURNAL.VOL"))
    findings = audit_volume_security(volume)
    assert {f.module for f in findings} == {"purchase", "sales", "nominal"}
    assert all(f.fingerprint for f in findings if f.present)
    assert all(set(f.masked) <= {"*"} for f in findings)
