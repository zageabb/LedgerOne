# CashLink legacy format notes

## Confirmed container format

The supplied CashLink datasets are UCSD p-System style block volumes:

- block size: 512 bytes
- volume directory begins at block 2 (offset 1024)
- directory entry size: 26 bytes
- logical files are contiguous block ranges
- the final-block byte count is stored in directory bytes 22-23

`PROGRAM.VOL` contains the p-System runtime and CashLink program. The journal and job-cost volumes contain accounting data files.

## Confirmed logical files

Main journal includes purchase, sales, nominal ledger, stock and invoicing files including:

- `ACCS.PURCH`, `TRANS.PURCH`, `ANAL.PURCH`
- `ACCS.SALES`, `TRANS.SALES`, `ANAL.SALES`
- `ACCS.NOM`, `TRANS.NOM`
- `INFO.PURCH`, `INFO.SALES`, `INFO.NOM`, `INFO.STOCK`
- stock, department, group and invoice files

Job costing includes:

- `ACCS.JOB`, `TRANS.JOB`, `INFO.JOB`
- `ANAL.JOB`, `EMPL.JOB`, `NUM.JOB`, `STAGE.JOB`

## Confirmed record sizes

- `ACCS.PURCH`: 380 bytes
- `ACCS.SALES`: 380 bytes
- `ACCS.NOM`: 64 bytes
- `TRANS.PURCH`: 128 bytes
- `TRANS.SALES`: 128 bytes
- `TRANS.NOM`: 56 bytes

The recovery database preserves every fixed record as a BLOB even where individual fields have not yet been decoded.

## Account fields decoded so far

For purchase/sales account records:

- offset 0: Pascal string containing account name/address components separated by `~`
- offset 150: telephone field 1
- offset 170: telephone field 2
- offset 210: alpha/index code

For nominal accounts:

- offset 0: Pascal account-description string
- record number acts as the legacy account slot/number

Unknown fields remain preserved in raw form.

## Security/password handling

Three module password fields are confirmed in the supplied journal snapshots:

- purchase ledger: `INFO.PURCH`
- sales ledger: `INFO.SALES`
- nominal ledger: `INFO.NOM`

They are stored as cleartext Pascal short strings in the legacy data. LedgerOne's migration path does not display, log, CSV-export, or store those secrets as plaintext. It can read each value in memory and immediately convert it to a modern salted scrypt hash, so users can continue using the same password without needing to remember or re-enter it during migration.

## SECURITY.EXE and SECURITY.DAT

Static analysis of the supplied `SECURITY.EXE` confirms it is the standalone CashLink security-management program, identifying itself as:

- `CashLink Security Release 4.1`
- `Hotelier Plus Security 4.03 UK`
- Borland/Turbo Pascal-era DOS executable

It explicitly opens/creates `SECURITY.DAT`. The program displays the following warning when the file is absent:

- `WARNING : SECURITY.DAT does not exist.`
- `Create New File`
- security features are enabled automatically when a new file is created
- at least one operator class with access rights must then be configured

The user-list/report screens include `ID`, `Name` and `Password`, and the edit code compares existing passwords to prevent duplicates. This indicates that operator passwords are stored in a recoverable representation rather than a one-way hash.

### Inferred SECURITY.DAT operator record layout

Machine-code analysis of CashLink Security 4.1 gives a strong 128-byte fixed-record layout:

| Offset | Size | Meaning |
| ---: | ---: | --- |
| 0 | 4 | Pascal `string[3]` operator ID |
| 4 | 30 | Pascal `string[29]` operator name |
| 34 | 10 | Pascal `string[9]` operator password |
| 44 | 32 | access-rights bitfield / option block |
| 76 | 2 | default printer number (little-endian word) |
| 78 | 50 | reserved / future-version fields |

The file creation routine uses a record size of `0x80` (128 bytes), and local work buffers are sized in 128-byte multiples. The executable also appears to provision up to 255 operator slots. These findings are sufficiently strong to support a parser, but should remain marked as inferred until a real `SECURITY.DAT` is available for validation.

`legacy_import/cashlink/security_dat.py` implements this inferred layout. Its normal parse API returns the ID, name, masked-password metadata, access-right bytes and printer number. The plaintext password is exposed only to the trusted in-memory migration function so it can be immediately re-hashed for LedgerOne.

A scan of the supplied `SECURITY.EXE` found no embedded records matching the inferred operator-record structure and no customer-specific operator names. Current evidence therefore indicates that the EXE contains the security program and templates, while live operator records lived in `SECURITY.DAT`.

The security utility allows an alternative path to be entered for `SECURITY.DAT`, so an old live installation may have stored it outside the directory from which these backup files were recovered.

## Other supplied executables

### CASHLINK.COM

`CASHLINK.COM` is a DOS COM bootstrap for the p-System environment. It references:

- `PROGRAM.VOL`
- `SYSTEM.CONFIG`
- `SYSTEM.PME.87`
- `DOSVV.DRV`

and includes a 1989 Cabot Software Ltd. copyright notice. This confirms that CashLink used a DOS-hosted p-System runtime to load the Pascal application volume.

### FIXFIRST.EXE

`FIXFIRST.EXE` is a Borland/Turbo Pascal maintenance utility, with source-unit/debug strings including `FIXFIRST.PAS`. It directly references the CashLink accounting files and many of their Pascal record-field names, including `FIRSTTRANS`, `LASTTRANS`, `NEXT_TRANS`, `PREV_TRANS`, `NOM_TRANS`, purchase/sales/stock transaction structures and `JOBCOST.DAT`.

Its code iterates account/transaction records and manipulates transaction-pointer fields. The strongest interpretation is that it was a repair/conversion utility for rebuilding or resetting first/last transaction links rather than part of normal day-to-day accounting. It is valuable as a reverse-engineering reference because it retains numerous original Pascal field names and record structures.

## Recovery principle

Never modify the original CashLink files. Work on copies, retain hashes of source files, preserve raw logical files/records in SQLite, and layer decoded fields on top. This permits later decoder improvements without repeating the original media recovery.
