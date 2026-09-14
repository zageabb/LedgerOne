from __future__ import annotations

import json
from typing import Any

import requests
from flask import current_app

from ledgerone.extensions import db
from ledgerone.models.audit import AuditEvent
from ledgerone.modules.ai.models import AIInteraction
from ledgerone.modules.ai.tools import available_tools
from ledgerone.services.context import AccessContext


class LocalAIError(RuntimeError):
    pass


class LocalAIService:
    @staticmethod
    def status():
        if not current_app.config.get("LOCAL_AI_ENABLED", True):
            return {"enabled": False, "reachable": False, "model": current_app.config.get("LOCAL_AI_MODEL")}
        base_url = current_app.config["LOCAL_AI_BASE_URL"]
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=3)
            response.raise_for_status()
            data = response.json()
            models = [item.get("name") for item in data.get("models", [])]
            return {
                "enabled": True,
                "reachable": True,
                "model": current_app.config["LOCAL_AI_MODEL"],
                "models": models,
                "base_url": base_url,
            }
        except Exception as exc:
            return {
                "enabled": True,
                "reachable": False,
                "model": current_app.config["LOCAL_AI_MODEL"],
                "base_url": base_url,
                "error": str(exc),
            }

    @staticmethod
    def _call_model(messages: list[dict]) -> str:
        if not current_app.config.get("LOCAL_AI_ENABLED", True):
            raise LocalAIError("Local AI is disabled")
        response = requests.post(
            f"{current_app.config['LOCAL_AI_BASE_URL']}/api/chat",
            json={
                "model": current_app.config["LOCAL_AI_MODEL"],
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2},
            },
            timeout=current_app.config.get("LOCAL_AI_TIMEOUT", 120),
        )
        response.raise_for_status()
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
    def _system_prompt(organisation_name: str, tools: dict) -> str:
        tool_lines = "\n".join(
            f"- {name} [{'WRITE' if spec.write else 'READ'}]: {spec.description}"
            for name, spec in tools.items()
        )
        return f"""You are LedgerOne AI, the trusted local accounting assistant for {organisation_name}.
You have full internal access to enabled LedgerOne modules through the tools below. Never invent database IDs: use a read tool first when an ID is required. Use tools whenever the answer depends on LedgerOne data.

WRITE SAFETY: You may use WRITE tools only when the user's request explicitly asks you to create, add, record, post or change accounting data. Do not perform writes merely to answer a question. Explain completed changes clearly.

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
    def _audit_tool(organisation_id: str, tool_name: str, arguments: dict, result: Any):
        serialised = json.dumps(result, default=str)
        if len(serialised) > 5000:
            serialised = serialised[:5000] + "..."
        db.session.add(
            AuditEvent(
                organisation_id=organisation_id,
                actor_type="local_ai",
                actor_id=current_app.config.get("LOCAL_AI_MODEL"),
                module_id="ai",
                action="tool_call",
                entity_type="tool",
                entity_id=tool_name,
                detail={"arguments": arguments, "result": serialised},
            )
        )
        db.session.commit()

    @classmethod
    def chat(cls, *, organisation_id: str, organisation_name: str, user_id: str | None,
             prompt: str):
        tools = available_tools(organisation_id)
        system_context = AccessContext.system(organisation_id)
        interaction = AIInteraction(
            organisation_id=organisation_id,
            user_id=user_id,
            prompt=prompt,
            model=current_app.config.get("LOCAL_AI_MODEL"),
            tool_log=[],
        )
        db.session.add(interaction)
        db.session.commit()

        messages = [
            {"role": "system", "content": cls._system_prompt(organisation_name, tools)},
            {"role": "user", "content": prompt},
        ]
        tool_log = []
        final_message = ""

        try:
            for _ in range(4):
                content = cls._call_model(messages)
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
                        result = {"error": f"Unknown or disabled tool: {name}"}
                    else:
                        try:
                            result = spec.handler(system_context, arguments)
                        except Exception as exc:
                            result = {"error": str(exc)}
                    log_entry = {"tool": name, "arguments": arguments, "result": result}
                    tool_log.append(log_entry)
                    results.append(log_entry)
                    cls._audit_tool(organisation_id, name or "unknown", arguments, result)

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
            return {"message": final_message, "tools": tool_log, "interaction_id": interaction.id}
        except Exception as exc:
            interaction.success = False
            interaction.error = str(exc)
            interaction.tool_log = tool_log
            db.session.commit()
            raise LocalAIError(str(exc)) from exc
