"""Tests des contrôles d'accès du service de classement.

Lancer depuis le dossier leaderboard/ :  python -m pytest tests -q
Aucun appel réseau : les clés publiques GitHub (JWKS) sont simulées.
"""

import importlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

LEADERBOARD_DIR = Path(__file__).resolve().parents[1]
AUDITOR_TOKEN = "a" * 32
ADMIN_TOKEN = "b" * 32

GITHUB_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ATTACKER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": GITHUB_KEY.public_key()})()


def oidc(repository="alice/weather-mcp", key=GITHUB_KEY, aud="mcp-trust-score",
         iss="https://token.actions.githubusercontent.com", exp_in=300):
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "iat": now, "exp": now + exp_in, "repository": repository,
              "workflow_ref": f"{repository}/.github/workflows/ci.yml@refs/heads/main",
              "run_id": "42", "ref": "refs/heads/main"}
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUDITOR_TOKENS", f"alice:{AUDITOR_TOKEN}")
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.syspath_prepend(str(LEADERBOARD_DIR))
    for mod in ("server", "security", "badge_tier", "db", "framework_watch", "organizational_audit"):
        sys.modules.pop(mod, None)
    server = importlib.import_module("server")
    import security
    monkeypatch.setattr(security, "_jwks_client", _FakeJWKS())
    return server, server.app.test_client(), tmp_path


def _submit(client, token=None, **payload):
    body = {"server_name": "weather", "nist_score": 90, "axiom_score": 95, **payload}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/submit", json=body, headers=headers)


# --- /submit -----------------------------------------------------------------

def test_submit_without_token_is_rejected(app_env):
    _, client, _ = app_env
    r = _submit(client, repo_url="https://github.com/victim/repo")
    assert r.status_code == 401


def test_submit_with_forged_token_is_rejected(app_env):
    _, client, _ = app_env
    assert _submit(client, oidc(key=ATTACKER_KEY)).status_code == 401
    assert _submit(client, oidc(aud="someone-else")).status_code == 401
    assert _submit(client, oidc(iss="https://evil.example.com")).status_code == 401
    assert _submit(client, oidc(exp_in=-3600)).status_code == 401


def test_submit_uses_repository_from_token(app_env):
    _, client, _ = app_env
    r = _submit(client, oidc("alice/weather-mcp"))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["repo_url"] == "https://github.com/alice/weather-mcp"
    board = client.get("/leaderboard.json").get_json()
    assert [e["repo_url"] for e in board] == ["https://github.com/alice/weather-mcp"]


def test_cannot_submit_for_someone_elses_repo(app_env):
    _, client, _ = app_env
    r = _submit(client, oidc("mallory/fake"), repo_url="https://github.com/victim/repo")
    assert r.status_code == 403
    assert client.get("/leaderboard.json").get_json() == []


def test_score_validation(app_env):
    _, client, _ = app_env
    assert _submit(client, oidc(), nist_score="100").status_code == 400
    assert _submit(client, oidc(), axiom_score=True).status_code == 400
    assert _submit(client, oidc(), axiom_score=101).status_code == 400


def test_legacy_unverified_rows_are_hidden_and_do_not_count(app_env):
    server, client, tmp = app_env
    conn = sqlite3.connect(tmp / "leaderboard.db")
    for _ in range(3):
        conn.execute("INSERT INTO submissions (server_name, repo_url, nist_score, axiom_score) "
                     "VALUES ('x', 'javascript:alert(1)', 100, 100)")
    conn.commit()
    conn.close()
    assert client.get("/leaderboard.json").get_json() == []
    assert "javascript:" not in client.get("/").get_data(as_text=True)
    badge = client.get("/badge", query_string={"repo_url": "javascript:alert(1)"}).get_json()
    assert badge["tier"] == "none"


# --- audits ------------------------------------------------------------------

def _audit_payload(server, repo=""):
    subs = server.axiom.load_methodology()["sub_domains"]
    entries = [{"id": sd["id"], "level": 4, "evidence": "Mesure technique", "justification": "charte IA"} for sd in subs]
    return {"company_name": "Acme", "linked_repo_url": repo, "entries": entries}


