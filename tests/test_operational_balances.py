from ledgerone.models.core import Organisation, User
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext
from ledgerone.services.operational_balances import customer_balances, supplier_balances


def test_customer_supplier_balances_are_grouped_and_default_to_zero(app):
    with app.app_context():
        org = Organisation.query.first()
        user = User.query.first()
        context = AccessContext(identity_type="user", organisation_id=org.id,
                                user_id=user.id, full_access=True, permissions=frozenset({"*"}))
        customer = SalesService.create_customer(context, name="Balance Customer")
        supplier = PurchasesService.create_supplier(context, name="Balance Supplier")
        assert customer_balances(context).get(customer.id, 0) == 0
        assert supplier_balances(context).get(supplier.id, 0) == 0
        assert all(isinstance(rows, list) for rows in customer_balances(context).values())
        assert all(isinstance(rows, list) for rows in supplier_balances(context).values())
