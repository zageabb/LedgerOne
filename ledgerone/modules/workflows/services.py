from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_

from ledgerone.extensions import db
from ledgerone.models.core import Membership, Organisation, Setting, User, utcnow
from ledgerone.models.ledger import Account
from ledgerone.modules.workflows.models import (
    ScheduledTransaction,
    TransactionTemplate,
    UserAction,
    WorkflowDefinition,
    WorkflowInstance,
)
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext
from ledgerone.services.ledger import LedgerService


class WorkflowError(ValueError):
    pass


def _money(value, *, allow_none: bool = False) -> Decimal | None:
    if value is None or value == "":
        return None if allow_none else Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise WorkflowError(f"Invalid monetary value: {value}") from exc


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _advance(value: date, frequency: str) -> date:
    if frequency == "weekly":
        return value + timedelta(days=7)
    if frequency == "four_weekly":
        return value + timedelta(days=28)
    if frequency == "monthly":
        return _add_months(value, 1)
    if frequency == "quarterly":
        return _add_months(value, 3)
    if frequency == "annual":
        return _add_months(value, 12)
    raise WorkflowError(f"Unsupported frequency: {frequency}")


def _membership_role(context: AccessContext) -> str | None:
    if not context.user_id or not context.organisation_id:
        return None
    row = Membership.query.filter_by(
        organisation_id=context.organisation_id,
        user_id=context.user_id,
        is_active=True,
    ).first()
    return row.role if row else None


def _originator_mode(user_id: str | None) -> str:
    if not user_id:
        return "professional"
    user = db.session.get(User, user_id)
    return user.ui_mode if user else "professional"


