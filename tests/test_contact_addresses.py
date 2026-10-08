from ledgerone.extensions import db
from ledgerone.models.core import Organisation, User
from ledgerone.modules.sales.services import SalesService
from ledgerone.modules.purchases.services import PurchasesService
from ledgerone.services.context import AccessContext


def _context():
    organisation = Organisation.query.first()
    user = User.query.first()
    return AccessContext(
        identity_type="user", organisation_id=organisation.id,
        user_id=user.id, full_access=True, permissions=frozenset({"*"})
    )


def test_customer_address_create_edit_and_organisation_scope(app):
    with app.app_context():
        context = _context()
        customer = SalesService.create_customer(
            context, name="Address Customer",
            address={"line1": "12 Station Road", "city": "Stafford", "postcode": "ST16 1AA", "country": "United Kingdom"},
        )
        assert customer.address["postcode"] == "ST16 1AA"
        changed = SalesService.update_customer(
            context, customer.id, name="Address Customer Ltd",
            address={"line1": "8 High Street", "city": "Stafford", "postcode": "ST16 2BB", "country": "United Kingdom"},
        )
        assert changed.name == "Address Customer Ltd"
        assert changed.address["postcode"] == "ST16 2BB"
        assert db.session.get(type(changed), changed.id).address["line1"] == "8 High Street"
        try:
            SalesService.update_customer(context, "missing-id", name="Invalid")
            assert False, "missing customer must be rejected"
        except ValueError:
            pass


def test_supplier_address_create_edit_and_roundtrip(app):
    with app.app_context():
        context = _context()
        supplier = PurchasesService.create_supplier(
            context, name="Address Supplier",
            address={"line1": "14 Market Street", "city": "Stafford", "postcode": "ST16 3ZZ", "country": "United Kingdom"},
        )
        assert supplier.address["line1"] == "14 Market Street"
        changed = PurchasesService.update_supplier(
            context, supplier.id, name="Address Supplier Ltd",
            email="orders@example.test", address={"line1": "22 Market Street", "city": "Stafford", "postcode": "ST16 4ZZ"},
        )
        assert changed.email == "orders@example.test"
        assert db.session.get(type(changed), changed.id).address["postcode"] == "ST16 4ZZ"


def test_address_validation_rejects_malformed_input(app):
    import pytest
    with app.app_context():
        context = _context()
        with pytest.raises(ValueError, match="Address must be an object"):
            SalesService.create_customer(context, name="Invalid Address", address="text")
        with pytest.raises(ValueError, match="Unsupported address field"):
            PurchasesService.create_supplier(context, name="Invalid Supplier", address={"unknown": "value"})
        with pytest.raises(ValueError, match="exceeds 255"):
            SalesService.create_customer(context, name="Too Long", address={"line1": "x" * 256})
