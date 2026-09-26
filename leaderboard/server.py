"""
Serveur combiné — fusionne l'API du classement (leaderboard) et le
formulaire d'audit organisationnel dans une seule application Flask.

Pourquoi la fusion était nécessaire : le formulaire d'audit doit vérifier
le palier technique (Silver) d'un repo pour déterminer l'éligibilité
Platinum — ça exige qu'il lise la MÊME base de données que l'API du
classement. Deux services séparés sur deux instances distinctes
n'auraient pas partagé le même fichier SQLite.

Routes :
- /                    -> classement public (HTML)
- /leaderboard.json    -> classement public (JSON)
- /submit              -> soumission automatique de score (POST, jeton OIDC GitHub Actions)
- /badge               -> calcul du palier technique EMMA/Silver
- /audit               -> formulaire d'audit organisationnel (HTML)
- /submit-audit        -> soumission d'un audit (POST, jeton auditeur)

Contrôles d'accès : voir security.py (fermé par défaut si la
configuration manque). Variables : OIDC_AUDIENCE, AUDITOR_TOKENS, ADMIN_TOKEN.

Prérequis : pip install -r requirements.txt
"""

import hashlib
import json
import os
import db as db_layer
from datetime import datetime, timedelta

from flask import Flask, g, request, jsonify, render_template_string

import security
from security import require_admin, require_auditor, require_auditor_page, require_github_oidc

import axiom
import axiom_pages
import badge_tier
import organizational_audit
from organizational_audit import AUDIT_QUESTIONNAIRE  # questionnaire v1.0, pour relire les anciens audits
from blockchain_anchor import compute_report_hash, create_opentimestamps_proof
import framework_watch

app = Flask(__name__)
DB_PATH = "leaderboard.db"

RATE_LIMIT_MINUTES = 10
GOLD_MIN_PERCENTAGE = 75.0
# Un score élevé sur une petite partie de la grille ne suffit pas pour un palier.
GOLD_MIN_COVERAGE = 80.0
TIER_ORDER = {"none": 0, "EMMA": 1, "Silver": 2}
VERIFIED = "github-oidc"
MAX_SERVER_NAME = 100
MAX_COMPANY_NAME = 200
MAX_EVIDENCE_CHARS = 2000

def get_db():
    return db_layer.get_db(DB_PATH)


def init_db():
    pk = db_layer.autoincrement_pk()
    now = db_layer.now_expr()
    conn = get_db()
    with conn:
        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS submissions (
            id {pk},
            server_name TEXT NOT NULL,
            repo_url TEXT NOT NULL,
            nist_score REAL NOT NULL,
            axiom_score REAL NOT NULL,
            proof_hash TEXT,
            submitted_at TEXT DEFAULT {now}
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repo_url ON submissions(repo_url)")
        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS org_audits (
            id {pk},
            company_name TEXT NOT NULL,
            linked_repo_url TEXT,
            answers_json TEXT NOT NULL,
            evidences_json TEXT,
            percentage REAL NOT NULL,
            tier TEXT NOT NULL,
            audited_at TEXT DEFAULT {now}
        )
        """)
        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS anchored_badges (
            id {pk},
            repo_url TEXT NOT NULL,
            tier TEXT NOT NULL,
            certification_hash TEXT NOT NULL UNIQUE,
            proof_path TEXT,
            anchor_status TEXT DEFAULT 'pending',
            anchored_at TEXT DEFAULT {now}
        )
        """)
    conn.close()
    _migrate_security_columns()


def _existing_columns(conn, table: str) -> set:
    if db_layer.USE_POSTGRES:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?", (table,)
        ).fetchall()
        return {r["column_name"] for r in rows}
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_security_columns():
    """Ajoute les colonnes de traçabilité aux bases existantes (idempotent).

    Les lignes antérieures gardent verification='none' / auditor NULL :
    elles restent en base mais ne comptent plus pour les paliers et ne
    sont plus affichées publiquement (rien ne prouve qui les a soumises)."""
    wanted = {
        "submissions": [("verification", "TEXT DEFAULT 'none'"), ("workflow_ref", "TEXT"),
                        ("run_id", "TEXT"), ("git_ref", "TEXT")],
        "org_audits": [("auditor", "TEXT"), ("report_token", "TEXT"),
                       ("methodology_version", "TEXT"), ("coverage", "REAL")],
    }
    conn = get_db()
    with conn:
        for table, columns in wanted.items():
            existing = _existing_columns(conn, table)
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        # Les anciens rapports étaient accessibles par simple numéro : on leur
        # donne un identifiant non devinable (l'ancien lien cesse de marcher).
        for row in conn.execute("SELECT id FROM org_audits WHERE report_token IS NULL").fetchall():
            conn.execute("UPDATE org_audits SET report_token = ? WHERE id = ?",
                         (security.new_report_token(), row["id"]))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_report_token ON org_audits(report_token)")
    conn.close()


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


