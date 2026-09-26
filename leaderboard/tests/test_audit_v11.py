"""Formulaire (réservé aux évaluateurs), enregistrement, bilan et page publique AXIOM v1.1."""

import base64
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

LEADERBOARD_DIR = Path(__file__).resolve().parents[1]
TOKEN = "t" * 32
BASIC = {"Authorization": "Basic " + base64.b64encode(f"claire:{TOKEN}".encode()).decode()}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUDITOR_TOKENS", f"claire:{TOKEN}")
    monkeypatch.syspath_prepend(str(LEADERBOARD_DIR))
    for mod in ("server", "security", "badge_tier", "db", "framework_watch", "organizational_audit",
                "axiom", "axiom_pages", "ai_audit_assist"):
        sys.modules.pop(mod, None)
    server = importlib.import_module("server")
    return server, server.app.test_client(), tmp_path


def _post(c, entries, company="Acme", repo="", headers=BASIC):
    return c.post("/submit-audit", json={"company_name": company, "linked_repo_url": repo, "entries": entries},
                  headers=headers)


def test_form_is_reserved_to_auditors(client):
    _, c, _ = client
    r = c.get("/audit")
    assert r.status_code == 401 and r.headers["WWW-Authenticate"].startswith("Basic")
    wrong = {"Authorization": "Basic " + base64.b64encode(b"mallory:" + TOKEN.encode()).decode()}
    assert c.get("/audit", headers=wrong).status_code == 401  # nom qui ne correspond pas au jeton
    form = c.get("/audit", headers=BASIC)
    html = form.get_data(as_text=True)
    assert form.status_code == 200 and html.count('data-id="') == 27
    assert "texte fictif de test" in html and "claire" in html
    assert form.headers["Cache-Control"] == "private, no-store"


def test_public_methodology_page_has_no_confidential_content(client):
    _, c, _ = client
    page = c.get("/methodologie").get_data(as_text=True)
    assert "AXIOM v1.1" in page and "9.4" in page and "Source publique" in page
    assert "texte fictif" not in page and "preuve fictive" not in page and "Bonne pratique fictive" not in page
    assert "pondération 5" not in page and "pondération 8" not in page
    assert c.get("/methodologie.json").status_code == 404


def test_grid_not_configured(client, monkeypatch):
    server, c, _ = client
    monkeypatch.delenv("AXIOM_METHODOLOGY_FILE")
    server.axiom.load_methodology.cache_clear()
    assert c.get("/audit", headers=BASIC).status_code == 503
    assert _post(c, [{"id": "1.1", "level": 2, "evidence": "Document"}]).status_code == 503
    assert c.get("/methodologie").status_code == 200


def test_low_coverage_gives_no_tier(client):
    _, c, _ = client
    r = _post(c, [{"id": "1.1", "level": 4, "evidence": "Vérifiée par l'évaluateur", "justification": "x"}])
    body = r.get_json()
    assert r.status_code == 200
    assert body["percentage"] == 100.0 and body["coverage"] < 80
    assert body["tier"] == "none" and "Couverture" in body["reason"]


def test_evidence_caps_applied_and_shown_in_report(client):
    server, c, tmp = client
    subs = server.axiom.load_public()["sub_domains"]
    entries = [{"id": s["id"], "level": 4, "evidence": "Document", "justification": "doc interne"} for s in subs]
    body = _post(c, entries, headers={"Authorization": f"Bearer {TOKEN}"}).get_json()  # l'API accepte aussi Bearer
    assert body["percentage"] < 100
    page = c.get(body["report_url"]).get_data(as_text=True)
    assert "plafonné à 3 par le type de preuve" in page and "mesure technique exigée" in page
    assert "claire" in page and "AXIOM v1.1" in page
    assert "texte fictif" not in page  # le bilan ne recopie pas la grille
    row = sqlite3.connect(tmp / "leaderboard.db").execute(
        "SELECT methodology_version, coverage, answers_json FROM org_audits").fetchone()
    assert row[0] == "1.1" and row[1] == 100.0
    assert json.loads(row[2])["entries"][0]["evidence"] == "Document"


def test_invalid_entries_rejected(client):
    _, c, _ = client
    assert _post(c, [{"id": "1.1", "level": 7}]).status_code == 400
    assert _post(c, [{"id": "42.1", "level": 2}]).status_code == 400
    assert _post(c, [{"id": "1.1", "level": "N/A"}]).status_code == 400


def test_legacy_audit_still_renders(client):
    server, c, tmp = client
    conn = sqlite3.connect(tmp / "leaderboard.db")
    n = len(server.AUDIT_QUESTIONNAIRE)
    conn.execute("INSERT INTO org_audits (company_name, answers_json, evidences_json, percentage, tier, auditor, "
                 "report_token) VALUES ('Ancienne', ?, ?, 50, 'none', 'claire', ?)",
                 (json.dumps([2] * n), json.dumps([""] * n), "L" * 32))
    conn.commit()
    conn.close()
    page = c.get("/audit-report/" + "L" * 32)
    assert page.status_code == 200 and "Ancienne" in page.get_data(as_text=True)
