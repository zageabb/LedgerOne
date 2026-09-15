import subprocess
import sys


def test_ledger_service_can_be_imported_without_application_factory_cycle():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ledgerone.services.ledger import LedgerService; print(LedgerService.__name__)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "LedgerService" in result.stdout
