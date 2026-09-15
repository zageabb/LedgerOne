from datetime import date

import pytest

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, User
from ledgerone.models.ledger import Account, Journal
from ledgerone.modules.expense_claims.models import ExpenseClaim
from ledgerone.modules.expense_claims.services import ExpenseClaimService
from ledgerone.modules.settings.services import SettingsService
from ledgerone.modules.workflows.expense_claim_requests import ExpenseClaimWorkflowService
from ledgerone.modules.workflows.models import UserAction, WorkflowInstance
from ledgerone.modules.workflows.posting import can_post_action
from ledgerone.modules.workflows.services import WorkflowError
from ledgerone.services.context import AccessContext


def _context(*, professional=True, permissions=None):
    organisation = Organisation.query.first()
    user = User.query.first()
    user.ui_mode = "professional" if professional else "home"
    db.session.commit()
    system = AccessContext.system(organisation.id)
    SettingsService.set_module_enabled(system, "expense_claims", True)
    SettingsService.set_module_enabled(system, "workflows", True)
    return AccessContext(
        identity_type="user",
        organisation_id=organisation.id,
        user_id=user.id,
        permissions=frozenset(
            permissions
            or {
                "expense_claims.read",
                "expense_claims.write",
                "expense_claims.approve",
                "workflows.read",
                "workflows.review",
                "workflows.post",
            }
        ),
    )


def _accounts(context):
    return {
        row.code: row
        for row in Account.query.filter_by(organisation_id=context.organisation_id).all()
    }


def _claim(context, accounts, *, number="WF-EXP-001"):
    return ExpenseClaimService.create_claim(
        context,
        claimant_name="Workflow Claimant",
        claim_number=number,
        claim_date=date(2026, 9, 15),
        expense_date=date(2026, 9, 14),
        merchant="Workflow Merchant",
        description="Workflow travel",
        amount="100.00",
        expense_account_id=accounts["5000"].id,
        reimbursement_account_id=accounts["2150"].id,
        currency="GBP",
    )


def _open_action(workflow_id, action_type):
    return UserAction.query.filter_by(
        workflow_instance_id=workflow_id,
        action_type=action_type,
        status="open",
    ).one()


def test_professional_expense_claim_requires_user_action_before_posting(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        claim = _claim(context, accounts)
        journals_before = Journal.query.count()

        workflow = ExpenseClaimWorkflowService.submit_request(context, claim.id)

        assert workflow.status == "awaiting_review"
        assert claim.status == "submitted"
        assert Journal.query.count() == journals_before
        review = _open_action(workflow.id, "review")

        ExpenseClaimWorkflowService.complete_action(
            context,
            review.id,
            decision="approve",
            comments="Receipts and coding reviewed",
        )
        post_action = _open_action(workflow.id, "post")
        assert can_post_action(context, post_action) is True
        assert context.can("ledger.journals.post") is False

        posted = ExpenseClaimWorkflowService.post_from_action(
            context,
            post_action.id,
            posting_date=date(2026, 9, 15),
        )

        assert posted.status == "posted"
        assert posted.posted_journal_id is not None
        assert Journal.query.count() == journals_before + 1
        assert posted.posted_journal.source_module == "expense_claims"
        workflow = db.session.get(WorkflowInstance, workflow.id)
        assert workflow.status == "posted"
        assert workflow.metadata_json["posted_expense_claim_id"] == posted.id
        assert workflow.metadata_json["posted_journal_id"] == posted.posted_journal_id


def test_return_reopens_claim_and_resubmission_reevaluates_workflow(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        claim = _claim(context, accounts, number="WF-EXP-RETURN")
        first = ExpenseClaimWorkflowService.submit_request(context, claim.id)
        review = _open_action(first.id, "review")

        returned = ExpenseClaimWorkflowService.complete_action(
            context,
            review.id,
            decision="return",
            comments="Add parking receipt",
        )

        db.session.refresh(claim)
        assert returned.status == "returned"
        assert claim.status == "draft"
        assert claim.metadata_json["returned_from_workflow_id"] == first.id
        assert UserAction.query.filter_by(workflow_instance_id=first.id, status="open").count() == 0

        ExpenseClaimService.add_line(
            context,
            claim.id,
            expense_date=date(2026, 9, 14),
            merchant="Car park",
            description="Parking",
            amount="12.50",
            expense_account_id=accounts["5000"].id,
        )
        second = ExpenseClaimWorkflowService.submit_request(context, claim.id)

        assert second.id != first.id
        assert second.status == "awaiting_review"
        assert str(second.amount) == "112.50"
        db.session.refresh(claim)
        assert claim.status == "submitted"
        assert claim.metadata_json["workflow_instance_id"] == second.id


def test_submitted_claim_cannot_change_after_review_snapshot(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        claim = _claim(context, accounts, number="WF-EXP-TAMPER")
        workflow = ExpenseClaimWorkflowService.submit_request(context, claim.id)
        review = _open_action(workflow.id, "review")
        ExpenseClaimWorkflowService.complete_action(context, review.id, decision="approve")
        post_action = _open_action(workflow.id, "post")

        # Simulate an unexpected out-of-band data mutation after reviewers saw the claim.
        claim.lines[0].description = "Changed after review"
        db.session.commit()

        with pytest.raises(WorkflowError, match="changed after submission"):
            ExpenseClaimWorkflowService.post_from_action(
                context,
                post_action.id,
                posting_date=date(2026, 9, 15),
            )

        db.session.expire_all()
        persisted = db.session.get(ExpenseClaim, claim.id)
        assert persisted.status == "submitted"
        assert persisted.posted_journal_id is None
        assert db.session.get(UserAction, post_action.id).status == "open"


def test_reject_closes_claim_without_accounting_entry(app):
    with app.app_context():
        context = _context(professional=True)
        accounts = _accounts(context)
        claim = _claim(context, accounts, number="WF-EXP-REJECT")
        journals_before = Journal.query.count()
        workflow = ExpenseClaimWorkflowService.submit_request(context, claim.id)
        review = _open_action(workflow.id, "review")

        rejected = ExpenseClaimWorkflowService.complete_action(
            context,
            review.id,
            decision="reject",
            comments="Receipt is not valid evidence",
        )

        db.session.refresh(claim)
        assert rejected.status == "rejected"
        assert claim.status == "rejected"
        assert claim.metadata_json["rejection_reason"] == "Receipt is not valid evidence"
        assert Journal.query.count() == journals_before
