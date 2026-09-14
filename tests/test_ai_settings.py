from ledgerone.models.core import Organisation, Setting
from ledgerone.modules.ai.configuration import AIConfiguration
from ledgerone.modules.ai.tools import available_tools
from ledgerone.services.context import AccessContext


def test_ai_settings_fall_back_to_environment(app):
    with app.app_context():
        organisation = Organisation.query.first()
        config = AIConfiguration.get(organisation.id)
        assert config["enabled"] is False
        assert config["allow_writes"] is False
        assert config["model"] == app.config["LOCAL_AI_MODEL"]


def test_ai_settings_persist_per_organisation(app):
    with app.app_context():
        organisation = Organisation.query.first()
        context = AccessContext.system(organisation.id)
        updated = AIConfiguration.update(
            context,
            enabled=True,
            base_url="http://192.168.1.249:11434/",
            model="qwen3:14b",
            timeout=180,
            allow_writes=False,
        )
        assert updated["base_url"] == "http://192.168.1.249:11434"
        assert AIConfiguration.get(organisation.id)["timeout"] == 180
        row = Setting.query.filter_by(
            organisation_id=organisation.id,
            scope="ai",
            key="local_ai",
        ).one()
        assert row.value["model"] == "qwen3:14b"


def test_ai_read_only_mode_removes_write_tools(app):
    with app.app_context():
        organisation = Organisation.query.first()
        read_only = available_tools(organisation.id, allow_writes=False)
        assert "ledger.list_accounts" in read_only
        assert "ledger.create_account" not in read_only
        assert "ledger.post_journal" not in read_only
        assert all(not spec.write for spec in read_only.values())


def test_ai_probe_discovers_models(app, monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "qwen3:14b"}, {"name": "gemma3:12b"}]}

    monkeypatch.setattr(
        "ledgerone.modules.ai.configuration.requests.get",
        lambda *args, **kwargs: Response(),
    )

    with app.app_context():
        result = AIConfiguration.probe(base_url="http://ollama.local:11434")
        assert result["reachable"] is True
        assert result["models"] == ["gemma3:12b", "qwen3:14b"]


def test_settings_page_shows_ai_panel(app, client, monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "qwen3:14b"}]}

    monkeypatch.setattr(
        "ledgerone.modules.ai.configuration.requests.get",
        lambda *args, **kwargs: Response(),
    )
    response = client.post(
        "/auth/login",
        data={"email": "test-admin@ledgerone.local", "password": "test-password"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    response = client.get("/settings/")
    assert response.status_code == 200
    assert b"LedgerOne AI" in response.data
    assert b"Ollama / local AI server" in response.data
    assert b"qwen3:14b" in response.data
