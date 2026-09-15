import json

from ledgerone.extensions import db
from ledgerone.models.core import Organisation, User
from ledgerone.models.ledger import Journal
from ledgerone.modules.ai.knowledge import KnowledgeService
from ledgerone.modules.ai.models import AIConversation, AIInteraction
from ledgerone.modules.ai.services import LocalAIService
from ledgerone.modules.ai.tools import available_tools
from ledgerone.services.context import AccessContext


def _ai_config(*, allow_writes=True):
    return {
        "enabled": True,
        "base_url": "http://local-ai.invalid",
        "model": "test-model",
        "timeout": 1,
        "allow_writes": allow_writes,
    }


def test_ai_tools_never_expand_caller_permissions(app):
    with app.app_context():
        organisation = Organisation.query.first()
        read_context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id="reader",
            permissions=frozenset({"ai.use", "ledger.read", "sales.read"}),
        )
        tools = available_tools(read_context, allow_writes=True)

        assert "ledger.list_accounts" in tools
        assert "sales.list_customers" in tools
        assert "ledger.post_journal" not in tools
        assert "sales.create_customer" not in tools
        assert "sales.create_invoice" not in tools
        assert "purchases.create_supplier" not in tools
        assert "purchases.create_bill" not in tools

        writer = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id="writer",
            permissions=frozenset({"ai.use", "ledger.read", "ledger.journals.post"}),
        )
        assert "ledger.post_journal" in available_tools(writer, allow_writes=True)
        assert "ledger.post_journal" not in available_tools(writer, allow_writes=False)

        business_writer = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id="business-writer",
            permissions=frozenset({"ai.use", "sales.write", "purchases.write"}),
        )
        writable = available_tools(business_writer, allow_writes=True)
        assert "sales.create_invoice" in writable
        assert "purchases.create_bill" in writable
        assert all(not spec.write for spec in available_tools(business_writer, allow_writes=False).values())


def test_ai_api_key_scope_is_preserved(app):
    with app.app_context():
        organisation = Organisation.query.first()
        context = AccessContext(
            identity_type="api_key",
            organisation_id=organisation.id,
            api_key_id="scoped-key",
            permissions=frozenset({"ai.use", "sales.read"}),
        )
        tools = available_tools(context, allow_writes=True)
        assert "sales.list_customers" in tools
        assert "sales.create_invoice" not in tools
        assert "ledger.list_accounts" not in tools
        assert "ledger.post_journal" not in tools


def test_ai_cannot_execute_disallowed_write_even_when_model_requests_it(app, monkeypatch):
    with app.app_context():
        organisation = Organisation.query.first()
        user = User.query.first()
        context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id=user.id,
            permissions=frozenset({"ai.use", "ledger.read"}),
        )

        monkeypatch.setattr(
            "ledgerone.modules.ai.services.AIConfiguration.get",
            lambda organisation_id: _ai_config(allow_writes=True),
        )
        responses = iter(
            [
                json.dumps(
                    {
                        "message": "I will post it.",
                        "tool_calls": [
                            {
                                "name": "ledger.post_journal",
                                "arguments": {
                                    "description": "Forbidden AI journal",
                                    "lines": [],
                                },
                            }
                        ],
                    }
                ),
                json.dumps({"message": "I cannot post that with your permissions.", "tool_calls": []}),
            ]
        )
        monkeypatch.setattr(
            LocalAIService,
            "_call_model",
            staticmethod(lambda messages, config: next(responses)),
        )

        result = LocalAIService.chat(
            context=context,
            organisation_name=organisation.name,
            prompt="Post a journal for me",
            approve_writes=True,
        )

        assert Journal.query.count() == 0
        assert result["tools"][0]["result"]["error"].startswith("Unknown, disabled or disallowed tool")
        interaction = db.session.get(AIInteraction, result["interaction_id"])
        assert interaction.requester_type == "user"
        assert interaction.requester_id == user.id


def test_ai_chat_rejects_write_without_per_message_approval(app, monkeypatch):
    with app.app_context():
        organisation = Organisation.query.first()
        user = User.query.first()
        context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id=user.id,
            permissions=frozenset({"ai.use", "ledger.journals.post"}),
        )
        monkeypatch.setattr(
            "ledgerone.modules.ai.services.AIConfiguration.get",
            lambda organisation_id: _ai_config(allow_writes=True),
        )
        responses = iter(
            [
                json.dumps({
                    "message": "Posting.",
                    "tool_calls": [{"name": "ledger.post_journal", "arguments": {"lines": []}}],
                }),
                json.dumps({"message": "Write approval is required.", "tool_calls": []}),
            ]
        )
        monkeypatch.setattr(
            LocalAIService,
            "_call_model",
            staticmethod(lambda messages, config: next(responses)),
        )
        result = LocalAIService.chat(
            context=context,
            organisation_name=organisation.name,
            prompt="Post this journal",
            approve_writes=False,
        )
        assert result["writes_approved"] is False
        assert Journal.query.count() == 0
        assert "disallowed tool" in result["tools"][0]["result"]["error"]


