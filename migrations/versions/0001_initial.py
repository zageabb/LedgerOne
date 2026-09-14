"""Initial LedgerOne schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("ui_mode", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "organisations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("fiscal_year_start_month", sa.Integer(), nullable=False),
        sa.Column("fiscal_year_start_day", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organisations_slug", "organisations", ["slug"], unique=True)

    op.create_table(
        "memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index("ix_memberships_organisation_id", "memberships", ["organisation_id"], unique=False)
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("full_access", sa.Boolean(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_organisation_id", "api_keys", ["organisation_id"], unique=False)

    op.create_table(
        "module_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("module_id", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "module_id", name="uq_module_state_org_module"),
    )
    op.create_index("ix_module_states_organisation_id", "module_states", ["organisation_id"], unique=False)
    op.create_index("ix_module_states_module_id", "module_states", ["module_id"], unique=False)

    op.create_table(
        "settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "scope", "key", name="uq_setting_org_scope_key"),
    )
    op.create_index("ix_settings_organisation_id", "settings", ["organisation_id"], unique=False)

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("account_type", sa.String(length=40), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("is_control_account", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "code", name="uq_account_org_code"),
    )
    op.create_index("ix_accounts_organisation_id", "accounts", ["organisation_id"], unique=False)
    op.create_index("ix_accounts_account_type", "accounts", ["account_type"], unique=False)

    op.create_table(
        "journals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("journal_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_module", sa.String(length=80), nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("reversal_of_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journals_organisation_id", "journals", ["organisation_id"], unique=False)
    op.create_index("ix_journals_journal_date", "journals", ["journal_date"], unique=False)
    op.create_index("ix_journals_reference", "journals", ["reference"], unique=False)
    op.create_index("ix_journals_status", "journals", ["status"], unique=False)
    op.create_index("ix_journals_source_module", "journals", ["source_module"], unique=False)
    op.create_index("ix_journals_source_reference", "journals", ["source_reference"], unique=False)

    op.create_table(
        "journal_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("debit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("credit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("foreign_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_journal_lines_journal_id", "journal_lines", ["journal_id"], unique=False)
    op.create_index("ix_journal_lines_account_id", "journal_lines", ["account_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=True),
        sa.Column("actor_type", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=True),
        sa.Column("module_id", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_organisation_id", "audit_events", ["organisation_id"], unique=False)
    op.create_index("ix_audit_events_actor_type", "audit_events", ["actor_type"], unique=False)
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"], unique=False)
    op.create_index("ix_audit_events_module_id", "audit_events", ["module_id"], unique=False)
    op.create_index("ix_audit_events_action", "audit_events", ["action"], unique=False)
    op.create_index("ix_audit_events_entity_type", "audit_events", ["entity_type"], unique=False)
    op.create_index("ix_audit_events_entity_id", "audit_events", ["entity_id"], unique=False)
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"], unique=False)

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("institution", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("ledger_account_id", sa.String(length=36), nullable=True),
        sa.Column("account_mask", sa.String(length=40), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ledger_account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bank_accounts_organisation_id", "bank_accounts", ["organisation_id"], unique=False)
    op.create_index("ix_bank_accounts_ledger_account_id", "bank_accounts", ["ledger_account_id"], unique=False)

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("matched_journal_id", sa.String(length=36), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["matched_journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_account_id", "external_id", name="uq_bank_transaction_external"),
    )
    op.create_index("ix_bank_transactions_bank_account_id", "bank_transactions", ["bank_account_id"], unique=False)
    op.create_index("ix_bank_transactions_transaction_date", "bank_transactions", ["transaction_date"], unique=False)
    op.create_index("ix_bank_transactions_status", "bank_transactions", ["status"], unique=False)

    op.create_table(
        "customers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=80), nullable=True),
        sa.Column("tax_id", sa.String(length=120), nullable=True),
        sa.Column("address", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_organisation_id", "customers", ["organisation_id"], unique=False)
    op.create_index("ix_customers_name", "customers", ["name"], unique=False)

    op.create_table(
        "sales_invoices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_number", sa.String(length=120), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("posted_journal_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["posted_journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "invoice_number", name="uq_sales_invoice_org_number"),
    )
    op.create_index("ix_sales_invoices_organisation_id", "sales_invoices", ["organisation_id"], unique=False)
    op.create_index("ix_sales_invoices_customer_id", "sales_invoices", ["customer_id"], unique=False)
    op.create_index("ix_sales_invoices_invoice_number", "sales_invoices", ["invoice_number"], unique=False)
    op.create_index("ix_sales_invoices_invoice_date", "sales_invoices", ["invoice_date"], unique=False)
    op.create_index("ix_sales_invoices_status", "sales_invoices", ["status"], unique=False)

    op.create_table(
        "sales_invoice_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("revenue_account_id", sa.String(length=36), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["sales_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revenue_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_invoice_lines_invoice_id", "sales_invoice_lines", ["invoice_id"], unique=False)

    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=80), nullable=True),
        sa.Column("tax_id", sa.String(length=120), nullable=True),
        sa.Column("address", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_suppliers_organisation_id", "suppliers", ["organisation_id"], unique=False)
    op.create_index("ix_suppliers_name", "suppliers", ["name"], unique=False)

    op.create_table(
        "purchase_bills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("bill_number", sa.String(length=120), nullable=False),
        sa.Column("bill_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("posted_journal_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["posted_journal_id"], ["journals.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "bill_number", name="uq_purchase_bill_org_number"),
    )
    op.create_index("ix_purchase_bills_organisation_id", "purchase_bills", ["organisation_id"], unique=False)
    op.create_index("ix_purchase_bills_supplier_id", "purchase_bills", ["supplier_id"], unique=False)
    op.create_index("ix_purchase_bills_bill_number", "purchase_bills", ["bill_number"], unique=False)
    op.create_index("ix_purchase_bills_bill_date", "purchase_bills", ["bill_date"], unique=False)
    op.create_index("ix_purchase_bills_status", "purchase_bills", ["status"], unique=False)

    op.create_table(
        "purchase_bill_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bill_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("expense_account_id", sa.String(length=36), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["bill_id"], ["purchase_bills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["expense_account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_bill_lines_bill_id", "purchase_bill_lines", ["bill_id"], unique=False)

    op.create_table(
        "ai_interactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("tool_log", sa.JSON(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_interactions_organisation_id", "ai_interactions", ["organisation_id"], unique=False)
    op.create_index("ix_ai_interactions_user_id", "ai_interactions", ["user_id"], unique=False)
    op.create_index("ix_ai_interactions_created_at", "ai_interactions", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_ai_interactions_created_at", table_name="ai_interactions")
    op.drop_index("ix_ai_interactions_user_id", table_name="ai_interactions")
    op.drop_index("ix_ai_interactions_organisation_id", table_name="ai_interactions")
    op.drop_table("ai_interactions")

    op.drop_index("ix_purchase_bill_lines_bill_id", table_name="purchase_bill_lines")
    op.drop_table("purchase_bill_lines")

    op.drop_index("ix_purchase_bills_status", table_name="purchase_bills")
    op.drop_index("ix_purchase_bills_bill_date", table_name="purchase_bills")
    op.drop_index("ix_purchase_bills_bill_number", table_name="purchase_bills")
    op.drop_index("ix_purchase_bills_supplier_id", table_name="purchase_bills")
    op.drop_index("ix_purchase_bills_organisation_id", table_name="purchase_bills")
    op.drop_table("purchase_bills")

    op.drop_index("ix_suppliers_name", table_name="suppliers")
    op.drop_index("ix_suppliers_organisation_id", table_name="suppliers")
    op.drop_table("suppliers")

    op.drop_index("ix_sales_invoice_lines_invoice_id", table_name="sales_invoice_lines")
    op.drop_table("sales_invoice_lines")

    op.drop_index("ix_sales_invoices_status", table_name="sales_invoices")
    op.drop_index("ix_sales_invoices_invoice_date", table_name="sales_invoices")
    op.drop_index("ix_sales_invoices_invoice_number", table_name="sales_invoices")
    op.drop_index("ix_sales_invoices_customer_id", table_name="sales_invoices")
    op.drop_index("ix_sales_invoices_organisation_id", table_name="sales_invoices")
    op.drop_table("sales_invoices")

    op.drop_index("ix_customers_name", table_name="customers")
    op.drop_index("ix_customers_organisation_id", table_name="customers")
    op.drop_table("customers")

    op.drop_index("ix_bank_transactions_status", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_transaction_date", table_name="bank_transactions")
    op.drop_index("ix_bank_transactions_bank_account_id", table_name="bank_transactions")
    op.drop_table("bank_transactions")

    op.drop_index("ix_bank_accounts_ledger_account_id", table_name="bank_accounts")
    op.drop_index("ix_bank_accounts_organisation_id", table_name="bank_accounts")
    op.drop_table("bank_accounts")

    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_id", table_name="audit_events")
    op.drop_index("ix_audit_events_entity_type", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_module_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_type", table_name="audit_events")
    op.drop_index("ix_audit_events_organisation_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_journal_lines_account_id", table_name="journal_lines")
    op.drop_index("ix_journal_lines_journal_id", table_name="journal_lines")
    op.drop_table("journal_lines")

    op.drop_index("ix_journals_source_reference", table_name="journals")
    op.drop_index("ix_journals_source_module", table_name="journals")
    op.drop_index("ix_journals_status", table_name="journals")
    op.drop_index("ix_journals_reference", table_name="journals")
    op.drop_index("ix_journals_journal_date", table_name="journals")
    op.drop_index("ix_journals_organisation_id", table_name="journals")
    op.drop_table("journals")

    op.drop_index("ix_accounts_account_type", table_name="accounts")
    op.drop_index("ix_accounts_organisation_id", table_name="accounts")
    op.drop_table("accounts")

    op.drop_index("ix_settings_organisation_id", table_name="settings")
    op.drop_table("settings")

    op.drop_index("ix_module_states_module_id", table_name="module_states")
    op.drop_index("ix_module_states_organisation_id", table_name="module_states")
    op.drop_table("module_states")

    op.drop_index("ix_api_keys_organisation_id", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_organisation_id", table_name="memberships")
    op.drop_table("memberships")

    op.drop_index("ix_organisations_slug", table_name="organisations")
    op.drop_table("organisations")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