def test_audit_requires_auditor_token(app_env):
    server, client, _ = app_env
    assert client.post("/submit-audit", json=_audit_payload(server)).status_code == 401
    r = client.post("/submit-audit", json=_audit_payload(server), headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert client.get("/companies.json").get_json() == []


def test_audit_disabled_without_configuration(app_env, monkeypatch):
    server, client, _ = app_env
    monkeypatch.delenv("AUDITOR_TOKENS")
    r = client.post("/submit-audit", json=_audit_payload(server), headers={"Authorization": f"Bearer {AUDITOR_TOKEN}"})
    assert r.status_code == 503


def test_audit_report_link_is_unguessable_and_private(app_env):
    server, client, tmp = app_env
    r = client.post("/submit-audit", json=_audit_payload(server),
                    headers={"Authorization": f"Bearer {AUDITOR_TOKEN}"})
    assert r.status_code == 200, r.get_json()
    url = r.get_json()["report_url"]
    assert len(url.rsplit("/", 1)[1]) >= 30
    assert client.get("/audit-report/1").status_code == 404
    page = client.get(url)
    assert page.status_code == 200 and "Acme" in page.get_data(as_text=True)
    assert "noindex" in page.headers["X-Robots-Tag"]

    companies = client.get("/companies.json").get_json()
    assert companies[0]["company_name"] == "Acme"
    assert "evidences_json" not in companies[0] and "answers_json" not in companies[0]
    assert "report_token" not in companies[0] and "auditor" not in companies[0]
    row = sqlite3.connect(tmp / "leaderboard.db").execute("SELECT auditor FROM org_audits").fetchone()
    assert row[0] == "alice"


def test_audit_rejects_dangerous_repo_link(app_env):
    server, client, _ = app_env
    r = client.post("/submit-audit", json=_audit_payload(server, "javascript:alert(1)"),
                    headers={"Authorization": f"Bearer {AUDITOR_TOKEN}"})
    assert r.status_code == 400


def test_platinum_needs_verified_silver(app_env):
    server, client, tmp = app_env
    conn = sqlite3.connect(tmp / "leaderboard.db")
    for days in (20, 10, 1):  # 3 vérifications étalées, mais NON attestées
        conn.execute("INSERT INTO submissions (server_name, repo_url, nist_score, axiom_score, submitted_at) "
                     "VALUES ('x', 'https://github.com/acme/mcp', 95, 95, datetime('now', ?))", (f"-{days} days",))
    conn.commit()
    conn.close()
    r = client.post("/submit-audit", json=_audit_payload(server, "https://github.com/acme/mcp"),
                    headers={"Authorization": f"Bearer {AUDITOR_TOKEN}"})
    assert r.get_json()["tier"] == "Gold"

    conn = sqlite3.connect(tmp / "leaderboard.db")
    conn.execute("UPDATE submissions SET verification = 'github-oidc'")
    conn.commit()
    conn.close()
    r = client.post("/submit-audit", json=_audit_payload(server, "https://github.com/acme/mcp"),
                    headers={"Authorization": f"Bearer {AUDITOR_TOKEN}"})
    assert r.get_json()["tier"] == "Platinum"


def test_legacy_audits_hidden_and_get_new_links(tmp_path, monkeypatch):
    """Base créée par l'ancienne version : colonnes ajoutées, anciens audits masqués."""
    monkeypatch.chdir(tmp_path)
    conn = sqlite3.connect(tmp_path / "leaderboard.db")
    conn.execute("CREATE TABLE org_audits (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT NOT NULL, "
                 "linked_repo_url TEXT, answers_json TEXT NOT NULL, evidences_json TEXT, percentage REAL NOT NULL, "
                 "tier TEXT NOT NULL, audited_at TEXT DEFAULT (datetime('now')))")
    conn.execute("INSERT INTO org_audits (company_name, answers_json, evidences_json, percentage, tier) "
                 "VALUES ('SelfAwarded', '[]', '[\"secret\"]', 100, 'Platinum')")
    conn.commit()
    conn.close()
    monkeypatch.setenv("AUDITOR_TOKENS", "")
    monkeypatch.syspath_prepend(str(LEADERBOARD_DIR))
    for mod in ("server", "security", "badge_tier", "db", "framework_watch", "organizational_audit"):
        sys.modules.pop(mod, None)
    server = importlib.import_module("server")
    client = server.app.test_client()
    assert client.get("/companies.json").get_json() == []
    assert client.get("/audit-report/1").status_code == 404
    token = sqlite3.connect(tmp_path / "leaderboard.db").execute("SELECT report_token FROM org_audits").fetchone()[0]
    assert token and len(token) >= 30


# --- admin -------------------------------------------------------------------

@pytest.mark.parametrize("route", ["/badge/anchor", "/framework-check", "/test-email"])
def test_admin_routes_require_admin_token(app_env, route):
    _, client, _ = app_env
    assert client.post(route, json={"repo_url": "https://github.com/a/b"}).status_code == 401
    assert client.post(route, json={}, headers={"Authorization": f"Bearer {AUDITOR_TOKEN}"}).status_code == 401


def test_admin_routes_disabled_without_admin_token(app_env, monkeypatch):
    _, client, _ = app_env
    monkeypatch.delenv("ADMIN_TOKEN")
    assert client.post("/test-email", headers={"Authorization": "Bearer "}).status_code == 503


def test_security_headers(app_env):
    _, client, _ = app_env
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
