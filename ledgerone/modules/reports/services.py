from decimal import Decimal

from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


class ReportsService:
    @staticmethod
    def summary(context: AccessContext):
        rows = LedgerService.trial_balance(context)
        assets = [row for row in rows if row["account_type"] == "asset"]
        liabilities = [row for row in rows if row["account_type"] == "liability"]
        equity = [row for row in rows if row["account_type"] == "equity"]
        income = [row for row in rows if row["account_type"] == "income"]
        expenses = [row for row in rows if row["account_type"] == "expense"]

        total_assets = sum((row["balance"] for row in assets), Decimal("0"))
        total_liabilities = sum((-row["balance"] for row in liabilities), Decimal("0"))
        total_equity = sum((-row["balance"] for row in equity), Decimal("0"))
        total_income = sum((-row["balance"] for row in income), Decimal("0"))
        total_expenses = sum((row["balance"] for row in expenses), Decimal("0"))
        net_profit = total_income - total_expenses

        return {
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "income": income,
            "expenses": expenses,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "net_worth": total_assets - total_liabilities,
        }
