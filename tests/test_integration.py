"""Controllers + container, persistence across restarts, kill-process durability, config, printing, i18n."""
import json
import re
import subprocess
import sys
import textwrap
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from pos.container import build
from pos.infrastructure.config.settings import load_config
from pos.infrastructure.demo import seed_demo
from pos.infrastructure.i18n.translator import JsonTranslator
from pos.infrastructure.printing.printers import FilePrinter, NullPrinter, build_printer
from pos.infrastructure.printing.render import render_document
from pos.infrastructure.security.hasher import DEFAULT_ITERATIONS, Pbkdf2Hasher
from pos.infrastructure.sqlite.connection import connect
from pos.infrastructure.sqlite.migrations import MIGRATIONS, current_version

SRC = Path(__file__).resolve().parents[1] / "src"


def make_box(tmp_path, printer=None):
    cfg = load_config(data_dir_override=tmp_path / "data")
    return build(cfg, printer=printer or NullPrinter(), hasher=Pbkdf2Hasher(iterations=1000))


def test_full_cashier_journey_through_controllers(tmp_path):
    box = make_box(tmp_path)
    assert box.seeded
    admin = box.auth_uc.login("admin", "admin123")
    seed_demo(box.admin_uc, box.catalogue_uc, admin.id)

    assert not box.auth.login("cashier", "nope").ok
    out = box.auth.login("cashier", "cashier123")
    assert out.ok and box.session.presenter.locale == "ar"          # per-user locale
    assert not box.checkout.scan("COLA330").ok                      # no shift yet -> localized Arabic error
    assert "وردية" in box.checkout.scan("COLA330").error
    assert box.shift.open("10").ok

    cart = box.checkout.scan("COLA330", "2")
    assert cart.ok and cart.value.total_raw == 1500
    assert box.checkout.scan("RICE", "1.250").value.total_raw == 1500 + 3000   # 1.25 kg * 2.4 = 3.000
    assert not box.checkout.pay_split("100", "", box.checkout.scan("BAG").value.total_raw).ok   # missing card ref (or invalid)
    total = box.checkout.scan("BREAD").value.total_raw
    paid = box.checkout.pay_cash("20", total)
    assert paid.ok and "الباقي" in paid.message
    assert box.checkout.sale_id is None                              # cart reset

    assert box.auth.toggle_locale().ok and box.session.presenter.locale == "en"
    assert box.auth.login("manager", "4321").ok
    rep = box.report.run("DAILY", datetime.now().date().isoformat(), datetime.now().date().isoformat())
    assert rep.ok and rep.value.rows and rep.value.columns[0] == "Date"
    assert box.report.export("DAILY", datetime.now().date().isoformat(), datetime.now().date().isoformat()).ok
    assert not box.report.run("DAILY", "bad", "2026-01-01").ok
    assert box.catalogue.low_stock().ok
    assert not box.admin.users().ok                                   # manager is not an admin
    assert box.auth.login("admin", "admin123").ok and box.admin.audit().value
    assert box.admin.backup_now().ok and box.admin.backups().value


def test_data_survives_restart_and_migrations_are_idempotent(tmp_path):
    box = make_box(tmp_path)
    admin = box.auth_uc.login("admin", "admin123")
    seed_demo(box.admin_uc, box.catalogue_uc, admin.id)
    box.conn.close()
    again = make_box(tmp_path)
    assert again.seeded is False
    assert len(again.catalogue_uc.search_products(admin.id, "", True)) == 6
    assert current_version(again.conn) == len(MIGRATIONS)


