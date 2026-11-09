"""Builds every Tk screen against a real container to catch wiring errors (skipped without a display)."""
import tkinter as tk

import pytest

from pos.application.permissions import Permission
from pos.container import build
from pos.infrastructure.config.settings import load_config
from pos.infrastructure.demo import seed_demo
from pos.infrastructure.printing.printers import NullPrinter
from pos.infrastructure.security.hasher import Pbkdf2Hasher
from pos.ui_tkinter.app import NAV, App, Controllers


@pytest.fixture
def ui(tmp_path):
    root = None
    for _ in range(3):                      # Tk creation is occasionally flaky on Windows
        try:
            root = tk.Tk()
            break
        except tk.TclError:
            import time
            time.sleep(0.3)
    if root is None:
        pytest.skip("no display available")
    root.withdraw()
    box = build(load_config(data_dir_override=tmp_path), printer=NullPrinter(), hasher=Pbkdf2Hasher(1000))
    admin = box.auth_uc.login("admin", "admin123")
    seed_demo(box.admin_uc, box.catalogue_uc, admin.id)
    controllers = Controllers(box.auth, box.checkout, box.refund, box.shift, box.catalogue, box.report, box.admin)
    app = App(root, box.session, controllers)
    yield app, box
    root.destroy()


@pytest.mark.parametrize("user,secret,locale", [("admin", "admin123", "en"), ("cashier", "cashier123", "ar"),
                                                ("manager", "manager123", "en")])
def test_every_screen_builds_for_each_role(ui, user, secret, locale):
    app, box = ui
    assert box.auth.login(user, secret).ok
    app.build_shell()
    assert app.session.presenter.locale == locale
    for key, _label, perm, _cls in NAV:
        if app.session.can(perm):
            app.show(key)
            app.root.update()
    # nav hides screens the role may not use
    assert (("admin" in app.nav_buttons) == (user == "admin"))


def test_checkout_screen_scan_pay_flow(ui):
    app, box = ui
    box.auth.login("admin", "admin123")
    app.build_shell()
    app.show("shift")
    app.screen.amount.var.set("10")
    app.screen.open()
    app.root.update()
    app.show("checkout")
    screen = app.screen
    screen.scan_var.set("2*COLA330")
    screen._on_scan()
    screen.scan_var.set("nonexistent")
    screen._on_scan()
    assert "not found" in app.status_var.get().lower()
    assert screen.cart.total == "1.500 LYD" and len(screen.cart.lines) == 1
    out = box.checkout.pay_cash("2", screen.cart.total_raw)
    assert out.ok and "0.500" in out.message
    screen._render(None)
    app.toggle_locale()                       # rebuild whole UI in Arabic (RTL)
    app.show("reports")
    app.root.update()
    assert app.rtl.on
