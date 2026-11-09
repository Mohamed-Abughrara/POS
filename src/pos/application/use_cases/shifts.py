"""UC-02 OpenShift and UC-12 CloseShift."""
from __future__ import annotations

from dataclasses import replace

from ...domain.entities import Shift
from ...domain.errors import ShiftAlreadyOpen
from ...domain.money import Money
from ..dto import CloseShiftInput, OpenShiftInput, ShiftView, ZReport
from ..errors import ApprovalRequired, ParkedSalesExist
from ..permissions import Permission
from ..ports import PasswordHasher, ReceiptPrinter, ReportQueries
from .common import UowFactory, UseCase, resolve_approver
from .receipts import DEFAULT_SETTINGS, footer_text, header_lines, try_print


class ShiftUseCases(UseCase):
    def __init__(self, uow_factory: UowFactory, clock, ids, hasher: PasswordHasher,
                 printer: ReceiptPrinter, queries: ReportQueries):
        super().__init__(uow_factory, clock, ids)
        self._hasher = hasher
        self._printer = printer
        self._queries = queries

    def current(self, actor_id: str):
        with self._uow_factory() as uow:
            self._user(uow, actor_id, Permission.SHIFT)
            s = uow.shifts.get_open()
            return None if s is None else ShiftView(s.id, s.opened_at, s.opening_float.amount, s.cashier_id)

    def open_shift(self, inp: OpenShiftInput) -> ShiftView:
        with self._uow_factory() as uow:
            self._user(uow, inp.cashier_id, Permission.SHIFT)
            if uow.shifts.get_open() is not None:
                raise ShiftAlreadyOpen("a shift is already open on this till")
            shift = Shift(self._ids.new_id(), inp.cashier_id, self._clock.now(), Money(inp.opening_float))
            uow.shifts.save(shift)
            self._audit(uow, inp.cashier_id, "SHIFT_OPENED", "shift", shift.id, opening_float=inp.opening_float)
            uow.commit()
        try_print_drawer = getattr(self._printer, "open_drawer", None)
        if try_print_drawer:
            try:
                try_print_drawer()
            except Exception:  # noqa: BLE001 - drawer problems never block opening
                pass
        return ShiftView(shift.id, shift.opened_at, shift.opening_float.amount, shift.cashier_id)

    def close_shift(self, inp: CloseShiftInput) -> ZReport:
        with self._uow_factory() as uow:
            actor = self._user(uow, inp.actor_id, Permission.SHIFT)
            shift = uow.shifts.get(inp.shift_id)
            if shift is None or not shift.is_open:
                from ...domain.errors import ShiftNotOpen
                raise ShiftNotOpen("shift is not open")
            parked = uow.sales.list_parked(shift.id)
            approver = None
            if parked:
                if not inp.force_void_parked:
                    raise ParkedSalesExist(str(len(parked)))
                approver = resolve_approver(uow, self._hasher, actor, inp.approver_credentials)
                for s in parked:
                    s.void()
                    uow.sales.save(s)
                    self._audit(uow, actor.id, "VOID_SALE", "sale", s.id, reason="shift close")
            totals = self._queries.shift_totals(shift.id)
            expected = Money(shift.opening_float.amount + totals.cash_sales - totals.cash_refunds)
            counted = Money(inp.counted_cash)
            threshold = int(uow.settings.get("variance_threshold", DEFAULT_SETTINGS["variance_threshold"]))
            if abs(counted.amount - expected.amount) > threshold:
                try:
                    approver = resolve_approver(uow, self._hasher, actor, inp.approver_credentials)
                except ApprovalRequired:
                    raise
            shift.close(counted, expected, self._clock.now())
            uow.shifts.save(shift)
            cashier = uow.users.get(shift.cashier_id)
            self._audit(uow, actor.id, "SHIFT_CLOSED", "shift", shift.id, counted=counted.amount,
                        expected=expected.amount, variance=shift.variance.amount,
                        approver=approver.id if approver else None,
                        denominations=inp.denominations or {})
            uow.commit()
            report = ZReport(
                shift_id=shift.id, opened_at=shift.opened_at, closed_at=shift.closed_at,
                cashier_name=cashier.display_name if cashier else "", sales_count=totals.sales_count,
                gross=totals.gross, discounts=totals.discounts, tax=totals.tax, refunds=totals.refunds,
                net=totals.gross - totals.refunds, by_method=dict(totals.by_method),
                opening_float=shift.opening_float.amount, expected_cash=expected.amount,
                counted_cash=counted.amount, variance=shift.variance.amount,
                header=header_lines(uow), footer=footer_text(uow))
        printed = try_print(self._printer, report, False)
        return replace(report, printed=printed)
