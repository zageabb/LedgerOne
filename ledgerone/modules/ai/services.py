from __future__ import annotations

import json
from typing import Any

import requests

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.models.core import utcnow
from ledgerone.modules.ai.configuration import AIConfiguration
from ledgerone.modules.ai.knowledge import KnowledgeService
from ledgerone.modules.ai.models import AIConversation, AIInteraction
from ledgerone.modules.ai.tools import available_tools
from ledgerone.services.context import AccessContext


class LocalAIError(RuntimeError):
    pass


def _identity_id(context: AccessContext) -> str | None:
    return context.user_id or context.api_key_id


class LocalAIService:
    @staticmethod
    def status(organisation_id: str):
        config = AIConfiguration.get(organisation_id)
        result = AIConfiguration.probe(base_url=config["base_url"], timeout=3)
        return {
            "enabled": config["enabled"],
            "reachable": result["reachable"] if config["enabled"] else False,
            "model": config["model"],
            "models": result.get("models", []),
            "base_url": config["base_url"],
            "timeout": config["timeout"],
            "allow_writes": config["allow_writes"],
            **({"error": result.get("error")} if result.get("error") and config["enabled"] else {}),
        }

    @staticmethod
    def _call_model(messages: list[dict], config: dict) -> str:
        if not config.get("enabled", True):
            raise LocalAIError("Local AI is disabled")
        try:
            response = requests.post(
                f"{config['base_url']}/api/chat",
                json={
                    "model": config["model"],
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2},
                },
                timeout=config.get("timeout", 120),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LocalAIError(f"Could not reach local AI server: {exc}") from exc
        payload = response.json()
        return payload.get("message", {}).get("content", "")

    @staticmethod
    def _parse_model_json(content: str) -> dict:
        try:
            value = json.loads(content)
            return value if isinstance(value, dict) else {"message": str(value), "tool_calls": []}
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                try:
                    value = json.loads(content[start:end + 1])
                    if isinstance(value, dict):
                        return value
                except json.JSONDecodeError:
                    pass
            return {"message": content, "tool_calls": []}

    @staticmethod
    def _system_prompt(
        organisation_name: str,
        tools: dict,
        allow_writes: bool,
        knowledge: list[dict] | None = None,
    ) -> str:
        tool_lines = "\n".join(
            f"- {name} [{'WRITE' if spec.write else 'READ'}]: {spec.description}"
            for name, spec in tools.items()
        ) or "- No LedgerOne data tools are permitted for this caller."

        convention_help = {
            "ledger.create_account": "code, name, account_type, optional currency, parent_id.",
            "ledger.post_journal": "date YYYY-MM-DD, description, optional reference, lines[] with account_id, debit, credit, optional description/dimensions.",
            "sales.create_customer": "name, optional email, phone.",
            "sales.create_invoice": "customer_id, invoice_number, amount, receivable_account_id, revenue_account_id, optional invoice_date, due_date, description, currency.",
            "purchases.create_supplier": "name, optional email, phone.",
            "purchases.create_bill": "supplier_id, bill_number, amount, payable_account_id, expense_account_id, optional bill_date, due_date, description, currency.",
        }
        convention_lines = "\n".join(
            f"- {name}: {convention_help[name]}"
            for name in tools
            if name in convention_help
        ) or "- No special write-tool argument conventions apply to the tools permitted for this caller."

        write_policy = (
            "WRITE SAFETY: This message has explicit write approval. You may use a WRITE tool only if it is listed below and the user's request clearly requires that change. The caller's own permissions still apply."
            if allow_writes
            else "WRITE SAFETY: This message is read-only. No WRITE tools are available and you must not claim to have changed accounting data."
        )

        knowledge_text = ""
        if knowledge:
            blocks = []
            for item in knowledge:
                excerpt = str(item.get("excerpt") or "")[:1800]
                blocks.append(
                    f"[Knowledge: {item.get('title', 'Untitled')} | chunk {item.get('chunk_index', 0)}]\n{excerpt}"
                )
            knowledge_text = (
                "\n\nORGANISATION KNOWLEDGE\n"
                "Use this only when relevant. Cite procedural/manual guidance as [Knowledge: title]. "
                "Live LedgerOne tool results and accounting controls remain authoritative if there is a conflict.\n\n"
                + "\n\n".join(blocks)
            )

        return f"""You are LedgerOne AI, the local accounting assistant for {organisation_name}.
You operate only with the permissions of the requesting user or API key. A missing tool is forbidden; never try to work around permission limits.
Never invent database IDs: use a permitted read tool first when an ID is required. Use tools whenever the answer depends on live LedgerOne data.

{write_policy}

Return ONLY valid JSON in this exact shape:
{{"message":"brief user-facing response","tool_calls":[{{"name":"tool.name","arguments":{{}}}}]}}
If no tool is needed, return an empty tool_calls array. After tool results are supplied, use them to answer or request another permitted tool call.

Available tools:
{tool_lines}

Important argument conventions for permitted tools only:
{convention_lines}
Read-list tools accept an optional limit where relevant.
{knowledge_text}
"""

    @staticmethod
    def _audit_tool(
        context: AccessContext,
        model: str,
        tool_name: str,
        arguments: dict,
        result: Any,
    ):
        serialised = json.dumps(result, default=str)
        if len(serialised) > 5000:
            serialised = serialised[:5000] + "..."
        db.session.add(
            AuditEvent(
                organisation_id=context.organisation_id,
                actor_type=context.identity_type,
                actor_id=_identity_id(context),
                module_id="ai",
                action="tool_call",
                entity_type="tool",
                entity_id=tool_name,
                detail={
                    "model": model,
                    "requester_type": context.identity_type,
                    "requester_id": _identity_id(context),
                    "arguments": arguments,
                    "result": serialised,
                },
            )
        )
        db.session.commit()

    @staticmethod
    def _conversation_query(context: AccessContext):
        return AIConversation.query.filter_by(
            organisation_id=context.organisation_id,
            owner_identity_type=context.identity_type,
            owner_identity_id=_identity_id(context),
        )

    @classmethod
    def get_conversation(cls, context: AccessContext, conversation_id: str):
        row = cls._conversation_query(context).filter_by(id=conversation_id).first()
        if not row:
            raise LocalAIError("Conversation not found")
        return row

    @classmethod
    def _adopt_legacy_interactions(cls, context: AccessContext) -> None:
        """Turn pre-conversation browser AI interactions into reopenable conversations.

        Older LedgerOne builds stored one interaction per request. For signed-in users we can
        safely attach their own ungrouped rows to one-message conversations the first time
        they open the new workspace. API-key interactions from the legacy schema cannot be
        attributed reliably and are intentionally left untouched.
        """
        if context.identity_type != "user" or not context.user_id:
            return
        legacy = (
            AIInteraction.query.filter_by(
                organisation_id=context.organisation_id,
                user_id=context.user_id,
                conversation_id=None,
            )
            .order_by(AIInteraction.created_at.asc())
            .all()
        )
        if not legacy:
            return
        for interaction in legacy:
            conversation = AIConversation(
                organisation_id=context.organisation_id,
                owner_identity_type="user",
                owner_identity_id=context.user_id,
                title=(interaction.prompt or "Previous conversation")[:180],
                created_at=interaction.created_at,
                updated_at=interaction.created_at,
            )
            db.session.add(conversation)
            db.session.flush()
            interaction.conversation_id = conversation.id
            interaction.requester_type = interaction.requester_type or "user"
            interaction.requester_id = interaction.requester_id or context.user_id
        db.session.commit()

    @classmethod
    def list_conversations(cls, context: AccessContext, *, include_archived: bool = False, limit: int = 100):
        cls._adopt_legacy_interactions(context)
        query = cls._conversation_query(context)
        if not include_archived:
            query = query.filter_by(archived=False)
        return query.order_by(AIConversation.updated_at.desc()).limit(min(max(int(limit), 1), 200)).all()

    @classmethod
    def create_conversation(cls, context: AccessContext, *, title: str | None = None):
        row = AIConversation(
            organisation_id=context.organisation_id,
            owner_identity_type=context.identity_type,
            owner_identity_id=_identity_id(context),
            title=(title or "New conversation")[:180],
        )
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def rename_conversation(cls, context: AccessContext, conversation_id: str, title: str):
        row = cls.get_conversation(context, conversation_id)
        title = (title or "").strip()
        if not title:
            raise LocalAIError("Conversation title is required")
        row.title = title[:180]
        row.updated_at = utcnow()
        db.session.commit()
        return row

    @classmethod
    def archive_conversation(cls, context: AccessContext, conversation_id: str):
        row = cls.get_conversation(context, conversation_id)
        row.archived = True
        row.updated_at = utcnow()
        db.session.commit()
        return row

    @staticmethod
    def _history_messages(conversation: AIConversation, *, limit: int = 12) -> list[dict]:
        rows = (
            AIInteraction.query.filter_by(
                organisation_id=conversation.organisation_id,
                conversation_id=conversation.id,
            )
            .order_by(AIInteraction.created_at.desc())
            .limit(max(1, min(int(limit), 30)))
            .all()
        )
        messages: list[dict] = []
        for row in reversed(rows):
            messages.append({"role": "user", "content": row.prompt})
            if row.response:
                messages.append({"role": "assistant", "content": row.response})
        return messages

    @classmethod
    def chat(
        cls,
        *,
        context: AccessContext,
        organisation_name: str,
        prompt: str,
        conversation_id: str | None = None,
        approve_writes: bool = False,
    ):
        if not context or not context.organisation_id:
            raise LocalAIError("Authorisation context is required")
        if not context.can("ai.use"):
            raise LocalAIError("Missing permission: ai.use")

        config = AIConfiguration.get(context.organisation_id)
        if not config["enabled"]:
            raise LocalAIError("Local AI is disabled")

        write_approved = bool(config["allow_writes"] and approve_writes)
        tools = available_tools(context, allow_writes=write_approved)

        if conversation_id:
            conversation = cls.get_conversation(context, conversation_id)
        else:
            conversation = cls.create_conversation(
                context,
                title=(prompt.strip().replace("\n", " ")[:72] or "New conversation"),
            )

        knowledge: list[dict] = []
        if context.can("ai.knowledge.read"):
            try:
                knowledge = KnowledgeService.retrieve(context, prompt, limit=4)
            except PermissionError:
                knowledge = []

        history_messages = cls._history_messages(conversation)
        interaction = AIInteraction(
            organisation_id=context.organisation_id,
            conversation_id=conversation.id,
            user_id=context.user_id,
            requester_type=context.identity_type,
            requester_id=_identity_id(context),
            prompt=prompt,
            model=config["model"],
            tool_log=[],
            knowledge_log=[
                {
                    "source_id": item["source_id"],
                    "title": item["title"],
                    "filename": item.get("filename"),
                    "chunk_index": item["chunk_index"],
                    "score": item["score"],
                }
                for item in knowledge
            ],
        )
        db.session.add(interaction)
        db.session.commit()

        messages = [
            {
                "role": "system",
                "content": cls._system_prompt(
                    organisation_name,
                    tools,
                    write_approved,
                    knowledge,
                ),
            },
            *history_messages,
            {"role": "user", "content": prompt},
        ]
        tool_log = []
        final_message = ""

        try:
            for _ in range(4):
                content = cls._call_model(messages, config)
                plan = cls._parse_model_json(content)
                final_message = str(plan.get("message") or "")
                calls = plan.get("tool_calls") or []
                if not calls:
                    break

                results = []
                for call in calls[:5]:
                    name = call.get("name")
                    arguments = call.get("arguments") or {}
                    spec = tools.get(name)
                    if not spec:
                        result = {"error": f"Unknown, disabled or disallowed tool: {name}"}
                    else:
                        try:
                            result = spec.handler(context, arguments)
                        except Exception as exc:
                            result = {"error": str(exc)}
                    log_entry = {"tool": name, "arguments": arguments, "result": result}
                    tool_log.append(log_entry)
                    results.append(log_entry)
                    cls._audit_tool(
                        context,
                        config["model"],
                        name or "unknown",
                        arguments,
                        result,
                    )

                tool_text = json.dumps(results, default=str)
                if len(tool_text) > 20000:
                    tool_text = tool_text[:20000] + "..."
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": f"TOOL RESULTS:\n{tool_text}\nUse these results. Return the required JSON. Request more tools only if necessary.",
                    }
                )
            else:
                final_message = final_message or "The tool-call limit was reached."

            interaction.response = final_message
            interaction.tool_log = tool_log
            interaction.success = True
            conversation.updated_at = utcnow()
            if conversation.title == "New conversation":
                conversation.title = (prompt.strip().replace("\n", " ")[:72] or "Conversation")
            db.session.commit()
            return {
                "message": final_message,
                "tools": tool_log,
                "knowledge": interaction.knowledge_log,
                "interaction_id": interaction.id,
                "conversation_id": conversation.id,
                "writes_approved": write_approved,
            }
        except LocalAIError as exc:
            interaction.success = False
            interaction.error = str(exc)
            interaction.tool_log = tool_log
            conversation.updated_at = utcnow()
            db.session.commit()
            raise
        except Exception as exc:
            interaction.success = False
            interaction.error = str(exc)
            interaction.tool_log = tool_log
            conversation.updated_at = utcnow()
            db.session.commit()
            raise LocalAIError(str(exc)) from exc
