# CashLink legacy format notes

## Confirmed container format

The supplied CashLink datasets are UCSD p-System style block volumes:

- block size: 512 bytes
- volume directory begins at block 2 (offset 1024)
- directory entry size: 26 bytes
- logical files are contiguous block ranges
- the final-block byte count is stored in directory bytes 22-23

`PROGRAM.VOL` contains the p-System runtime and CashLink program. The journal and job-cost volumes contain accounting data files.

## Complete surviving directory supplied for recovery

The complete surviving CashLink folder supplied for this recovery contains 14 files:

- `CASHLINK.COM`
- `FIXFIRST.EXE`
- `SECURITY.EXE`
- duplicate copy `SECURITY(1).EXE`
- `PROGRAM.VOL`
- `NEWDATA.VOL`
- `JOURNAL.VOL`
- `JOURNAL.BAK`
- `JOURNAL.MIK`
- `JOURNAL.OLD`
- `JOURNAL.STE`
- `JOBCOST.DAT`
- `JOBCOST.BAK`
- `JOBCOST.IDX`

`SECURITY.EXE` and `SECURITY(1).EXE` are byte-for-byte identical. No `SECURITY.DAT`, `ORDER.DAT` or separate `STOCK.VOL` survives in this directory.

### Backup-manifest evidence

The first reserved blocks of the June/July 2020 journal backup images contain CashLink backup manifests for `BENNETTS TRAVEL (CRANBERRY) LTD`, sourced from `C:\BENNETT\`.

Those manifests explicitly list only:

- `JOURNAL.VOL`
- `JOBCOST.DAT`
- `JOBCOST.IDX`

This is strong evidence that the normal CashLink company-data backup process did **not** include `SECURITY.DAT`. The operator security database was therefore probably installation-level/shared configuration, potentially located elsewhere from the company data directory.

The surviving generations also establish useful chronology:

- `JOURNAL.STE`: accounting period field around 1 Oct 2000
- `JOURNAL.OLD`: accounting period field around 30 Apr 2002
- `JOURNAL.BAK`: accounting period field around 31 Jul 2020
- `JOURNAL.VOL`: accounting period field around 30 Apr 2022

`JOURNAL.MIK` is not an independent generation: it is an exact byte-for-byte prefix of `JOURNAL.BAK` and stops after 1,457,664 bytes. Its directory still describes the full journal, but the physical file truncates part-way through `TRANS.NOM`; purchase, stock and nominal-account data before that point remain recoverable, while later sales-ledger files are absent from the truncated image.

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

The same three module credentials persist across the 2000, 2002, 2020 and 2022 journal generations, which is a strong indication that these fields are genuine long-lived CashLink module passwords rather than incidental text.

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

The CLI now includes:

```bash
python -m legacy_import.cashlink security-dat-audit SECURITY.DAT
```

for use if a surviving `SECURITY.DAT` is found elsewhere.

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

`FIXFIRST.EXE` is a Borland/Turbo Pascal maintenance utility, with source-unit/debug strings including `FIXFIRST.PAS`, `CLINK.PAS`, `CL_MULTI.PAS` and `CL_TYPES.PAS`. It directly references the CashLink accounting files and many of their Pascal record-field names, including `FIRSTTRANS`, `LASTTRANS`, `NEXT_TRANS`, `PREV_TRANS`, `NOM_TRANS`, purchase/sales/stock transaction structures and `JOBCOST.DAT`.

Its code iterates account/transaction records and manipulates transaction-pointer fields. The strongest interpretation is that it was a repair/conversion utility for rebuilding or resetting first/last transaction links rather than part of normal day-to-day accounting. It is valuable as a reverse-engineering reference because it retains numerous original Pascal field names and record structures.

The executable contains a hard-coded reference to `D:\CL\JOURNAL.VOL`, another indication that the software could operate with data outside the `C:\BENNETT\` company-data folder.

## Recovery principle

Never modify the original CashLink files. Work on copies, retain hashes of source files, preserve raw logical files/records in SQLite, and layer decoded fields on top. This permits later decoder improvements without repeating the original media recovery.
