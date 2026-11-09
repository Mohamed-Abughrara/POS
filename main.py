"""SouqPOS entry point (composition root). Usage: python main.py [--data-dir DIR] [--demo]"""
from __future__ import annotations

import argparse
import logging
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pos.container import load_and_build                      # noqa: E402
from pos.infrastructure.demo import seed_demo                 # noqa: E402
from pos.ui_tkinter.app import App, Controllers               # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SouqPOS point of sale")
    parser.add_argument("--data-dir", type=Path, help="folder for the database, config, backups and logs")
    parser.add_argument("--demo", action="store_true", help="add demo users and sample products")
    args = parser.parse_args(argv)

    box = load_and_build(args.data_dir)
    log = logging.getLogger("souqpos")
    log.info("SouqPOS started, database %s", box.config.db_path)
    if args.demo:
        try:
            admin = box.auth_uc.login("admin", "admin123")
        except Exception:                                    # noqa: BLE001 - admin password was changed
            print("--demo needs the default admin account (admin/admin123); skipped.")
        else:
            seed_demo(box.admin_uc, box.catalogue_uc, admin.id)

    root = tk.Tk()
    controllers = Controllers(box.auth, box.checkout, box.refund, box.shift, box.catalogue, box.report, box.admin)

    def scheduled_backup() -> None:
        box.admin_uc.backup_now(None)

    App(root, box.session, controllers, scheduled_backup, box.config.backup_interval_hours)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
