from datetime import date

from ledgerone.models.core import Organisation, User
from ledgerone.models.ledger import Account
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


def test_purchase_bill_auto_number_is_assigned_only_at_post(app):
    with app.app_context():
        org = Organisation.query.first()
        user = User.query.first()
        context = AccessContext(
            identity_type="user", organisation_id=org.id, user_id=user.id,
            full_access=True, permissions=frozenset({"*"}),
        )
        supplier = PurchasesService.create_supplier(context, name="Numbering Test Supplier")
        accounts = Account.query.filter_by(organisation_id=org.id, is_active=True).all()
        payable = next(row for row in accounts if row.account_type == "liability" and not row.is_control_account or row.code == "2000")
        expense = next(row for row in accounts if row.account_type == "expense")
        bill_day = date(2027, 2, 15)
        LedgerService.create_period(
            context, name="Numbering test period",
            start_date=date(2027, 2, 1), end_date=date(2027, 2, 28),
        )
        first = PurchasesService.create_bill(
            context, supplier_id=supplier.id, bill_number=None,
            bill_date=bill_day, due_date=None, description="Test purchase",
            amount="10.00", payable_account_id=payable.id,
            expense_account_id=expense.id,
        )
        assert first.bill_number.startswith("BILL-")
        second = PurchasesService.create_bill(
            context, supplier_id=supplier.id, bill_number="",
            bill_date=bill_day, due_date=None, description="Another purchase",
            amount="12.00", payable_account_id=payable.id,
            expense_account_id=expense.id,
        )
        assert second.bill_number != first.bill_number
