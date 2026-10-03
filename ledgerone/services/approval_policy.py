from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from ledgerone.extensions import db
from ledgerone.models.core import Setting, new_id, utcnow
from ledgerone.modules.workflows.models import WorkflowDefinition, WorkflowInstance
from ledgerone.modules.workflows.services import WorkflowError, WorkflowService
from ledgerone.services.audit import record_audit_event
from ledgerone.services.context import AccessContext


POLICY_KEYS = (
    "journal",
    "sales_invoice",
    "purchase_bill",
    "master_data",
    "payment",
    "bank_posting",
    "period_reopen",
    "control_adjustment",
    "ai_write",
)

WORKFLOW_ENTITY_POLICIES = {
    "journal": "journal",
    "sales_invoice": "sales_invoice",
    "purchase_bill": "purchase_bill",
}


class ApprovalRequired(ValueError):
    def __init__(self, workflow: WorkflowInstance):
        self.workflow = workflow
        super().__init__(
            f"Approval required before this operation can proceed "
            f"(workflow {workflow.id}, status {workflow.status})"
        )


class ApprovalPolicyService:
    SCOPE = "approval_policy"

    @staticmethod
    def _money(value) -> Decimal | None:
        if value in {None, ""}:
            return None
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid approval threshold/amount: {value}") from exc

    @staticmethod
    def get(context: AccessContext, policy_key: str) -> dict:
        if policy_key not in POLICY_KEYS:
            raise ValueError(f"Unsupported approval policy: {policy_key}")
        row = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=ApprovalPolicyService.SCOPE,
            key=policy_key,
        ).first()
        raw = dict(row.value or {}) if row else {}
        return {
            "enabled": bool(raw.get("enabled", False)),
            "threshold": raw.get("threshold"),
            "approval_role": raw.get("approval_role"),
            "separate_approver": bool(raw.get("separate_approver", True)),
        }

    @staticmethod
    def list(context: AccessContext) -> dict:
        return {key: ApprovalPolicyService.get(context, key) for key in POLICY_KEYS}

    @staticmethod
    def _ensure_definition(context: AccessContext, policy_key: str, policy: dict):
        entity_type = WORKFLOW_ENTITY_POLICIES.get(policy_key, "approval_request")
        name = f"Governance policy: {policy_key}"
        row = WorkflowDefinition.query.filter_by(
            organisation_id=context.organisation_id,
            name=name,
        ).first()
        threshold = ApprovalPolicyService._money(policy.get("threshold"))
        rules = {
            "transaction_types": [policy_key] if entity_type == "approval_request" else [],
            "min_amount": str(threshold) if threshold is not None else None,
            "max_amount": None,
            "separate_approver": bool(policy.get("separate_approver", True)),
            "system_policy_key": policy_key,
        }
        steps = [
            {
                "type": "approve",
                "label": f"Approve {policy_key.replace('_', ' ')}",
                "role": (policy.get("approval_role") or "").strip() or None,
            }
        ]
        if row is None:
            row = WorkflowDefinition(
                organisation_id=context.organisation_id,
                name=name,
                description="Managed by organisation approval policy",
                entity_type=entity_type,
                priority=5,
                rules_json=rules,
                steps_json=steps,
                is_active=bool(policy.get("enabled")),
                created_by_user_id=context.user_id,
            )
            db.session.add(row)
        else:
            row.entity_type = entity_type
            row.priority = 5
            row.rules_json = rules
            row.steps_json = steps
            row.is_active = bool(policy.get("enabled"))
        db.session.flush()
        return row

    @staticmethod
    def set(context: AccessContext, policy_key: str, *, enabled: bool, threshold=None,
            approval_role: str | None = None, separate_approver: bool = True) -> dict:
        if not context.can("workflows.manage"):
            raise PermissionError("workflows.manage")
        if policy_key not in POLICY_KEYS:
            raise ValueError(f"Unsupported approval policy: {policy_key}")
        clean_threshold = ApprovalPolicyService._money(threshold)
        if clean_threshold is not None and clean_threshold < 0:
            raise ValueError("Approval threshold cannot be negative")
        value = {
            "enabled": bool(enabled),
            "threshold": str(clean_threshold) if clean_threshold is not None else None,
            "approval_role": (approval_role or "").strip() or None,
            "separate_approver": bool(separate_approver),
        }
        row = Setting.query.filter_by(
            organisation_id=context.organisation_id,
            scope=ApprovalPolicyService.SCOPE,
            key=policy_key,
        ).first()
        if row is None:
            row = Setting(
                organisation_id=context.organisation_id,
                scope=ApprovalPolicyService.SCOPE,
                key=policy_key,
                value=value,
            )
            db.session.add(row)
        else:
            row.value = value
        definition = ApprovalPolicyService._ensure_definition(context, policy_key, value)
        record_audit_event(
            context,
            module_id="workflows",
            action="approval_policy_updated",
            entity_type="setting",
            entity_id=row.id,
            detail={"policy_key": policy_key, **value, "workflow_definition_id": definition.id},
        )
        db.session.commit()
        return value

    @staticmethod
    def _canonical(payload: dict) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def fingerprint(policy_key: str, payload: dict) -> str:
        return hashlib.sha256(
            f"{policy_key}\n{ApprovalPolicyService._canonical(payload)}".encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _applies(policy: dict, amount=None) -> bool:
        if not policy.get("enabled"):
            return False
        threshold = ApprovalPolicyService._money(policy.get("threshold"))
        if threshold is None:
            return True
        clean_amount = ApprovalPolicyService._money(amount)
        return clean_amount is not None and abs(clean_amount) >= threshold

    @staticmethod
    def _submission_context(context: AccessContext) -> AccessContext:
        if context.can("workflows.write"):
            return context
        return AccessContext(
            identity_type=context.identity_type,
            organisation_id=context.organisation_id,
            user_id=context.user_id,
            api_key_id=context.api_key_id,
            full_access=context.full_access,
            permissions=frozenset(set(context.permissions) | {"workflows.write"}),
        )

    @staticmethod
    def guard(context: AccessContext, policy_key: str, *, payload: dict,
              title: str, amount=None) -> WorkflowInstance | None:
        policy = ApprovalPolicyService.get(context, policy_key)
        if not ApprovalPolicyService._applies(policy, amount):
            return None
        fingerprint = ApprovalPolicyService.fingerprint(policy_key, payload)

        rows = (
            WorkflowInstance.query.filter_by(
                organisation_id=context.organisation_id,
                entity_type="approval_request",
            )
            .order_by(WorkflowInstance.created_at.desc())
            .limit(200)
            .all()
        )
        for row in rows:
            meta = row.metadata_json or {}
            if meta.get("approval_policy_key") != policy_key or meta.get("request_fingerprint") != fingerprint:
                continue
            if meta.get("approval_consumed_at"):
                continue
            if row.status == "ready_to_post":
                return row
            if row.status not in {"rejected", "superseded", "executed"}:
                raise ApprovalRequired(row)

        definition = ApprovalPolicyService._ensure_definition(context, policy_key, policy)
        request_id = new_id()
        workflow = WorkflowService.start(
            ApprovalPolicyService._submission_context(context),
            entity_type="approval_request",
            entity_id=request_id,
            title=title,
            amount=amount,
            source_module="governance",
            metadata={
                "transaction_type": policy_key,
                "approval_policy_key": policy_key,
                "request_fingerprint": fingerprint,
                "request_payload": payload,
            },
            definition_id=definition.id,
            originator_user_id=context.user_id,
            create_post_action=False,
            commit=False,
        )
        record_audit_event(
            context,
            module_id="workflows",
            action="approval_requested",
            entity_type="approval_request",
            entity_id=request_id,
            detail={
                "workflow_instance_id": workflow.id,
                "policy_key": policy_key,
                "request_fingerprint": fingerprint,
                "amount": str(amount) if amount is not None else None,
            },
        )
        db.session.commit()
        raise ApprovalRequired(workflow)

    @staticmethod
    def consume(context: AccessContext, workflow: WorkflowInstance | None, *, result: dict | None = None):
        if workflow is None:
            return
        if workflow.status != "ready_to_post":
            raise WorkflowError("Approval workflow is not ready for execution")
        metadata = dict(workflow.metadata_json or {})
        if metadata.get("approval_consumed_at"):
            raise WorkflowError("Approval has already been consumed")
        metadata["approval_consumed_at"] = utcnow().isoformat()
        metadata["approval_execution_result"] = result or {}
        workflow.metadata_json = metadata
        workflow.status = "executed"
        workflow.completed_at = utcnow()
        record_audit_event(
            context,
            module_id="workflows",
            action="approved_operation_executed",
            entity_type="approval_request",
            entity_id=workflow.entity_id,
            detail={
                "workflow_instance_id": workflow.id,
                "policy_key": metadata.get("approval_policy_key"),
                "result": result or {},
            },
        )
        db.session.commit()