def test_ai_write_tools_require_per_message_approval(app):
    with app.app_context():
        organisation = Organisation.query.first()
        context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id="writer",
            permissions=frozenset({"ai.use", "ledger.read", "ledger.journals.post"}),
        )
        assert "ledger.post_journal" in available_tools(context, allow_writes=True)
        assert "ledger.post_journal" not in available_tools(context, allow_writes=False)


def test_conversations_persist_and_are_owned_by_requester(app, monkeypatch):
    with app.app_context():
        organisation = Organisation.query.first()
        user = User.query.first()
        context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id=user.id,
            permissions=frozenset({"ai.use"}),
        )
        monkeypatch.setattr(
            "ledgerone.modules.ai.services.AIConfiguration.get",
            lambda organisation_id: _ai_config(allow_writes=False),
        )
        monkeypatch.setattr(
            LocalAIService,
            "_call_model",
            staticmethod(lambda messages, config: json.dumps({"message": "OK", "tool_calls": []})),
        )

        first = LocalAIService.chat(
            context=context,
            organisation_name=organisation.name,
            prompt="First question",
        )
        second = LocalAIService.chat(
            context=context,
            organisation_name=organisation.name,
            prompt="Second question",
            conversation_id=first["conversation_id"],
        )

        assert first["conversation_id"] == second["conversation_id"]
        conversation = db.session.get(AIConversation, first["conversation_id"])
        assert conversation.owner_identity_id == user.id
        assert AIInteraction.query.filter_by(conversation_id=conversation.id).count() == 2

        other_context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id="person-b",
            permissions=frozenset({"ai.use"}),
        )
        assert LocalAIService.list_conversations(other_context) == []


def test_knowledge_retrieval_is_organisation_scoped(app):
    with app.app_context():
        first_org = Organisation.query.first()
        second_org = Organisation(name="Second Ledger", slug="second-ledger", base_currency="GBP")
        db.session.add(second_org)
        db.session.commit()

        permissions = frozenset({"ai.knowledge.read", "ai.knowledge.manage"})
        first_context = AccessContext(
            identity_type="user",
            organisation_id=first_org.id,
            user_id="knowledge-owner",
            permissions=permissions,
        )
        second_context = AccessContext(
            identity_type="user",
            organisation_id=second_org.id,
            user_id="knowledge-owner",
            permissions=permissions,
        )

        source = KnowledgeService.create_text_source(
            first_context,
            title="Customer refund process",
            content="Customer refunds require an approved credit note before money is returned to the customer bank account.",
        )
        first_results = KnowledgeService.retrieve(first_context, "How do customer refunds work?")
        second_results = KnowledgeService.retrieve(second_context, "How do customer refunds work?")

        assert first_results
        assert first_results[0]["source_id"] == source.id
        assert second_results == []


def test_ai_injects_relevant_knowledge_without_granting_more_permissions(app, monkeypatch):
    with app.app_context():
        organisation = Organisation.query.first()
        context = AccessContext(
            identity_type="user",
            organisation_id=organisation.id,
            user_id="knowledge-user",
            permissions=frozenset({"ai.use", "ai.knowledge.read", "ai.knowledge.manage"}),
        )
        KnowledgeService.create_text_source(
            context,
            title="Invoice approval manual",
            content="Invoices over five thousand pounds require finance director approval before posting.",
        )
        monkeypatch.setattr(
            "ledgerone.modules.ai.services.AIConfiguration.get",
            lambda organisation_id: _ai_config(allow_writes=True),
        )
        captured = {}

        def fake_call(messages, config):
            captured["messages"] = messages
            return json.dumps({"message": "Use the approval process.", "tool_calls": []})

        monkeypatch.setattr(LocalAIService, "_call_model", staticmethod(fake_call))

        result = LocalAIService.chat(
            context=context,
            organisation_name=organisation.name,
            prompt="What approval is needed for a £6,000 invoice?",
            approve_writes=True,
        )

        system_prompt = captured["messages"][0]["content"]
        assert "[Knowledge: Invoice approval manual" in system_prompt
        assert "ledger.post_journal" not in system_prompt
        assert result["knowledge"][0]["title"] == "Invoice approval manual"


def test_ai_page_has_chat_layout_and_knowledge_link(app, client, monkeypatch):
    client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    monkeypatch.setattr(
        LocalAIService,
        "status",
        staticmethod(
            lambda organisation_id: {
                "enabled": True,
                "reachable": True,
                "model": "test-model",
                "models": ["test-model"],
                "base_url": "http://local",
                "timeout": 1,
                "allow_writes": True,
            }
        ),
    )

    response = client.get("/ai/?new=1")
    assert response.status_code == 200
    assert b"ai-conversation-list" in response.data
    assert b"ai-messages" in response.data
    assert b"ai-composer" in response.data
    assert b"Knowledge" in response.data
    assert b"Allow LedgerOne AI to make accounting changes for this message" in response.data
