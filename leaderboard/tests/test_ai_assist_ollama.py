"""Assistant de brouillon : modèle local Ollama uniquement (aucun appel réseau réel dans ces tests)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_audit_assist as assist  # noqa: E402
import axiom  # noqa: E402


class FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


@pytest.fixture(autouse=True)
def fresh_grid():
    axiom.load_methodology.cache_clear()


def test_refuses_remote_server():
    with pytest.raises(SystemExit, match="pas un serveur local"):
        assist.check_local("https://ollama.example.com", allow_remote=False)
    assist.check_local("http://localhost:11434", allow_remote=False)
    assist.check_local("http://127.0.0.1:11434", allow_remote=False)


def test_model_must_be_installed(monkeypatch):
    monkeypatch.setattr(assist.requests, "get", lambda *a, **k: FakeResp({"models": [{"name": "mistral-small:latest"}]}))
    assert assist.check_model("http://localhost:11434", "mistral-small") == "mistral-small"
    with pytest.raises(SystemExit, match="ollama pull llama3"):
        assist.check_model("http://localhost:11434", "llama3")
    with pytest.raises(SystemExit, match="Choisis un modèle"):
        assist.check_model("http://localhost:11434", None)


def test_full_run_with_fake_ollama(monkeypatch, tmp_path):
    (tmp_path / "charte.txt").write_text("Notre charte IA est publiée en interne.")
    sent = []

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        sent.append((url, json))
        prompt = json["messages"][0]["content"]
        if "[1.1]" in prompt:
            return FakeResp({"message": {"content": '{"level": 4, "evidence_quote": "charte — charte.txt", "confidence": "haute"}'}})
        if "[9.4]" in prompt:
            return FakeResp({"message": {"content": '{"level": 3.8, "evidence_quote": "filtrage — charte.txt", "confidence": "moyenne"}'}})
        if "[2.1]" in prompt:
            return FakeResp({"message": {"content": "pas du json"}})
        return FakeResp({"message": {"content": '{"level": null, "evidence_quote": "aucune mention trouvée", "confidence": "aucune_preuve"}'}})

    monkeypatch.setattr(assist.requests, "get", lambda *a, **k: FakeResp({"models": [{"name": "mistral-small:latest"}]}))
    monkeypatch.setattr(assist.requests, "post", fake_post)
    draft = assist.run_ai_assisted_audit(str(tmp_path), "mistral-small")

    assert len(sent) == 27 and all(u == "http://localhost:11434/api/chat" for u, _ in sent)
    assert all(p["format"] == "json" and p["options"]["temperature"] == 0 for _, p in sent)
    by_id = {a["id"]: a for a in draft["answers"]}
    assert by_id["1.1"]["retained"] == 3                                 # preuve « Document » : N3 max
    assert by_id["9.4"]["level"] == 4 and by_id["9.4"]["retained"] == 2  # arrondi + mesure technique exigée
    assert by_id["2.1"]["level"] is None                                 # réponse illisible -> non évalué
    assert draft["model"] == "ollama:mistral-small" and draft["human_reviewed"] is False
    json.dumps(draft)  # sérialisable pour draft_audit_result.json
