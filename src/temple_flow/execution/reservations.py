"""Concurrent cash reservations. One dollar cannot be spent twice."""

from __future__ import annotations

from decimal import Decimal

from temple_flow.ledger.store import LedgerStore
from temple_flow.money import amount, dstr


class ReservationError(ValueError):
    """Cash could not be reserved."""


def reserve_cash(
    store: LedgerStore,
    venue: str,
    account_alias: str,
    debit: Decimal,
    reservation_id: str,
    intent_id: str,
) -> None:
    if debit <= 0:
        raise ReservationError("reservation must be positive")
    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute(
            "SELECT available_decimal, reserved_decimal FROM cash_balances WHERE venue=? AND account_alias=?",
            (venue, account_alias),
        ).fetchone()
        avail = amount(row[0]) if row else Decimal("0")
        reserved = amount(row[1]) if row else Decimal("0")
        if avail < debit:
            raise ReservationError(
                f"insufficient_funded_cash available={dstr(avail)} need={dstr(debit)}"
            )
        new_avail = avail - debit
        new_reserved = reserved + debit
        db.execute(
            """INSERT INTO cash_balances(venue, account_alias, available_decimal, reserved_decimal)
               VALUES (?,?,?,?)
               ON CONFLICT(venue, account_alias) DO UPDATE SET
                 available_decimal=excluded.available_decimal,
                 reserved_decimal=excluded.reserved_decimal""",
            (venue, account_alias, dstr(new_avail), dstr(new_reserved)),
        )
        db.execute(
            """INSERT INTO reservations
               (reservation_id, intent_id, resource_key, amount_decimal, state, exclusive_group_id)
               VALUES (?,?,?,?,?,NULL)""",
            (
                reservation_id,
                intent_id,
                f"cash:{venue}:{account_alias}",
                dstr(debit),
                "held",
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
