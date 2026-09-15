from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ledgerone.extensions import db
from ledgerone.models.ledger import Account, Journal, JournalLine
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerError


ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


class FinancialReportingService:
    """Date-aware financial statements built only from posted ledger entries."""

    @staticmethod
    def _assert_context(context: AccessContext) -> None:
        if not context.organisation_id:
            raise LedgerError("An organisation is required")

    @staticmethod
    def _validate_range(from_date: date | None, to_date: date | None) -> None:
        if from_date and to_date and to_date < from_date:
            raise LedgerError("Report end date cannot be before start date")

    @staticmethod
    def _balances(
        context: AccessContext,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict]:
        FinancialReportingService._assert_context(context)
        FinancialReportingService._validate_range(from_date, to_date)

        query = (
            db.session.query(
                JournalLine.account_id,
                db.func.coalesce(db.func.sum(JournalLine.debit), 0).label("debit"),
                db.func.coalesce(db.func.sum(JournalLine.credit), 0).label("credit"),
            )
            .join(Journal, Journal.id == JournalLine.journal_id)
            .filter(
                Journal.organisation_id == context.organisation_id,
                Journal.status == "posted",
            )
        )
        if from_date:
            query = query.filter(Journal.journal_date >= from_date)
        if to_date:
            query = query.filter(Journal.journal_date <= to_date)
        totals = {
            row.account_id: (_money(row.debit), _money(row.credit))
            for row in query.group_by(JournalLine.account_id).all()
        }

        accounts = (
            Account.query.filter_by(organisation_id=context.organisation_id)
            .order_by(Account.code.asc())
            .all()
        )
        rows = []
        for account in accounts:
            debit, credit = totals.get(account.id, (ZERO, ZERO))
            rows.append(
                {
                    "id": account.id,
                    "code": account.code,
                    "name": account.name,
                    "account_type": account.account_type,
                    "debit": debit,
                    "credit": credit,
                    "balance": debit - credit,
                }
            )
        return rows

    @staticmethod
    def trial_balance(
        context: AccessContext,
        *,
        as_of: date | None = None,
        from_date: date | None = None,
    ) -> dict:
        as_of = as_of or date.today()
        rows = FinancialReportingService._balances(
            context,
            from_date=from_date,
            to_date=as_of,
        )
        total_debit = sum((row["debit"] for row in rows), ZERO)
        total_credit = sum((row["credit"] for row in rows), ZERO)
        return {
            "from_date": from_date,
            "as_of": as_of,
            "mode": "movement" if from_date else "cumulative",
            "rows": rows,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "difference": total_debit - total_credit,
        }

    @staticmethod
    def _profit_loss_core(
        context: AccessContext,
        *,
        from_date: date,
        to_date: date,
    ) -> dict:
        rows = FinancialReportingService._balances(
            context,
            from_date=from_date,
            to_date=to_date,
        )
        income = [row for row in rows if row["account_type"] == "income"]
        expenses = [row for row in rows if row["account_type"] == "expense"]
        total_income = sum((-row["balance"] for row in income), ZERO)
        total_expenses = sum((row["balance"] for row in expenses), ZERO)
        return {
            "from_date": from_date,
            "to_date": to_date,
            "income": income,
            "expenses": expenses,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_profit": total_income - total_expenses,
        }

    @staticmethod
    def profit_and_loss(
        context: AccessContext,
        *,
        from_date: date,
        to_date: date,
        compare_from: date | None = None,
        compare_to: date | None = None,
    ) -> dict:
        FinancialReportingService._validate_range(from_date, to_date)
        if bool(compare_from) != bool(compare_to):
            raise LedgerError("Comparative P&L requires both compare_from and compare_to")
        current = FinancialReportingService._profit_loss_core(
            context,
            from_date=from_date,
            to_date=to_date,
        )
        if compare_from and compare_to:
            FinancialReportingService._validate_range(compare_from, compare_to)
            current["comparative"] = FinancialReportingService._profit_loss_core(
                context,
                from_date=compare_from,
                to_date=compare_to,
            )
        else:
            current["comparative"] = None
        return current

    @staticmethod
    def _balance_sheet_core(context: AccessContext, *, as_of: date) -> dict:
        rows = FinancialReportingService._balances(context, to_date=as_of)
        assets = [row for row in rows if row["account_type"] == "asset"]
        liabilities = [row for row in rows if row["account_type"] == "liability"]
        equity = [row for row in rows if row["account_type"] == "equity"]
        income = [row for row in rows if row["account_type"] == "income"]
        expenses = [row for row in rows if row["account_type"] == "expense"]

        total_assets = sum((row["balance"] for row in assets), ZERO)
        total_liabilities = sum((-row["balance"] for row in liabilities), ZERO)
        posted_equity = sum((-row["balance"] for row in equity), ZERO)
        cumulative_income = sum((-row["balance"] for row in income), ZERO)
        cumulative_expenses = sum((row["balance"] for row in expenses), ZERO)
        current_earnings = cumulative_income - cumulative_expenses
        total_equity = posted_equity + current_earnings
        net_assets = total_assets - total_liabilities

        return {
            "as_of": as_of,
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "posted_equity": posted_equity,
            "current_earnings": current_earnings,
            "total_equity": total_equity,
            "net_assets": net_assets,
            "balance_check": total_assets - total_liabilities - total_equity,
        }

    @staticmethod
    def balance_sheet(
        context: AccessContext,
        *,
        as_of: date,
        compare_as_of: date | None = None,
    ) -> dict:
        current = FinancialReportingService._balance_sheet_core(context, as_of=as_of)
        current["comparative"] = (
            FinancialReportingService._balance_sheet_core(context, as_of=compare_as_of)
            if compare_as_of
            else None
        )
        return current

    @staticmethod
    def summary(
        context: AccessContext,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        compare_from: date | None = None,
        compare_to: date | None = None,
        compare_as_of: date | None = None,
    ) -> dict:
        to_date = to_date or date.today()
        from_date = from_date or date(to_date.year, 1, 1)
        profit_loss = FinancialReportingService.profit_and_loss(
            context,
            from_date=from_date,
            to_date=to_date,
            compare_from=compare_from,
            compare_to=compare_to,
        )
        balance_sheet = FinancialReportingService.balance_sheet(
            context,
            as_of=to_date,
            compare_as_of=compare_as_of,
        )
        return {
            **profit_loss,
            "assets": balance_sheet["assets"],
            "liabilities": balance_sheet["liabilities"],
            "equity": balance_sheet["equity"],
            "total_assets": balance_sheet["total_assets"],
            "total_liabilities": balance_sheet["total_liabilities"],
            "posted_equity": balance_sheet["posted_equity"],
            "current_earnings": balance_sheet["current_earnings"],
            "total_equity": balance_sheet["total_equity"],
            "net_assets": balance_sheet["net_assets"],
            "net_worth": balance_sheet["net_assets"],
            "balance_check": balance_sheet["balance_check"],
            "balance_sheet_comparative": balance_sheet["comparative"],
        }

    @staticmethod
    def general_ledger(
        context: AccessContext,
        *,
        from_date: date,
        to_date: date,
        account_id: str | None = None,
    ) -> dict:
        FinancialReportingService._assert_context(context)
        FinancialReportingService._validate_range(from_date, to_date)

        accounts_query = Account.query.filter_by(organisation_id=context.organisation_id)
        if account_id:
            accounts_query = accounts_query.filter(Account.id == account_id)
        accounts = accounts_query.order_by(Account.code.asc()).all()
        if account_id and not accounts:
            raise LedgerError("Account not found")

        opening_rows = FinancialReportingService._balances(
            context,
            to_date=from_date - timedelta(days=1),
        )
        opening_map = {row["id"]: row["balance"] for row in opening_rows}

        line_query = (
            db.session.query(JournalLine, Journal)
            .join(Journal, Journal.id == JournalLine.journal_id)
            .filter(
                Journal.organisation_id == context.organisation_id,
                Journal.status == "posted",
                Journal.journal_date >= from_date,
                Journal.journal_date <= to_date,
            )
            .order_by(
                Journal.journal_date.asc(),
                Journal.created_at.asc(),
                JournalLine.line_number.asc(),
            )
        )
        if account_id:
            line_query = line_query.filter(JournalLine.account_id == account_id)
        line_rows = line_query.all()
        grouped: dict[str, list[tuple[JournalLine, Journal]]] = {}
        for line, journal in line_rows:
            grouped.setdefault(line.account_id, []).append((line, journal))

        results = []
        for account in accounts:
            entries = []
            running = _money(opening_map.get(account.id, ZERO))
            movement_debit = ZERO
            movement_credit = ZERO
            for line, journal in grouped.get(account.id, []):
                debit = _money(line.debit)
                credit = _money(line.credit)
                movement_debit += debit
                movement_credit += credit
                running += debit - credit
                entries.append(
                    {
                        "journal_id": journal.id,
                        "journal_date": journal.journal_date,
                        "reference": journal.reference,
                        "journal_description": journal.description,
                        "line_description": line.description,
                        "debit": debit,
                        "credit": credit,
                        "running_balance": running,
                        "source_module": journal.source_module,
                        "source_reference": journal.source_reference,
                    }
                )
            opening = _money(opening_map.get(account.id, ZERO))
            if entries or account_id:
                results.append(
                    {
                        "id": account.id,
                        "code": account.code,
                        "name": account.name,
                        "account_type": account.account_type,
                        "opening_balance": opening,
                        "movement_debit": movement_debit,
                        "movement_credit": movement_credit,
                        "movement": movement_debit - movement_credit,
                        "closing_balance": running,
                        "entries": entries,
                    }
                )
        return {
            "from_date": from_date,
            "to_date": to_date,
            "account_id": account_id,
            "accounts": results,
        }