def test_committed_sale_survives_killed_process(tmp_path):
    db = tmp_path / "crash.db"
    script = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, r"{SRC}")
        from datetime import datetime
        from decimal import Decimal
        from pos.application.dto import *
        from pos.infrastructure.sqlite.connection import connect
        from pos.infrastructure.sqlite.uow import uow_factory
        from pos.infrastructure.sqlite.queries import SqliteReportQueries
        from pos.infrastructure.security.hasher import Pbkdf2Hasher
        from pos.infrastructure.printing.printers import NullPrinter
        from pos.infrastructure.system import SystemClock, UuidGenerator
        from pos.application.use_cases.admin import SeedDefaults
        from pos.application.use_cases.catalogue import CatalogueUseCases
        from pos.application.use_cases.checkout import CheckoutUseCases
        from pos.application.use_cases.shifts import ShiftUseCases
        conn = connect(r"{db}")
        u, c, i, h = uow_factory(conn), SystemClock(), UuidGenerator(), Pbkdf2Hasher(1000)
        SeedDefaults(u, c, i, h).run()
        with u() as t:
            admin = t.users.get_by_username("admin").id
        cat = CatalogueUseCases(u, c, i)
        cat.save_product(admin, ProductView(None, "X", None, "x", "x", None, 1000))
        ShiftUseCases(u, c, i, h, NullPrinter(), SqliteReportQueries(conn)).open_shift(OpenShiftInput(admin, 0))
        co = CheckoutUseCases(u, c, i, h, NullPrinter())
        cart = co.scan_item(ScanItemInput(admin, None, "X"))
        co.complete_sale(CompleteSaleInput(admin, cart.sale_id, [PaymentInput("CASH", 1000)]))
        os._exit(0)      # hard kill: no close(), no checkpoint
    """)
    subprocess.run([sys.executable, "-I", "-c", script], check=True, timeout=60)
    conn = connect(db)
    row = conn.execute("SELECT number, status, total FROM sales").fetchone()
    assert (row["number"], row["status"], row["total"]) == (1, "COMPLETED", 1000)
    assert conn.execute("SELECT SUM(qty_milli) FROM stock_movements").fetchone()[0] == -1000
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_hasher_meets_nfr08():
    assert DEFAULT_ITERATIONS >= 600_000
    h = Pbkdf2Hasher(iterations=1000)
    a, b = h.hash("secret"), h.hash("secret")
    assert a != b and h.verify("secret", a) and not h.verify("Secret", a)
    assert not h.verify("x", "garbage") and not h.verify("x", "md5$1$00$00")


def test_config_defaults_and_overrides(tmp_path):
    cfg = load_config(data_dir_override=tmp_path)
    assert cfg.printer.backend == "file" and cfg.db_path.parent == tmp_path and (tmp_path / "config.toml").exists()
    (tmp_path / "config.toml").write_text('default_locale = "ar"\n[printer]\nbackend = "null"\nwidth = 32\n', encoding="utf-8")
    cfg = load_config(data_dir_override=tmp_path)
    assert cfg.default_locale == "ar" and cfg.printer.width == 32 and cfg.printer.backend == "null"
    assert isinstance(build_printer(cfg.printer, tmp_path), NullPrinter)


def test_receipt_rendering_and_file_printer(tmp_path):
    box = make_box(tmp_path, printer=FilePrinter(tmp_path / "r", 40))
    admin = box.auth_uc.login("admin", "admin123")
    seed_demo(box.admin_uc, box.catalogue_uc, admin.id)
    box.auth.login("admin", "admin123")
    box.shift.open("5")
    box.checkout.scan("SOAP", "2")
    out = box.checkout.pay_cash("30", 2 * 1250 + 125)
    assert out.ok
    files = list((tmp_path / "r").glob("*saleReceipt*.txt")) or list((tmp_path / "r").glob("*.txt"))
    text = files[0].read_text(encoding="utf-8")
    assert "Soap bar" in text and "2.625" in text and "TOTAL" in text and "Change" in text
    with pytest.raises(TypeError):
        render_document(object())


def test_translations_are_complete_and_consistent():
    en = json.loads((SRC / "pos/infrastructure/i18n/en.json").read_text(encoding="utf-8"))
    ar = json.loads((SRC / "pos/infrastructure/i18n/ar.json").read_text(encoding="utf-8"))
    assert set(en) == set(ar), set(en) ^ set(ar)
    for key in en:                                    # same placeholders in both languages
        assert re.findall(r"\{(\w+)\}", en[key]) == re.findall(r"\{(\w+)\}", ar[key]), key
    # every error class has a message
    import pos.application.errors as app_errors
    import pos.domain.errors as dom_errors
    for mod in (app_errors, dom_errors):
        for name, cls in vars(mod).items():
            if isinstance(cls, type) and issubclass(cls, Exception) and name not in ("AppError", "DomainError"):
                assert f"err.{name}" in en, name
    # every translation key referenced from the UI / presenters exists
    pattern = re.compile(r"""["']((?:ok|cancel|save|yes|no|app|login|lock|approval|nav|checkout|customer|pay|refund|shift|cat|stock|report|admin|audit|backup|setting|col|method|role|z|msg|err)(?:\.[A-Za-z_]+)?)["']""")
    missing = set()
    for path in list((SRC / "pos/ui_tkinter").rglob("*.py")) + [SRC / "pos/adapters/presenters.py", SRC / "pos/adapters/controllers.py"]:
        for key in pattern.findall(path.read_text(encoding="utf-8")):
            if "." in key and key not in en:
                missing.add((path.name, key))
    assert not missing, sorted(missing)
    tr = JsonTranslator("ar")
    assert tr.t("msg.change_due", change="1.000") == "الباقي: 1.000." and tr.t("nope.key") == "nope.key"


def test_layer_boundaries_without_import_linter():
    """Cheap in-test version of the CI import-linter contracts (NFR-11)."""
    bad = []
    def imports(path):
        return re.findall(r"^\s*(?:from|import)\s+([\w.]+)", path.read_text(encoding="utf-8"), re.M)
    for path in (SRC / "pos/domain").rglob("*.py"):
        for mod in imports(path):
            if mod.startswith(("pos.", "tkinter", "sqlite3")) or mod.startswith("..") :
                bad.append((path.name, mod))
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"from \.\.(application|adapters|infrastructure|ui_tkinter)", text), path
    for path in (SRC / "pos/application").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(tkinter|sqlite3|\.\.adapters|\.\.infrastructure|\.\.ui_tkinter|\.\.\.adapters|\.\.\.infrastructure|\.\.\.ui_tkinter)", text), path
    for path in (SRC / "pos/adapters").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(tkinter|sqlite3|\.\.infrastructure|\.\.ui_tkinter)", text), path
    assert not bad
