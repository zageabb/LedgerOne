from __future__ import annotations

import json
from typing import Any

import requests

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.modules.ai.configuration import AIConfiguration
from ledgerone.modules.ai.models import AIInteraction
from ledgerone.modules.ai.tools import available_tools
from ledgerone.services.context import AccessContext


class LocalAIError(RuntimeError):
    pass


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
    def _system_prompt(organisation_name: str, tools: dict, allow_writes: bool) -> str:
        tool_lines = "\n".join(
            f"- {name} [{'WRITE' if spec.write else 'READ'}]: {spec.description}"
            for name, spec in tools.items()
        )
        write_policy = (
            "WRITE SAFETY: You may use WRITE tools only when the user's request explicitly asks you to create, add, record, post or change accounting data. Do not perform writes merely to answer a question. Explain completed changes clearly."
            if allow_writes
            else "WRITE SAFETY: This organisation has disabled AI writes. You have read-only tools and must not claim to have changed accounting data."
        )
        return f"""You are LedgerOne AI, the trusted local accounting assistant for {organisation_name}.
You have internal access to enabled LedgerOne modules through the tools below. Never invent database IDs: use a read tool first when an ID is required. Use tools whenever the answer depends on LedgerOne data.

{write_policy}

Return ONLY valid JSON in this exact shape:
{{"message":"brief user-facing response","tool_calls":[{{"name":"tool.name","arguments":{{}}}}]}}
If no tool is needed, return an empty tool_calls array. After tool results are supplied, use them to answer or request another tool call.

Available tools:
{tool_lines}

Important argument conventions:
- ledger.create_account: code, name, account_type, optional currency, parent_id.
- ledger.post_journal: date YYYY-MM-DD, description, optional reference, lines[] with account_id, debit, credit, optional description/dimensions.
- sales.create_customer: name, optional email, phone.
- sales.create_invoice: customer_id, invoice_number, amount, receivable_account_id, revenue_account_id, optional invoice_date, due_date, description, currency.
- purchases.create_supplier: name, optional email, phone.
- purchases.create_bill: supplier_id, bill_number, amount, payable_account_id, expense_account_id, optional bill_date, due_date, description, currency.
Read-list tools accept an optional limit where relevant.
"""

    @staticmethod
    def _audit_tool(
        organisation_id: str,
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
                organisation_id=organisation_id,
                actor_type="local_ai",
                actor_id=model,
                module_id="ai",
                action="tool_call",
                entity_type="tool",
                entity_id=tool_name,
                detail={"arguments": arguments, "result": serialised},
            )
        )
        db.session.commit()

    @classmethod
    def chat(
        cls,
        *,
        organisation_id: str,
        organisation_name: str,
        user_id: str | None,
        prompt: str,
    ):
        config = AIConfiguration.get(organisation_id)
        if not config["enabled"]:
            raise LocalAIError("Local AI is disabled")

        tools = available_tools(
            organisation_id,
            allow_writes=config["allow_writes"],
        )
        system_context = AccessContext.system(organisation_id)
        interaction = AIInteraction(
            organisation_id=organisation_id,
            user_id=user_id,
            prompt=prompt,
            model=config["model"],
            tool_log=[],
        )
        db.session.add(interaction)
        db.session.commit()

        messages = [
            {
                "role": "system",
                "content": cls._system_prompt(
                    organisation_name,
                    tools,
                    config["allow_writes"],
                ),
            },
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
                            result = spec.handler(system_context, arguments)
                        except Exception as exc:
                            result = {"error": str(exc)}
                    log_entry = {"tool": name, "arguments": arguments, "result": result}
                    tool_log.append(log_entry)
                    results.append(log_entry)
                    cls._audit_tool(
                        organisation_id,
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
            db.session.commit()
            return {
                "message": final_message,
                "tools": tool_log,
                "interaction_id": interaction.id,
            }
        except LocalAIError as exc:
            interaction.success = False
            interaction.error = str(exc)
            interaction.tool_log = tool_log
            db.session.commit()
            raise
        except Exception as exc:
            interaction.success = False
            interaction.error = str(exc)
            interaction.tool_log = tool_log
            db.session.commit()
            raise LocalAIError(str(exc)) from exc