init_db()  # Appelé au chargement du module — nécessaire pour gunicorn,
           # qui n'exécute jamais le bloc `if __name__ == "__main__"`.
framework_watch.init_framework_tables(DB_PATH)


# ============================================================
# LEADERBOARD (repris tel quel de api.py)
# ============================================================

def verify_hash_consistency(payload: dict) -> bool:
    if not payload.get("proof_hash"):
        return True
    report_summary = {
        "server_name": payload.get("server_name"),
        "checked_at": payload.get("checked_at"),
        "nist_score": payload.get("nist_score"),
        "axiom_score": payload.get("axiom_score"),
    }
    canonical = json.dumps(report_summary, sort_keys=True, separators=(",", ":"))
    computed_hash = hashlib.sha256(canonical.encode()).hexdigest()
    return computed_hash == payload["proof_hash"]


def check_rate_limit(repo_url: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT submitted_at FROM submissions WHERE repo_url = ? ORDER BY submitted_at DESC LIMIT 1",
        (repo_url,)
    ).fetchone()
    conn.close()
    if not row:
        return True
    last_submitted = badge_tier._parse_timestamp(row["submitted_at"])
    return datetime.now() - last_submitted > timedelta(minutes=RATE_LIMIT_MINUTES)


def _is_score(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100


@app.route("/submit", methods=["POST"])
@require_github_oidc
def submit():
    payload = request.get_json(silent=True) or {}
    required = ["server_name", "nist_score", "axiom_score"]
    missing = [f for f in required if f not in payload]
    if missing:
        return jsonify({"error": f"Champs manquants : {missing}"}), 400
    if not _is_score(payload["nist_score"]) or not _is_score(payload["axiom_score"]):
        return jsonify({"error": "Les scores doivent être des nombres entre 0 et 100"}), 400
    server_name = str(payload["server_name"]).strip()[:MAX_SERVER_NAME]
    if not server_name:
        return jsonify({"error": "server_name vide"}), 400

    # Le dépôt est celui que GitHub atteste dans le jeton, pas celui déclaré.
    repo_url = g.repo_url
    declared = payload.get("repo_url")
    if declared and security.normalize_repo_url(str(declared)) != repo_url:
        return jsonify({"error": f"repo_url déclaré différent du dépôt attesté par GitHub ({repo_url})"}), 403

    if not verify_hash_consistency(payload):
        return jsonify({"error": "Le hash fourni ne correspond pas aux données envoyées"}), 400
    if not check_rate_limit(repo_url):
        return jsonify({"error": f"Trop de soumissions récentes. Réessaie dans {RATE_LIMIT_MINUTES} minutes."}), 429
    claims = g.oidc_claims

    # Palier AVANT cette soumission, pour détecter une progression après coup
    previous_history = badge_tier.get_submission_history(DB_PATH, repo_url)
    previous_tier = badge_tier.compute_badge_tier(previous_history).tier

    conn = get_db()
    with conn:
        conn.execute(f"""
            INSERT INTO submissions (server_name, repo_url, nist_score, axiom_score, proof_hash,
                                     verification, workflow_ref, run_id, git_ref, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, {db_layer.now_expr()})
        """, (server_name, repo_url, payload["nist_score"], payload["axiom_score"], payload.get("proof_hash"),
              VERIFIED, claims.get("workflow_ref"), str(claims.get("run_id") or ""), claims.get("ref")))
    conn.close()

    # Palier APRÈS cette soumission
    updated_history = badge_tier.get_submission_history(DB_PATH, repo_url)
    new_tier_result = badge_tier.compute_badge_tier(updated_history)
    new_tier = new_tier_result.tier

    response = {"ok": True, "repo_url": repo_url, "verification": VERIFIED}

    # Ancrage automatique UNIQUEMENT en cas de vraie progression (ex: none->EMMA,
    # EMMA->Silver) — pas à chaque soumission qui maintient le même palier,
    # pour éviter de spammer la blockchain de certifications redondantes.
    if TIER_ORDER.get(new_tier, 0) > TIER_ORDER.get(previous_tier, 0):
        response["tier_progression"] = f"{previous_tier} -> {new_tier}"
        anchor_result = _attempt_badge_anchor(repo_url, new_tier_result)
        response["auto_anchor"] = anchor_result

    return jsonify(response), 200


def _attempt_badge_anchor(repo_url: str, tier_result) -> dict:
    """Tente l'ancrage automatique d'un badge après une progression de
    palier. Best-effort : un échec ici ne doit JAMAIS faire échouer la
    soumission de score elle-même (même logique que l'ancrage principal
    dans run_action.py)."""
    certification_hash = compute_report_hash({
        "repo_url": repo_url, "tier": tier_result.tier,
        "latest_axiom_score": tier_result.latest_axiom_score,
    })

    conn = get_db()
    existing = conn.execute(
        "SELECT anchor_status FROM anchored_badges WHERE certification_hash = ?",
        (certification_hash,)
    ).fetchone()

    if existing:
        conn.close()
        return {"status": existing["anchor_status"], "certification_hash": certification_hash, "note": "déjà tenté"}

    with conn:
        conn.execute(
            "INSERT INTO anchored_badges (repo_url, tier, certification_hash, anchor_status) VALUES (?,?,?,?)",
            (repo_url, tier_result.tier, certification_hash, "pending")
        )
    conn.close()

    try:
        report_path = f"/tmp/badge_{certification_hash[:16]}.json"
        with open(report_path, "w") as f:
            json.dump({"repo_url": repo_url, "tier": tier_result.tier, "certification_hash": certification_hash}, f)

        proof_path = create_opentimestamps_proof(report_path)

        conn = get_db()
        with conn:
            conn.execute(
                "UPDATE anchored_badges SET anchor_status = 'anchored', proof_path = ? WHERE certification_hash = ?",
                (proof_path, certification_hash)
            )
        conn.close()
        return {"status": "anchored", "certification_hash": certification_hash, "proof_path": proof_path}

    except Exception as e:
        conn = get_db()
        with conn:
            conn.execute(
                "UPDATE anchored_badges SET anchor_status = 'failed' WHERE certification_hash = ?",
                (certification_hash,)
            )
        conn.close()
        return {"status": "failed", "certification_hash": certification_hash, "error": str(e)}


@app.route("/leaderboard.json")
def leaderboard_json():
    conn = get_db()
    rows = conn.execute("""
        SELECT s.server_name, s.repo_url, s.nist_score, s.axiom_score, s.proof_hash, s.submitted_at
        FROM submissions s
        INNER JOIN (SELECT repo_url, MAX(submitted_at) AS max_date FROM submissions
                    WHERE verification = 'github-oidc' GROUP BY repo_url) latest
        ON s.repo_url = latest.repo_url AND s.submitted_at = latest.max_date
        WHERE s.verification = 'github-oidc'
        ORDER BY s.nist_score DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


LEADERBOARD_PAGE = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>MCP Trust Score — Classement</title>
  <style>
    body { font-family: -apple-system, Arial, sans-serif; max-width: 800px; margin: 40px auto; color: #1e293b; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }
    th { background: #f8fafc; }
    .score-high { color: #16a34a; font-weight: bold; }
    .score-mid { color: #ca8a04; font-weight: bold; }
    .score-low { color: #dc2626; font-weight: bold; }
    .badge-pill { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
    .badge-silver { background: #e2e8f0; color: #475569; }
    .badge-emma { background: #fef3c7; color: #92400e; }
    .badge-none { color: #94a3b8; font-size: 12px; }
    .nav { margin-bottom: 20px; }
    .nav a { color: #2563eb; margin-right: 16px; }
  </style>
</head>
<body>
  <div class="nav"><a href="/">🏆 Classement</a><a href="/audit">🔍 Audit organisationnel</a><a href="/companies">🏅 Entreprises évaluées</a><a href="/methodologie">📐 Méthodologie</a></div>
  <h1>🏆 MCP Trust Score — Classement</h1>
  <table>
    <tr><th>Rang</th><th>Serveur</th><th>Score NIST</th><th>Score AXIOM</th><th>Palier</th><th>Soumis le</th><th>Preuve</th></tr>
    {% for e in entries %}
    <tr>
      <td>{{ loop.index }}</td>
      <td><a href="{{ e.repo_url }}">{{ e.server_name }}</a></td>
      <td class="{{ 'score-high' if e.nist_score >= 90 else ('score-mid' if e.nist_score >= 70 else 'score-low') }}">{{ e.nist_score }}%</td>
      <td>{{ e.axiom_score }}%</td>
      <td>
        {% if e.badge_tier == 'Silver' %}<span class="badge-pill badge-silver">🥈 Silver</span>
        {% elif e.badge_tier == 'EMMA' %}<span class="badge-pill badge-emma">EMMA</span>
        {% else %}<span class="badge-none">—</span>
        {% endif %}
        {% if e.badge_tier != 'none' %}
          {% if e.anchor_status == 'anchored' %}<br><span style="font-size:11px;color:#16a34a;">⛓️ ancré</span>
          {% elif e.anchor_status == 'pending' or e.anchor_status == 'failed' %}<br><span style="font-size:11px;color:#94a3b8;">ancrage {{ e.anchor_status }}</span>
          {% else %}<br><span style="font-size:11px;color:#94a3b8;">non ancré</span>
          {% endif %}
        {% endif %}
      </td>
      <td>{{ e.submitted_at }}</td>
      <td>{{ e.proof_hash[:12] + '...' if e.proof_hash else '—' }}</td>
    </tr>
    {% endfor %}
  </table>

</body>
</html>
"""


@app.route("/")
def leaderboard_page():
    conn = get_db()
    rows = conn.execute("""
        SELECT s.server_name, s.repo_url, s.nist_score, s.axiom_score, s.proof_hash, s.submitted_at
        FROM submissions s
        INNER JOIN (SELECT repo_url, MAX(submitted_at) AS max_date FROM submissions
                    WHERE verification = 'github-oidc' GROUP BY repo_url) latest
        ON s.repo_url = latest.repo_url AND s.submitted_at = latest.max_date
        WHERE s.verification = 'github-oidc'
        ORDER BY s.nist_score DESC
    """).fetchall()
    conn.close()

    entries = []
    for r in rows:
        entry = dict(r)
        history = badge_tier.get_submission_history(DB_PATH, entry["repo_url"])
        tier_result = badge_tier.compute_badge_tier(history)
        entry["badge_tier"] = tier_result.tier

        entry["anchor_status"] = None
        if tier_result.tier != "none":
            cert_hash = compute_report_hash({
                "repo_url": entry["repo_url"], "tier": tier_result.tier,
                "latest_axiom_score": tier_result.latest_axiom_score,
            })
            conn2 = get_db()
            existing = conn2.execute(
                "SELECT anchor_status FROM anchored_badges WHERE certification_hash = ?", (cert_hash,)
            ).fetchone()
            conn2.close()
            entry["anchor_status"] = existing["anchor_status"] if existing else "not_requested"

        entries.append(entry)

    return render_template_string(LEADERBOARD_PAGE, entries=entries)


@app.route("/badge")
def badge():
    repo_url = request.args.get("repo_url")
    if not repo_url:
        return jsonify({"error": "Paramètre 'repo_url' requis"}), 400

    history = badge_tier.get_submission_history(DB_PATH, repo_url)
    result = badge_tier.compute_badge_tier(history)

    response = {
        "repo_url": repo_url, "tier": result.tier,
        "latest_axiom_score": result.latest_axiom_score,
        "submission_count_in_window": result.submission_count_in_window,
        "reason": result.reason,
    }
    if result.tier != "none":
        certification_hash = compute_report_hash({
            "repo_url": repo_url, "tier": result.tier,
            "latest_axiom_score": result.latest_axiom_score,
        })
        response["certification_hash"] = certification_hash

        # Vérifie si cette certification exacte a déjà été ancrée
        conn = get_db()
        existing = conn.execute(
            "SELECT anchor_status, proof_path FROM anchored_badges WHERE certification_hash = ?",
            (certification_hash,)
        ).fetchone()
        conn.close()

        if existing:
            response["anchor_status"] = existing["anchor_status"]
            response["proof_path"] = existing["proof_path"]
        else:
            response["anchor_status"] = "not_requested"
            response["anchor_hint"] = "POST /badge/anchor avec ce repo_url pour ancrer ce badge sur la blockchain."

    return jsonify(response)


@app.route("/badge/anchor", methods=["POST"])
@require_admin
def anchor_badge():
    """Déclenche l'ancrage blockchain réel d'un badge — action explicite,
    séparée de la simple consultation (/badge), pour ne pas refaire un
    appel réseau OpenTimestamps à chaque affichage de page."""
    payload = request.get_json() or {}
    repo_url = payload.get("repo_url") or request.args.get("repo_url")
    if not repo_url:
        return jsonify({"error": "Paramètre 'repo_url' requis"}), 400

    history = badge_tier.get_submission_history(DB_PATH, repo_url)
    result = badge_tier.compute_badge_tier(history)

    if result.tier == "none":
        return jsonify({"error": "Ce repo n'a atteint aucun palier — rien à ancrer."}), 400

    certification_hash = compute_report_hash({
        "repo_url": repo_url, "tier": result.tier,
        "latest_axiom_score": result.latest_axiom_score,
    })

    conn = get_db()
    existing = conn.execute(
        "SELECT anchor_status, proof_path FROM anchored_badges WHERE certification_hash = ?",
        (certification_hash,)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({
            "message": "Déjà ancré ou en cours — pas de nouvel ancrage déclenché.",
            "certification_hash": certification_hash,
            "anchor_status": existing["anchor_status"],
        })

    # Insère un enregistrement "pending" avant même de tenter l'ancrage,
    # pour éviter une double soumission si deux requêtes arrivent en même temps
    with conn:
        conn.execute(
            "INSERT INTO anchored_badges (repo_url, tier, certification_hash, anchor_status) VALUES (?,?,?,?)",
            (repo_url, result.tier, certification_hash, "pending")
        )
    conn.close()

    try:
        report_path = f"/tmp/badge_{certification_hash[:16]}.json"
        with open(report_path, "w") as f:
            json.dump({"repo_url": repo_url, "tier": result.tier, "certification_hash": certification_hash}, f)

        proof_path = create_opentimestamps_proof(report_path)

        conn = get_db()
        with conn:
            conn.execute(
                "UPDATE anchored_badges SET anchor_status = 'anchored', proof_path = ? WHERE certification_hash = ?",
                (proof_path, certification_hash)
            )
        conn.close()

        return jsonify({"certification_hash": certification_hash, "anchor_status": "anchored", "proof_path": proof_path})

    except Exception as e:
        conn = get_db()
        with conn:
            conn.execute(
                "UPDATE anchored_badges SET anchor_status = 'failed' WHERE certification_hash = ?",
                (certification_hash,)
            )
        conn.close()
        return jsonify({"error": f"Échec de l'ancrage : {e}", "certification_hash": certification_hash, "anchor_status": "failed"}), 500


# ============================================================
# AUDIT ORGANISATIONNEL — méthode AXIOM v1.1 (voir axiom.py et methodology/)
# ============================================================

def compute_org_tier(percentage: float, linked_repo_url: str, coverage: float | None = None) -> tuple:
    if coverage is not None and coverage < GOLD_MIN_COVERAGE:
        return "none", (f"Couverture de la grille ({coverage}%) sous le minimum requis pour un palier "
                        f"({GOLD_MIN_COVERAGE}%).")
    if percentage < GOLD_MIN_PERCENTAGE:
        return "none", f"Score organisationnel ({percentage}%) sous le seuil Gold ({GOLD_MIN_PERCENTAGE}%)."

    if not linked_repo_url:
        return "Gold", f"Score organisationnel {percentage}% ≥ {GOLD_MIN_PERCENTAGE}% — Gold atteint. Aucun repo lié fourni pour Platinum."

    try:
        history = badge_tier.get_submission_history(DB_PATH, linked_repo_url)
        tech_result = badge_tier.compute_badge_tier(history)
    except Exception:
        tech_result = None

    if tech_result and tech_result.tier == "Silver":
        return "Platinum", f"Score organisationnel {percentage}% ET palier technique Silver confirmé — Platinum atteint."

    return "Gold", f"Score organisationnel {percentage}% ≥ {GOLD_MIN_PERCENTAGE}% — Gold atteint, mais palier technique Silver requis pour Platinum non confirmé."


# Ancien bilan (questionnaire v1.0) : conservé pour relire les audits enregistrés avant la v1.1.
AUDIT_REPORT_PAGE = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Bilan d'audit — {{ company_name }}</title>
  <style>
    body { font-family: 'Segoe UI', -apple-system, Arial, sans-serif; max-width: 820px; margin: 0 auto; padding: 0 24px 60px; color: #1e293b; background: #f8fafc; }
    .nav { padding: 20px 0; }
    .nav a { color: #475569; margin-right: 20px; text-decoration: none; font-size: 14px; font-weight: 500; }
    .report-header {
      background: linear-gradient(135deg, #0f172a, #1e293b); color: white;
      padding: 36px; border-radius: 12px; margin-bottom: 28px;
    }
    .report-header .company { font-size: 24px; font-weight: 700; margin: 0 0 4px; }
    .report-header .date { color: #94a3b8; font-size: 13px; }
    .tier-badge {
      display: inline-block; padding: 8px 20px; border-radius: 24px; font-weight: 700;
      font-size: 15px; margin-top: 14px;
    }
    .tier-platinum { background: #ede9fe; color: #6d28d9; }
    .tier-gold { background: #fef3c7; color: #92400e; }
    .tier-none { background: #fee2e2; color: #991b1b; }
    .score-hero {
      display: flex; align-items: center; gap: 32px; background: white;
      border-radius: 12px; padding: 28px 32px; margin-bottom: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .score-number { font-size: 52px; font-weight: 800; color: #0f172a; }
    .score-label { color: #64748b; font-size: 14px; }
    .radar-container { background: white; border-radius: 12px; padding: 28px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); text-align: center; }
    .radar-container h3 { margin-top: 0; }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
    .insight-card { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
    .insight-card.strength { border-left: 4px solid #16a34a; }
    .insight-card.weakness { border-left: 4px solid #dc2626; }
    .insight-card h3 { margin-top: 0; font-size: 15px; }
    .insight-card ul { margin: 0; padding-left: 20px; font-size: 14px; }
    .details-section { background: white; border-radius: 12px; padding: 28px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
    .detail-row { padding: 14px 0; border-bottom: 1px solid #f1f5f9; }
    .detail-row:last-child { border-bottom: none; }
    .detail-q { font-size: 14px; font-weight: 500; margin: 0 0 4px; }
    .detail-score { display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 6px; margin-right: 8px; }
    .detail-evidence { color: #64748b; font-size: 13px; margin-top: 4px; font-style: italic; }
    .disclaimer { margin-top: 24px; padding: 16px 20px; background: #fefce8; border: 1px solid #fde047; border-radius: 10px; font-size: 13px; color: #713f12; }
  </style>
</head>
<body>
  <div class="nav"><a href="/">🏆 Classement</a><a href="/audit">🔍 Audit organisationnel</a><a href="/companies">🏅 Entreprises évaluées</a><a href="/methodologie">📐 Méthodologie</a></div>

  <div class="report-header">
    <p class="company">{{ company_name }}</p>
    <p class="date">Audité le {{ audited_at }}</p>
    <span class="tier-badge {{ 'tier-platinum' if tier == 'Platinum' else ('tier-gold' if tier == 'Gold' else 'tier-none') }}">
      {{ '💎 Platinum' if tier == 'Platinum' else ('🥇 Gold' if tier == 'Gold' else '— Aucun palier') }}
    </span>
  </div>

  <div class="score-hero">
    <div class="score-number">{{ overall_percentage }}%</div>
    <div class="score-label">Score de maturité organisationnelle global<br>{{ tier_reason }}</div>
  </div>

  <div class="radar-container">
    <h3>Répartition par domaine</h3>
    {{ radar_svg | safe }}
  </div>

  <div class="two-col">
    <div class="insight-card strength">
      <h3>✅ Points forts</h3>
      <ul>{% for s in strengths %}<li>{{ s }}</li>{% endfor %}</ul>
    </div>
    <div class="insight-card weakness">
      <h3>⚠️ Points à renforcer</h3>
      <ul>{% for w in weaknesses %}<li>{{ w }}</li>{% endfor %}</ul>
    </div>
  </div>

  <div class="details-section">
    <h3>Détail des réponses</h3>
    {% for d in details %}
    <div class="detail-row">
      <p class="detail-q">
        <span class="detail-score" style="background:{{ '#dcfce7;color:#166534' if d.score >= 3 else ('#fef3c7;color:#92400e' if d.score == 2 else '#fee2e2;color:#991b1b') }}">{{ d.score }}/4</span>
        [{{ d.sub_domain }}] {{ d.question }}
      </p>
      {% if d.evidence %}<p class="detail-evidence">📎 {{ d.evidence }}</p>{% endif %}
    </div>
    {% endfor %}
  </div>

  <div class="disclaimer">
    ⚠️ Ce bilan est une auto-évaluation déclarative (formulaire rempli par un auditeur humain),
    pas une vérification indépendante automatisée. Les preuves citées n'ont pas été vérifiées
    par un tiers.
  </div>
</body>
</html>
"""


def _public_context() -> dict:
    public = axiom.load_public()
    return {
        "version": axiom.version_label(),
        "subs": public["sub_domains"],
        "n": len(public["sub_domains"]),
        "levels": axiom.allowed_levels(),
        "labels": public["scale"]["labels"],
        "evidence_types": public["evidence_types"],
        "measured_cap": public["measured_cap"],
        "gold_min": GOLD_MIN_PERCENTAGE,
        "coverage_min": GOLD_MIN_COVERAGE,
    }


def _grid_unavailable():
    return ("Audit indisponible : la grille AXIOM confidentielle n'est pas configurée sur ce serveur.", 503,
            {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/audit")
@require_auditor_page
def audit_form():
    # Page réservée aux évaluateurs : elle affiche la grille confidentielle.
    try:
        method = axiom.load_methodology()
    except axiom.MethodologyUnavailable:
        return _grid_unavailable()
    ctx = _public_context() | {"subs": method["sub_domains"], "auditor": g.auditor}
    page = render_template_string(axiom_pages.AUDIT_FORM_V11, **ctx)
    return page, 200, {"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow"}


@app.route("/methodologie")
def methodology_page():
    # Partie publique uniquement : aucune donnée de la grille confidentielle.
    return render_template_string(axiom_pages.METHODOLOGY_PAGE, **_public_context())


@app.route("/submit-audit", methods=["POST"])
@require_auditor
def submit_audit():
    payload = request.get_json(silent=True) or {}
    company_name = str(payload.get("company_name") or "").strip()[:MAX_COMPANY_NAME]
    raw_repo = str(payload.get("linked_repo_url") or "").strip()
    linked_repo_url = security.normalize_repo_url(raw_repo)

    if not company_name:
        return jsonify({"error": "Nom d'entreprise requis"}), 400
    if raw_repo and not linked_repo_url:
        return jsonify({"error": "Repo lié invalide : attendu https://github.com/<owner>/<repo>"}), 400
    try:
        entries = axiom.parse_entries(payload.get("entries", []))
    except axiom.MethodologyUnavailable as e:
        return jsonify({"error": str(e)}), 503
    except axiom.ValidationError as e:
        return jsonify({"error": str(e)}), 400

    result = axiom.evaluate(entries)
    if result["score"] is None:
        return jsonify({"error": "Aucun sous-domaine évalué"}), 400
    tier, reason = compute_org_tier(result["score"], linked_repo_url, result["coverage"])

    report_token = security.new_report_token()
    stored = {"methodology": result["methodology"], "entries": axiom.entries_to_json(entries)}
    conn = get_db()
    with conn:
        conn.execute(f"""
            INSERT INTO org_audits (company_name, linked_repo_url, answers_json, evidences_json, percentage, tier,
                                    auditor, report_token, methodology_version, coverage, audited_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {db_layer.now_expr()})
        """, (company_name, linked_repo_url, json.dumps(stored, ensure_ascii=False), None, result["score"], tier,
              g.auditor, report_token, axiom.load_public()["version"], result["coverage"]))
    conn.close()

    return jsonify({"tier": tier, "percentage": result["score"], "coverage": result["coverage"],
                    "reason": reason, "report_url": f"/audit-report/{report_token}"})


@app.route("/audit-report/<report_token>")
def audit_report(report_token):
    # Lien non devinable, à transmettre uniquement à l'entreprise auditée.
    if len(report_token) < 20:
        return "Audit introuvable", 404
    conn = get_db()
    row = conn.execute("SELECT * FROM org_audits WHERE report_token = ?", (report_token,)).fetchone()
    conn.close()

    if not row:
        return "Audit introuvable", 404

    row = dict(row)
    headers = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
               "Cache-Control": "private, no-store"}
    if row.get("methodology_version"):
        if not axiom.is_available():
            return _grid_unavailable()
        stored = json.loads(row["answers_json"])
        entries = axiom.parse_entries(stored["entries"])
        result = axiom.evaluate(entries)
        tier, tier_reason = compute_org_tier(result["score"], row["linked_repo_url"], result["coverage"])
        domains_order = list(result["domains"].keys())
        radar_svg = organizational_audit.generate_radar_svg(
            {d: (v["score"] or 0) for d, v in result["domains"].items()}, size=560, order=domains_order)
        page = render_template_string(
            axiom_pages.AUDIT_REPORT_V11, company_name=row["company_name"], audited_at=row["audited_at"],
            auditor=row.get("auditor") or "évaluateur non identifié", tier=row["tier"], tier_reason=tier_reason,
            r=result, radar_svg=radar_svg)
        return page, 200, headers

    # Ancien format (questionnaire v1.0, 11 questions notées 0-4)
    scores = json.loads(row["answers_json"])
    evidences = json.loads(row["evidences_json"]) if row.get("evidences_json") else [""] * len(scores)

    report = organizational_audit.compute_full_report(AUDIT_QUESTIONNAIRE, scores, evidences)
    radar_svg = organizational_audit.generate_radar_svg(report["domain_percentages"])

    _, tier_reason = compute_org_tier(row["percentage"], row["linked_repo_url"])

    page = render_template_string(
        AUDIT_REPORT_PAGE,
        company_name=row["company_name"],
        audited_at=row["audited_at"],
        tier=row["tier"],
        tier_reason=tier_reason,
        overall_percentage=report["overall_percentage"],
        radar_svg=radar_svg,
        strengths=report["strengths"],
        weaknesses=report["weaknesses"],
        details=report["details"],
    )
    return page, 200, headers


COMPANIES_PAGE = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>MCP Trust Score — Entreprises évaluées</title>
  <style>
    body { font-family: -apple-system, Arial, sans-serif; max-width: 800px; margin: 40px auto; color: #1e293b; padding: 0 20px; }
    .nav { margin-bottom: 20px; }
    .nav a { color: #2563eb; margin-right: 16px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px; text-align: left; border-bottom: 1px solid #e2e8f0; }
    th { background: #f8fafc; }
    .badge-pill { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
    .badge-platinum { background: #ede9fe; color: #6d28d9; }
    .badge-gold { background: #fef3c7; color: #92400e; }
    .disclaimer { margin-top: 24px; padding: 16px; background: #fefce8; border: 1px solid #fde047; border-radius: 8px; font-size: 13px; color: #713f12; }
  </style>
</head>
<body>
  <div class="nav"><a href="/">🏆 Classement</a><a href="/audit">🔍 Audit organisationnel</a><a href="/companies">🏅 Entreprises évaluées</a><a href="/methodologie">📐 Méthodologie</a></div>
  <h1>🏅 Entreprises évaluées — paliers Gold / Platinum</h1>
  <p>Évaluations AXIOM réalisées par un évaluateur identifié, selon la <a href="/methodologie">méthodologie publique</a>.</p>

  <table>
    <tr><th>Entreprise</th><th>Palier</th><th>Score</th><th>Couverture</th><th>Repo lié</th><th>Évalué le</th></tr>
    {% for c in companies %}
    <tr>
      <td>{{ c.company_name }}</td>
      <td>
        {% if c.tier == 'Platinum' %}<span class="badge-pill badge-platinum">💎 Platinum</span>
        {% else %}<span class="badge-pill badge-gold">🥇 Gold</span>
        {% endif %}
      </td>
      <td>{{ c.percentage }}%</td>
      <td>{{ (c.coverage|string + '%') if c.coverage is not none else '—' }}</td>
      <td>{% if c.linked_repo_url %}<a href="{{ c.linked_repo_url }}">{{ c.linked_repo_url }}</a>{% else %}—{% endif %}</td>
      <td>{{ c.audited_at }}</td>
    </tr>
    {% endfor %}
  </table>

  <div class="disclaimer">
    ⚠️ Ces paliers résultent d'une évaluation AXIOM : chaque niveau est plafonné par le type de
    preuve obtenue, et le score se lit avec sa couverture. Ce n'est pas une certification ; les
    correspondances avec d'autres référentiels sont indicatives.
  </div>
</body>
</html>
"""


@app.route("/companies")
def companies_page():
    conn = get_db()
    rows = conn.execute("""
        SELECT o.company_name, o.tier, o.percentage, o.coverage, o.linked_repo_url, o.audited_at FROM org_audits o
        INNER JOIN (
            SELECT company_name, MAX(audited_at) AS max_date
            FROM org_audits WHERE auditor IS NOT NULL
            GROUP BY company_name
        ) latest ON o.company_name = latest.company_name AND o.audited_at = latest.max_date
        WHERE o.tier IN ('Gold', 'Platinum') AND o.auditor IS NOT NULL
        ORDER BY o.tier DESC, o.percentage DESC
    """).fetchall()
    conn.close()
    return render_template_string(COMPANIES_PAGE, companies=[dict(r) for r in rows])


@app.route("/companies.json")
def companies_json():
    conn = get_db()
    rows = conn.execute("""
        SELECT o.company_name, o.tier, o.percentage, o.coverage, o.linked_repo_url, o.audited_at FROM org_audits o
        INNER JOIN (
            SELECT company_name, MAX(audited_at) AS max_date
            FROM org_audits WHERE auditor IS NOT NULL
            GROUP BY company_name
        ) latest ON o.company_name = latest.company_name AND o.audited_at = latest.max_date
        WHERE o.tier IN ('Gold', 'Platinum') AND o.auditor IS NOT NULL
        ORDER BY o.tier DESC, o.percentage DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/framework-status")
def framework_status():
    conn = get_db()
    rows = conn.execute("SELECT * FROM framework_versions").fetchall()
    events = conn.execute(
        "SELECT * FROM framework_update_events ORDER BY detected_at DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return jsonify({
        "tracked_frameworks": [dict(r) for r in rows],
        "recent_updates": [dict(e) for e in events],
    })


@app.route("/framework-check", methods=["POST"])
@require_admin
def trigger_framework_check():
    """Déclenche une vérification à la demande — utile pour tester,
    en attendant une vraie tâche planifiée (cron) en production."""
    github_token = os.environ.get("GITHUB_TOKEN")
    events = framework_watch.run_framework_check(DB_PATH, github_token=github_token)

    email_result = None
    if events:
        email_result = framework_watch.send_framework_alert_emails(DB_PATH, events)

    return jsonify({
        "checked": True,
        "changes_detected": len(events),
        "events": events,
        "email_notification": email_result,
    })


@app.route("/subscribe", methods=["POST"])
def subscribe():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"error": "Email valide requis"}), 400

    conn = get_db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO framework_subscribers (email) VALUES (?)", (email,)
            )
    except db_layer.IntegrityError:
        conn.close()
        return jsonify({"message": "Déjà abonné"}), 200
    conn.close()
    return jsonify({"ok": True, "message": "Abonné aux alertes de mise à jour des référentiels."})


@app.route("/test-email", methods=["POST"])
@require_admin
def test_email():
    """Envoie un email de test à tous les abonnés actuels, avec des
    données factices — sert uniquement à vérifier que la configuration
    SMTP (Brevo) fonctionne réellement, sans toucher au système de
    détection de changement de référentiel."""
    fake_events = [{
        "framework": "test_smtp",
        "summary": "Ceci est un email de test — la configuration SMTP fonctionne.",
        "url": "https://mcp-trust-score.onrender.com",
    }]
    result = framework_watch.send_framework_alert_emails(DB_PATH, fake_events)
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
