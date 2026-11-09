# SouqPOS

Offline-first desktop point of sale for a single shop. Python 3.11, Tkinter/ttk, SQLite, Clean Architecture
(built from `SouqPOS — Preliminary Design Review (PDR).md`).

## Run

```
python main.py --demo          # first run: adds demo users and sample products
python main.py                 # normal start
python main.py --data-dir D:\souq   # keep database/config/backups/logs elsewhere
```

No third-party runtime dependencies. Data lives in `%LOCALAPPDATA%\SouqPOS` (database, `config.toml`, `backups\`,
`receipts\`, `exports\`, `logs\`).

Default accounts (**change these**): `admin` / `admin123`. With `--demo`: `manager` / `manager123` (PIN 4321),
`cashier` / `cashier123` (PIN 1234). Any user can sign in with the password or the PIN.

Keys on the checkout screen: F2 scan box, F3 find product, F4 quantity, F5 line discount, F6 cart discount,
F7 customer, F8 park, F9 recall, F10/Del remove line, F11 void, F12 pay. Type `3*<barcode>` to scan a quantity.

## Develop

```
pip install -r requirements-dev.txt
python -m pytest                      # unit, integration, UI smoke
python -m pytest -m benchmark -s      # NFR-01..03 timings
python -m pytest --cov=pos            # coverage (UI excluded)
set PYTHONPATH=src && lint-imports    # layer contracts (NFR-11)
```

## Layout

```
main.py                         entry point
src/pos/container.py            composition root (wires every concrete class)
src/pos/domain/                 Money, Quantity, Barcode, TaxRate, Discount, Sale, Refund, Shift, ...
src/pos/application/            use cases UC-01..UC-14, ports, DTOs, permissions
src/pos/adapters/               controllers, presenters, formatting (no tkinter / sqlite3)
src/pos/infrastructure/         sqlite (repos, UoW, migrations, queries, backup), printing, security, config, i18n
src/pos/ui_tkinter/             app shell, screens, RTL helper, widgets
tests/
```

## Decisions and deviations from the PDR

- SQLite repositories and the Unit of Work live in `infrastructure/sqlite` (not `adapters`): the PDR forbids
  `sqlite3` outside infrastructure/UI/main, so the repositories that use it have to live there.
- Use-case tests run against an in-memory SQLite database through the real repositories instead of hand-written
  in-memory fakes. It exercises the SQL, triggers and transactions as well as the business rules.
- `synchronous=NORMAL` (as in PDR 5.6) with WAL never corrupts the database and survives a killed process, but the
  last commits can be lost on a sudden OS crash or power cut. If NFR-04 must hold for power loss, change it to `FULL`
  in `infrastructure/sqlite/connection.py` (small write-speed cost).
- Quantities are stored as integer thousandths (exact for KG items); money as integer dirhams.
- Completed sales, the audit log and stock movements are protected by database triggers as well as domain rules.
- PDR sections after 5.7 (data model, plan, risks) were not in the provided file; the schema is derived from the
  entity tables in 5.2.
- Receipts: default backend writes UTF-8 `.txt` files to `receipts\`. USB/network ESC/POS needs `python-escpos`
  and has not been tried on real hardware; Arabic on thermal printers depends on the printer's code page
  (no glyph shaping is done).
- Tkinter has no real RTL layout. Arabic mode mirrors layouts, columns and alignment by hand and relies on the
  platform Tk for glyph shaping (PDR risk: limited RTL support). Check it on the target OS.
- Cash drawer is kicked through the receipt printer; the file backend only logs the kick.
