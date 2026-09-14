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

CashLink's program also contains explicit references to `SECURITY.DAT`, including `ERROR: opening SECURITY.DAT file`, `Invalid ID and PASSWORD!!`, supervisor-password prompts, operator numbers and access-right messages. This strongly indicates that `SECURITY.EXE` was a management utility while operator IDs/passwords/access rights were normally stored in a separate `SECURITY.DAT` file.

If only `SECURITY.EXE` survives, it is still valuable: reverse-engineering it may reveal the `SECURITY.DAT` record layout, password comparison/encoding routine, access-right bit fields and whether any defaults or fallback credentials were embedded in the executable.

## Recovery principle

Never modify the original CashLink files. Work on copies, retain hashes of source files, preserve raw logical files/records in SQLite, and layer decoded fields on top. This permits later decoder improvements without repeating the original media recovery.
