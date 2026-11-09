"""Reusable Tkinter widgets and the RTL helper. No business logic lives here."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, Sequence


class Rtl:
    """Tk has no real RTL layout engine: flip pack sides, anchors and column order by hand."""

    def __init__(self, enabled: bool):
        self.on = enabled

    @property
    def start(self) -> str:       # side where a label/leading widget goes
        return tk.RIGHT if self.on else tk.LEFT

    @property
    def end(self) -> str:
        return tk.LEFT if self.on else tk.RIGHT

    @property
    def anchor(self) -> str:
        return tk.E if self.on else tk.W

    @property
    def justify(self) -> str:
        return tk.RIGHT if self.on else tk.LEFT

    def order(self, items: Sequence) -> list:
        return list(reversed(items)) if self.on else list(items)


class DataTable(ttk.Frame):
    """Treeview with a scrollbar; columns are reversed automatically in RTL."""

    def __init__(self, parent, rtl: Rtl, columns: Sequence[tuple[str, str, int]], height: int = 12,
                 on_select: Optional[Callable[[], None]] = None, on_double: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.rtl = rtl
        ordered = rtl.order(columns)
        self._ids = [c[0] for c in ordered]
        self.tree = ttk.Treeview(self, columns=self._ids, show="headings", height=height, selectmode="browse")
        for cid, title, width in ordered:
            self.tree.heading(cid, text=title, anchor=rtl.anchor)
            self.tree.column(cid, width=width, anchor=rtl.anchor, stretch=True)
        bar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side=rtl.start, fill=tk.BOTH, expand=True)
        bar.pack(side=rtl.end, fill=tk.Y)
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda _e: on_select())
        if on_double:
            self.tree.bind("<Double-1>", lambda _e: on_double())

    def set_rows(self, rows: Sequence[Sequence], iids: Optional[Sequence[str]] = None) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            self.tree.insert("", tk.END, iid=iids[i] if iids else None, values=self.rtl.order(list(row)))

    def selected(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def selected_values(self) -> Optional[list]:
        iid = self.selected()
        return self.rtl.order(list(self.tree.item(iid, "values"))) if iid else None

    def select(self, iid: str) -> None:
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)


class FormRow:
    @staticmethod
    def entry(parent, rtl: Rtl, label: str, var: Optional[tk.StringVar] = None, show: str = "",
              width: int = 28, row: Optional[int] = None) -> ttk.Entry:
        var = var or tk.StringVar()
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        ttk.Label(frame, text=label, width=18, anchor=rtl.anchor).pack(side=rtl.start)
        e = ttk.Entry(frame, textvariable=var, show=show, width=width, justify=rtl.justify)
        e.pack(side=rtl.start, padx=4)
        e.var = var                                 # type: ignore[attr-defined]
        return e


class Dialog(tk.Toplevel):
    """Modal dialog; subclasses build a body and call `self.close(result)`."""

    def __init__(self, parent, title: str, rtl: Rtl):
        super().__init__(parent)
        self.title(title)
        self.rtl = rtl
        self.result = None
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill=tk.BOTH, expand=True)
        self.bind("<Escape>", lambda _e: self.close(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self.close(None))

    def buttons(self, ok_text: str, cancel_text: str, on_ok: Callable[[], None]) -> None:
        bar = ttk.Frame(self.body)
        bar.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(bar, text=ok_text, command=on_ok).pack(side=self.rtl.start, padx=4)
        ttk.Button(bar, text=cancel_text, command=lambda: self.close(None)).pack(side=self.rtl.start, padx=4)
        self.bind("<Return>", lambda _e: on_ok())

    def show(self):
        self.update_idletasks()
        parent = self.master.winfo_toplevel()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.wait_window(self)
        return self.result

    def close(self, result=None) -> None:
        self.result = result
        self.grab_release()
        self.destroy()


def ask_values(parent, rtl: Rtl, title: str, fields: Sequence[tuple[str, str, bool]], ok: str, cancel: str,
               initial: Optional[dict[str, str]] = None) -> Optional[dict[str, str]]:
    """fields: (key, label, secret). Returns {key: text} or None."""
    dlg = Dialog(parent, title, rtl)
    entries: dict[str, ttk.Entry] = {}
    for key, label, secret in fields:
        entries[key] = FormRow.entry(dlg.body, rtl, label, show="*" if secret else "")
        if initial and key in initial:
            entries[key].var.set(initial[key])                                    # type: ignore[attr-defined]
    first = next(iter(entries.values()))
    dlg.after(50, first.focus_set)
    dlg.buttons(ok, cancel, lambda: dlg.close({k: e.var.get() for k, e in entries.items()}))   # type: ignore[attr-defined]
    return dlg.show()


def style_app(root: tk.Tk) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Total.TLabel", font=("Segoe UI", 26, "bold"))
    style.configure("Big.TButton", font=("Segoe UI", 12, "bold"), padding=8)
    style.configure("Pay.TButton", font=("Segoe UI", 14, "bold"), padding=12)
    style.configure("Nav.TButton", font=("Segoe UI", 11), padding=8)
    style.configure("Err.TLabel", foreground="#b00020")
    style.configure("Ok.TLabel", foreground="#1b5e20")
    style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