class WorkflowService:
    """Generic review/approval engine used by scheduled transactions and future modules."""

    @staticmethod
    def list_definitions(context: AccessContext):
        if not context.organisation_id:
            raise WorkflowError("An organisation is required")
        return (
            WorkflowDefinition.query.filter_by(organisation_id=context.organisation_id)
            .order_by(WorkflowDefinition.priority.asc(), WorkflowDefinition.name.asc())
            .all()
        )

    @staticmethod
    def create_definition(
        context: AccessContext,
        *,
        name: str,
        description: str | None = None,
        entity_type: str = "scheduled_transaction",
        transaction_type: str | None = None,
        min_amount=None,
        max_amount=None,
        review_required: bool = True,
        approval_required: bool = False,
        approval_role: str | None = None,
        separate_approver: bool = True,
        priority: int = 100,
    ):
        if not context.can("workflows.manage"):
            raise PermissionError("workflows.manage")
        if not context.organisation_id:
            raise WorkflowError("An organisation is required")
        clean_name = (name or "").strip()
        if not clean_name:
            raise WorkflowError("Workflow name is required")
        minimum = _money(min_amount, allow_none=True)
        maximum = _money(max_amount, allow_none=True)
        if minimum is not None and minimum < 0:
            raise WorkflowError("Minimum amount cannot be negative")
        if maximum is not None and maximum < 0:
            raise WorkflowError("Maximum amount cannot be negative")
        if minimum is not None and maximum is not None and maximum < minimum:
            raise WorkflowError("Maximum amount cannot be less than minimum amount")

        steps = []
        if review_required:
            steps.append({"type": "review", "label": "Review", "role": None})
        if approval_required:
            steps.append(
                {
                    "type": "approve",
                    "label": "Approve",
                    "role": (approval_role or "").strip() or None,
                }
            )
        rules = {
            "transaction_types": [transaction_type] if transaction_type else [],
            "min_amount": str(minimum) if minimum is not None else None,
            "max_amount": str(maximum) if maximum is not None else None,
            "separate_approver": bool(separate_approver),
        }
        row = WorkflowDefinition(
            organisation_id=context.organisation_id,
            name=clean_name,
            description=(description or "").strip() or None,
            entity_type=(entity_type or "scheduled_transaction").strip(),
            priority=int(priority or 100),
            rules_json=rules,
            steps_json=steps,
            created_by_user_id=context.user_id,
        )
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="workflows",
            action="workflow_definition_created",
            entity_type="workflow_definition",
            entity_id=row.id,
            detail={"name": row.name, "entity_type": row.entity_type, "rules": rules, "steps": steps},
        )
        db.session.commit()
        return row

    @staticmethod
    def set_definition_active(context: AccessContext, definition_id: str, *, active: bool):
        if not context.can("workflows.manage"):
            raise PermissionError("workflows.manage")
        row = db.session.get(WorkflowDefinition, definition_id)
        if not row or row.organisation_id != context.organisation_id:
            raise WorkflowError("Workflow definition not found")
        row.is_active = bool(active)
        record_audit_event(
            context,
            module_id="workflows",
            action="workflow_definition_enabled" if active else "workflow_definition_disabled",
            entity_type="workflow_definition",
            entity_id=row.id,
            detail={"name": row.name},
        )
        db.session.commit()
        return row

    @staticmethod
    def _matches_definition(
        definition: WorkflowDefinition,
        *,
        entity_type: str,
        amount: Decimal | None,
        metadata: dict,
    ) -> bool:
        if definition.entity_type not in {"*", entity_type}:
            return False
        rules = definition.rules_json or {}
        transaction_types = rules.get("transaction_types") or []
        transaction_type = metadata.get("transaction_type")
        if transaction_types and transaction_type not in transaction_types:
            return False
        minimum = _money(rules.get("min_amount"), allow_none=True)
        maximum = _money(rules.get("max_amount"), allow_none=True)
        if minimum is not None and (amount is None or amount < minimum):
            return False
        if maximum is not None and (amount is None or amount > maximum):
            return False
        source_modules = rules.get("source_modules") or []
        if source_modules and metadata.get("source_module") not in source_modules:
            return False
        return True

    @staticmethod
    def resolve_definition(
        context: AccessContext,
        *,
        entity_type: str,
        amount: Decimal | None,
        metadata: dict | None = None,
        definition_id: str | None = None,
    ) -> WorkflowDefinition | None:
        metadata = metadata or {}
        if definition_id:
            row = db.session.get(WorkflowDefinition, definition_id)
            if not row or row.organisation_id != context.organisation_id or not row.is_active:
                raise WorkflowError("Selected workflow definition is not available")
            if not WorkflowService._matches_definition(
                row, entity_type=entity_type, amount=amount, metadata=metadata
            ):
                raise WorkflowError("Selected workflow definition does not match this transaction")
            return row
        rows = (
            WorkflowDefinition.query.filter_by(
                organisation_id=context.organisation_id,
                is_active=True,
            )
            .filter(WorkflowDefinition.entity_type.in_([entity_type, "*"]))
            .order_by(WorkflowDefinition.priority.asc(), WorkflowDefinition.created_at.asc())
            .all()
        )
        for row in rows:
            if WorkflowService._matches_definition(
                row, entity_type=entity_type, amount=amount, metadata=metadata
            ):
                return row
        return None

    @staticmethod
    def _action_title(action_type: str, title: str) -> str:
        prefix = {
            "review": "Review",
            "approve": "Approve",
            "post": "Post",
            "information": "Provide information for",
        }.get(action_type, action_type.replace("_", " ").title())
        return f"{prefix}: {title}"

    @staticmethod
    def _create_action(
        instance: WorkflowInstance,
        *,
        action_type: str,
        label: str | None = None,
        role: str | None = None,
        assigned_user_id: str | None = None,
        due_date: date | None = None,
        instructions: str | None = None,
    ) -> UserAction:
        action = UserAction(
            organisation_id=instance.organisation_id,
            workflow_instance_id=instance.id,
            action_type=action_type,
            title=WorkflowService._action_title(action_type, instance.title),
            instructions=instructions or label,
            assigned_user_id=assigned_user_id,
            assigned_role=role,
            due_date=due_date,
        )
        db.session.add(action)
        return action

    @staticmethod
    def _sync_entity_status(instance: WorkflowInstance):
        if instance.entity_type == "scheduled_transaction":
            item = db.session.get(ScheduledTransaction, instance.entity_id)
            if item and item.organisation_id == instance.organisation_id and item.status != "posted":
                item.status = instance.status

    @staticmethod
    def _make_ready(instance: WorkflowInstance, *, create_post_action: bool):
        instance.status = "ready_to_post"
        WorkflowService._sync_entity_status(instance)
        if create_post_action:
            WorkflowService._create_action(
                instance,
                action_type="post",
                label="Approved and ready for explicit ledger posting",
            )

    @staticmethod
    def start(
        context: AccessContext,
        *,
        entity_type: str,
        entity_id: str,
        title: str,
        amount=None,
        currency: str = "GBP",
        source_module: str = "workflows",
        metadata: dict | None = None,
        definition_id: str | None = None,
        originator_user_id: str | None = None,
        create_post_action: bool = False,
        commit: bool = True,
    ) -> WorkflowInstance:
        if not context.can("workflows.write"):
            raise PermissionError("workflows.write")
        if not context.organisation_id:
            raise WorkflowError("An organisation is required")
        existing = WorkflowInstance.query.filter_by(
            organisation_id=context.organisation_id,
            entity_type=entity_type,
            entity_id=entity_id,
        ).first()
        if existing:
            return existing

        clean_amount = _money(amount, allow_none=True)
        meta = dict(metadata or {})
        meta.setdefault("source_module", source_module)
        originator = originator_user_id if originator_user_id is not None else context.user_id
        definition = WorkflowService.resolve_definition(
            context,
            entity_type=entity_type,
            amount=clean_amount,
            metadata=meta,
            definition_id=definition_id,
        )
        if definition:
            steps = list(definition.steps_json or [])
        elif _originator_mode(originator) == "professional":
            steps = [{"type": "review", "label": "Professional review", "role": None}]
        else:
            steps = []

        instance = WorkflowInstance(
            organisation_id=context.organisation_id,
            workflow_definition_id=definition.id if definition else None,
            entity_type=entity_type,
            entity_id=entity_id,
            source_module=source_module,
            title=(title or entity_type).strip(),
            amount=clean_amount,
            currency=(currency or "GBP").upper(),
            originator_user_id=originator,
            metadata_json=meta,
            status="draft",
            current_step_index=0,
        )
        db.session.add(instance)
        db.session.flush()

        if steps:
            step = steps[0]
            action_type = step.get("type") or "review"
            instance.status = "awaiting_approval" if action_type == "approve" else "awaiting_review"
            WorkflowService._create_action(
                instance,
                action_type=action_type,
                label=step.get("label"),
                role=step.get("role"),
            )
        else:
            WorkflowService._make_ready(instance, create_post_action=create_post_action)

        record_audit_event(
            context,
            module_id="workflows",
            action="workflow_started",
            entity_type=entity_type,
            entity_id=entity_id,
            detail={
                "workflow_instance_id": instance.id,
                "definition_id": instance.workflow_definition_id,
                "status": instance.status,
                "title": instance.title,
            },
        )
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return instance

    @staticmethod
    def list_instances(context: AccessContext, *, limit: int = 200):
        if not context.can("workflows.read"):
            raise PermissionError("workflows.read")
        return (
            WorkflowInstance.query.filter_by(organisation_id=context.organisation_id)
            .order_by(WorkflowInstance.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def _can_access_action(context: AccessContext, action: UserAction) -> bool:
        if context.full_access or "*" in context.permissions:
            return True
        if action.assigned_user_id and action.assigned_user_id != context.user_id:
            return False
        role = _membership_role(context)
        if action.assigned_role and action.assigned_role != role:
            return False
        return True

    @staticmethod
    def open_actions(context: AccessContext, *, limit: int = 200):
        if not context.can("workflows.read"):
            raise PermissionError("workflows.read")
        query = (
            UserAction.query.join(WorkflowInstance)
            .filter(
                UserAction.organisation_id == context.organisation_id,
                UserAction.status == "open",
            )
        )
        if not (context.full_access or "*" in context.permissions):
            role = _membership_role(context)
            filters = [
                db.and_(UserAction.assigned_user_id.is_(None), UserAction.assigned_role.is_(None))
            ]
            if context.user_id:
                filters.append(UserAction.assigned_user_id == context.user_id)
            if role:
                filters.append(UserAction.assigned_role == role)
            query = query.filter(or_(*filters))
        return query.order_by(UserAction.due_date.asc(), UserAction.created_at.asc()).limit(limit).all()

    @staticmethod
    def recent_actions(context: AccessContext, *, limit: int = 50):
        if not context.can("workflows.read"):
            raise PermissionError("workflows.read")
        return (
            UserAction.query.filter(
                UserAction.organisation_id == context.organisation_id,
                UserAction.status != "open",
            )
            .order_by(UserAction.completed_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def open_action_count(context: AccessContext) -> int:
        return len(WorkflowService.open_actions(context, limit=1000))

    @staticmethod
    def complete_action(
        context: AccessContext,
        action_id: str,
        *,
        decision: str = "approve",
        comments: str | None = None,
    ) -> WorkflowInstance:
        action = db.session.get(UserAction, action_id)
        if not action or action.organisation_id != context.organisation_id or action.status != "open":
            raise WorkflowError("Open user action not found")
        if action.action_type == "post":
            raise WorkflowError("Posting actions must use the controlled post operation")
        permission = "workflows.approve" if action.action_type == "approve" else "workflows.review"
        if not context.can(permission):
            raise PermissionError(permission)
        if not WorkflowService._can_access_action(context, action):
            raise PermissionError("This action is assigned to another user or role")

        instance = action.workflow_instance
        clean_decision = (decision or "approve").strip().lower()
        if clean_decision not in {"approve", "reject", "return"}:
            raise WorkflowError("Decision must be approve, reject or return")

        if action.action_type == "approve" and instance.originator_user_id == context.user_id:
            rules = instance.definition.rules_json if instance.definition else {}
            if (rules or {}).get("separate_approver", True):
                raise WorkflowError("The creator cannot approve their own item under this workflow")

        action.status = "completed"
        action.decision = clean_decision
        action.comments = (comments or "").strip() or None
        action.completed_by_user_id = context.user_id
        action.completed_at = utcnow()

        if clean_decision == "reject":
            instance.status = "rejected"
            instance.completed_at = utcnow()
            WorkflowService._sync_entity_status(instance)
        elif clean_decision == "return":
            instance.status = "returned"
            WorkflowService._sync_entity_status(instance)
            WorkflowService._create_action(
                instance,
                action_type="review",
                label="Item was returned and needs changes/review",
                assigned_user_id=instance.originator_user_id,
            )
        else:
            steps = list(instance.definition.steps_json or []) if instance.definition else []
            next_index = instance.current_step_index + 1
            instance.current_step_index = next_index
            if next_index < len(steps):
                step = steps[next_index]
                action_type = step.get("type") or "review"
                instance.status = "awaiting_approval" if action_type == "approve" else "awaiting_review"
                WorkflowService._sync_entity_status(instance)
                WorkflowService._create_action(
                    instance,
                    action_type=action_type,
                    label=step.get("label"),
                    role=step.get("role"),
                )
            else:
                create_post = bool((instance.metadata_json or {}).get("create_post_action"))
                WorkflowService._make_ready(instance, create_post_action=create_post)

        record_audit_event(
            context,
            module_id="workflows",
            action="user_action_completed",
            entity_type="user_action",
            entity_id=action.id,
            detail={
                "workflow_instance_id": instance.id,
                "action_type": action.action_type,
                "decision": clean_decision,
                "comments": action.comments,
                "resulting_status": instance.status,
            },
        )
        db.session.commit()
        return instance


class RecurringTransactionService:
    TRANSACTION_TYPES = ("income", "expense", "transfer")
    AMOUNT_MODES = ("fixed", "expected", "variable")
    FREQUENCIES = ("weekly", "four_weekly", "monthly", "quarterly", "annual")

    @staticmethod
    def _validate_accounts(context: AccessContext, transaction_type: str, bank_account_id: str, counter_account_id: str):
        bank = db.session.get(Account, bank_account_id)
        counter = db.session.get(Account, counter_account_id)
        for row, label in ((bank, "Payment/deposit account"), (counter, "Category/destination account")):
            if not row or row.organisation_id != context.organisation_id or not row.is_active:
                raise WorkflowError(f"{label} is invalid or inactive")
            if row.is_control_account:
                raise WorkflowError(f"{label} cannot be an AR/AP/VAT control account")
        if bank.id == counter.id:
            raise WorkflowError("The two accounts must be different")
        if bank.account_type not in {"asset", "liability"}:
            raise WorkflowError("Payment/deposit account must be an asset or liability account")
        if transaction_type == "income" and counter.account_type != "income":
            raise WorkflowError("Income transactions require an income category account")
        if transaction_type == "expense" and counter.account_type != "expense":
            raise WorkflowError("Expense transactions require an expense category account")
        if transaction_type == "transfer" and counter.account_type not in {"asset", "liability"}:
            raise WorkflowError("Transfers require an asset or liability destination account")
        return bank, counter

    @staticmethod
    def create_template(
        context: AccessContext,
        *,
        name: str,
        transaction_type: str,
        amount_mode: str,
        expected_amount,
        bank_account_id: str,
        counter_account_id: str,
        frequency: str,
        next_run_date: date,
        description: str | None = None,
        tolerance=None,
        currency: str = "GBP",
        end_date: date | None = None,
        reference: str | None = None,
        workflow_definition_id: str | None = None,
    ) -> TransactionTemplate:
        if not context.can("workflows.write"):
            raise PermissionError("workflows.write")
        if not context.organisation_id:
            raise WorkflowError("An organisation is required")
        clean_name = (name or "").strip()
        if not clean_name:
            raise WorkflowError("Template name is required")
        transaction_type = (transaction_type or "").strip().lower()
        amount_mode = (amount_mode or "expected").strip().lower()
        frequency = (frequency or "monthly").strip().lower()
        if transaction_type not in RecurringTransactionService.TRANSACTION_TYPES:
            raise WorkflowError("Transaction type must be income, expense or transfer")
        if amount_mode not in RecurringTransactionService.AMOUNT_MODES:
            raise WorkflowError("Amount mode must be fixed, expected or variable")
        if frequency not in RecurringTransactionService.FREQUENCIES:
            raise WorkflowError("Unsupported recurring frequency")
        if end_date and end_date < next_run_date:
            raise WorkflowError("End date cannot be before the first expected date")

        expected = _money(expected_amount, allow_none=True)
        tolerance_value = _money(tolerance, allow_none=True)
        if amount_mode in {"fixed", "expected"} and (expected is None or expected <= 0):
            raise WorkflowError("Fixed and expected templates require a positive expected amount")
        if expected is not None and expected <= 0:
            raise WorkflowError("Expected amount must be greater than zero")
        if tolerance_value is not None and tolerance_value < 0:
            raise WorkflowError("Tolerance cannot be negative")

        organisation = db.session.get(Organisation, context.organisation_id)
        clean_currency = (currency or organisation.base_currency or "GBP").upper()
        if clean_currency != (organisation.base_currency or "GBP").upper():
            raise WorkflowError("Recurring templates must use the organisation base currency until multi-currency is enabled")
        RecurringTransactionService._validate_accounts(
            context, transaction_type, bank_account_id, counter_account_id
        )
        if workflow_definition_id:
            definition = db.session.get(WorkflowDefinition, workflow_definition_id)
            if not definition or definition.organisation_id != context.organisation_id or not definition.is_active:
                raise WorkflowError("Selected workflow definition is not available")

        row = TransactionTemplate(
            organisation_id=context.organisation_id,
            name=clean_name,
            description=(description or "").strip() or None,
            transaction_type=transaction_type,
            amount_mode=amount_mode,
            expected_amount=expected,
            tolerance=tolerance_value,
            currency=clean_currency,
            bank_account_id=bank_account_id,
            counter_account_id=counter_account_id,
            frequency=frequency,
            next_run_date=next_run_date,
            end_date=end_date,
            reference=(reference or "").strip() or None,
            workflow_definition_id=workflow_definition_id,
            posting_mode="manual",
            created_by_user_id=context.user_id,
        )
        db.session.add(row)
        db.session.flush()
        record_audit_event(
            context,
            module_id="workflows",
            action="transaction_template_created",
            entity_type="transaction_template",
            entity_id=row.id,
            detail={
                "name": row.name,
                "transaction_type": row.transaction_type,
                "amount_mode": row.amount_mode,
                "expected_amount": str(row.expected_amount) if row.expected_amount is not None else None,
                "frequency": row.frequency,
                "next_run_date": row.next_run_date.isoformat(),
                "posting_mode": "manual",
            },
        )
        db.session.commit()
        return row

    @staticmethod
    def list_templates(context: AccessContext):
        if not context.can("workflows.read"):
            raise PermissionError("workflows.read")
        return (
            TransactionTemplate.query.filter_by(organisation_id=context.organisation_id)
            .order_by(TransactionTemplate.is_active.desc(), TransactionTemplate.next_run_date.asc(), TransactionTemplate.name.asc())
            .all()
        )

    @staticmethod
    def list_items(context: AccessContext, *, limit: int = 250):
        if not context.can("workflows.read"):
            raise PermissionError("workflows.read")
        return (
            ScheduledTransaction.query.filter_by(organisation_id=context.organisation_id)
            .order_by(ScheduledTransaction.scheduled_date.desc(), ScheduledTransaction.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def set_template_active(context: AccessContext, template_id: str, *, active: bool):
        if not context.can("workflows.write"):
            raise PermissionError("workflows.write")
        row = db.session.get(TransactionTemplate, template_id)
        if not row or row.organisation_id != context.organisation_id:
            raise WorkflowError("Transaction template not found")
        row.is_active = bool(active)
        record_audit_event(
            context,
            module_id="workflows",
            action="transaction_template_enabled" if active else "transaction_template_disabled",
            entity_type="transaction_template",
            entity_id=row.id,
            detail={"name": row.name},
        )
        db.session.commit()
        return row

    @staticmethod
    def generate_due(context: AccessContext, *, through_date: date | None = None) -> list[ScheduledTransaction]:
        if not context.can("workflows.write"):
            raise PermissionError("workflows.write")
        through_date = through_date or date.today()
        templates = (
            TransactionTemplate.query.filter(
                TransactionTemplate.organisation_id == context.organisation_id,
                TransactionTemplate.is_active.is_(True),
                TransactionTemplate.next_run_date <= through_date,
            )
            .order_by(TransactionTemplate.next_run_date.asc())
            .all()
        )
        generated = []
        for template in templates:
            loops = 0
            while template.is_active and template.next_run_date <= through_date:
                loops += 1
                if loops > 36:
                    raise WorkflowError(f"Template {template.name} has more than 36 overdue occurrences; review it manually")
                scheduled_date = template.next_run_date
                if template.end_date and scheduled_date > template.end_date:
                    template.is_active = False
                    break
                existing = ScheduledTransaction.query.filter_by(
                    template_id=template.id,
                    scheduled_date=scheduled_date,
                ).first()
                if not existing:
                    item = ScheduledTransaction(
                        organisation_id=context.organisation_id,
                        template_id=template.id,
                        scheduled_date=scheduled_date,
                        transaction_type=template.transaction_type,
                        description=template.description or template.name,
                        expected_amount=template.expected_amount,
                        currency=template.currency,
                        bank_account_id=template.bank_account_id,
                        counter_account_id=template.counter_account_id,
                        reference=template.reference,
                        status="generated",
                    )
                    db.session.add(item)
                    db.session.flush()
                    workflow = WorkflowService.start(
                        context,
                        entity_type="scheduled_transaction",
                        entity_id=item.id,
                        title=template.name,
                        amount=item.expected_amount,
                        currency=item.currency,
                        source_module="workflows",
                        metadata={
                            "transaction_type": item.transaction_type,
                            "template_id": template.id,
                            "scheduled_date": scheduled_date.isoformat(),
                            "create_post_action": True,
                        },
                        definition_id=template.workflow_definition_id,
                        originator_user_id=template.created_by_user_id,
                        create_post_action=True,
                        commit=False,
                    )
                    item.workflow_instance_id = workflow.id
                    item.status = workflow.status
                    record_audit_event(
                        context,
                        module_id="workflows",
                        action="scheduled_transaction_generated",
                        entity_type="scheduled_transaction",
                        entity_id=item.id,
                        detail={
                            "template_id": template.id,
                            "scheduled_date": scheduled_date.isoformat(),
                            "transaction_type": item.transaction_type,
                            "workflow_instance_id": workflow.id,
                            "status": workflow.status,
                        },
                    )
                    generated.append(item)
                template.next_run_date = _advance(scheduled_date, template.frequency)
                if template.end_date and template.next_run_date > template.end_date:
                    template.is_active = False
            db.session.flush()
        db.session.commit()
        return generated

    @staticmethod
    def generate_due_once_per_day(context: AccessContext, *, through_date: date | None = None):
        through_date = through_date or date.today()
        marker = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope="workflows",
            key="last_due_generation_date",
        ).first()
        marker_date = None
        if marker and isinstance(marker.value, dict):
            marker_date = marker.value.get("date")
        if marker_date == through_date.isoformat():
            return []
        generated = RecurringTransactionService.generate_due(context, through_date=through_date)
        if marker is None:
            marker = Setting(
                organisation_id=context.organisation_id,
                scope="workflows",
                key="last_due_generation_date",
                value={"date": through_date.isoformat()},
            )
            db.session.add(marker)
        else:
            marker.value = {"date": through_date.isoformat()}
        db.session.commit()
        return generated

    @staticmethod
    def _amount_for_post(item: ScheduledTransaction, actual_amount) -> Decimal:
        template = item.template
        actual = _money(actual_amount, allow_none=True)
        if actual is None:
            actual = _money(item.expected_amount, allow_none=True)
        if actual is None or actual <= 0:
            raise WorkflowError("Enter the actual amount before posting this transaction")
        expected = _money(item.expected_amount, allow_none=True)
        if template.amount_mode == "fixed" and expected is not None and actual != expected:
            raise WorkflowError("Fixed recurring transactions must post at the configured amount")
        if template.amount_mode == "expected" and expected is not None and template.tolerance is not None:
            tolerance = _money(template.tolerance) or Decimal("0.00")
            if abs(actual - expected) > tolerance:
                raise WorkflowError("Actual amount is outside the configured tolerance; return the item for review")
        return actual

    @staticmethod
    def post_from_action(
        context: AccessContext,
        action_id: str,
        *,
        actual_amount=None,
        posting_date: date | None = None,
    ) -> ScheduledTransaction:
        if not context.can("workflows.post"):
            raise PermissionError("workflows.post")
        if not context.can("ledger.journals.post"):
            raise PermissionError("ledger.journals.post")
        action = db.session.get(UserAction, action_id)
        if not action or action.organisation_id != context.organisation_id or action.status != "open":
            raise WorkflowError("Open posting action not found")
        if action.action_type != "post":
            raise WorkflowError("This user action is not a posting action")
        if not WorkflowService._can_access_action(context, action):
            raise PermissionError("This action is assigned to another user or role")
        instance = action.workflow_instance
        if instance.entity_type != "scheduled_transaction" or instance.status != "ready_to_post":
            raise WorkflowError("Workflow is not ready for posting")
        item = db.session.get(ScheduledTransaction, instance.entity_id)
        if not item or item.organisation_id != context.organisation_id or item.status == "posted":
            raise WorkflowError("Scheduled transaction is not available for posting")

        amount = RecurringTransactionService._amount_for_post(item, actual_amount)
        bank, counter = RecurringTransactionService._validate_accounts(
            context, item.transaction_type, item.bank_account_id, item.counter_account_id
        )
        if item.transaction_type == "income":
            lines = [
                {"account_id": bank.id, "debit": amount, "credit": 0, "description": item.description, "currency": item.currency},
                {"account_id": counter.id, "debit": 0, "credit": amount, "description": item.description, "currency": item.currency},
            ]
        elif item.transaction_type == "expense":
            lines = [
                {"account_id": counter.id, "debit": amount, "credit": 0, "description": item.description, "currency": item.currency},
                {"account_id": bank.id, "debit": 0, "credit": amount, "description": item.description, "currency": item.currency},
            ]
        else:
            lines = [
                {"account_id": counter.id, "debit": amount, "credit": 0, "description": item.description, "currency": item.currency},
                {"account_id": bank.id, "debit": 0, "credit": amount, "description": item.description, "currency": item.currency},
            ]

        effective_date = posting_date or item.scheduled_date
        journal = LedgerService.post_journal(
            context,
            journal_date=effective_date,
            description=item.description,
            reference=item.reference or item.template.name,
            lines=lines,
            source_module="workflows",
            source_reference=item.id,
            metadata={
                "scheduled_transaction_id": item.id,
                "transaction_template_id": item.template_id,
                "workflow_instance_id": instance.id,
            },
            commit=False,
        )
        item.actual_amount = amount
        item.journal_id = journal.id
        item.status = "posted"
        instance.status = "posted"
        instance.completed_at = utcnow()
        action.status = "completed"
        action.decision = "posted"
        action.completed_by_user_id = context.user_id
        action.completed_at = utcnow()
        for other in instance.actions:
            if other.id != action.id and other.status == "open":
                other.status = "cancelled"
        record_audit_event(
            context,
            module_id="workflows",
            action="scheduled_transaction_posted",
            entity_type="scheduled_transaction",
            entity_id=item.id,
            detail={
                "journal_id": journal.id,
                "posting_date": effective_date.isoformat(),
                "amount": str(amount),
                "transaction_type": item.transaction_type,
                "template_id": item.template_id,
            },
        )
        db.session.commit()
        return item
