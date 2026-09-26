"""
Calcul des paliers de badge technique (EMMA, Silver) pour un serveur MCP,
basé sur son score AXIOM technique et sa récurrence de vérification.

⚠️ Portée honnête : ce module calcule UNIQUEMENT les paliers techniques
(EMMA, Silver), applicables à l'agent/serveur MCP lui-même — le score
automatique et gratuit qu'on calcule déjà (Domaines 4 et 5 d'AXIOM).

Les paliers Gold et Platinum, eux, porteraient sur l'ENTREPRISE qui
publie l'agent, pas sur l'agent — ils nécessitent un audit humain des
Domaines 1, 2, 3, 6, 7, 8 (organisationnels), qui ne peut pas être
automatisé. Ce module ne les calcule PAS — voir la discussion produit
pour la conception de ce processus séparé.

Critères :
- EMMA (Edge Methodology Management of AI) : score AXIOM technique ≥ 70%
  sur la dernière vérification (≈ 6 contrôles sur 8 passés).
- Silver : score AXIOM ≥ 80% (plus exigeant qu'EMMA) sur au moins 3
  vérifications qualifiantes, dont la première et la dernière sont
  espacées d'au moins 14 jours sur une fenêtre glissante de 30 jours —
  preuve d'une conformité tenue dans la durée, pas un sprint de
  vérifications rapprochées pour gonfler artificiellement le palier.
"""

import db as db_layer
from dataclasses import dataclass
from datetime import datetime, timedelta

EMMA_MIN_AXIOM_SCORE = 70.0
SILVER_MIN_AXIOM_SCORE = 80.0
SILVER_MIN_SUBMISSIONS = 3
SILVER_MIN_SPAN_DAYS = 14
SILVER_WINDOW_DAYS = 30


def _parse_timestamp(raw: str) -> datetime:
    """Parse un timestamp venant soit de SQLite (naïf, sans fuseau) soit
    de PostgreSQL (avec fuseau, ex: '...+00') — normalise en retirant le
    fuseau, pour permettre des comparaisons cohérentes entre les deux
    backends sans erreur 'naive vs aware'.

    ⚠️ Bug réel trouvé et corrigé lors des tests de migration PostgreSQL :
    comparer un datetime avec fuseau à un datetime sans fuseau lève une
    TypeError — découvert en testant contre un vrai serveur PostgreSQL,
    pas en théorie."""
    dt = datetime.fromisoformat(raw)
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


@dataclass
class BadgeResult:
    tier: str  # "none", "EMMA", "Silver"
    latest_axiom_score: float | None
    submission_count_in_window: int
    reason: str


def get_submission_history(db_path: str, repo_url: str) -> list[dict]:
    """Récupère l'historique complet des soumissions pour un repo,
    triées de la plus récente à la plus ancienne."""
    conn = db_layer.get_db(db_path)
    rows = conn.execute(
        # Seules les soumissions dont le dépôt est attesté par GitHub (OIDC)
        # comptent pour un palier — voir security.py.
        "SELECT * FROM submissions WHERE repo_url = ? AND verification = 'github-oidc' "
        "ORDER BY submitted_at DESC",
        (repo_url,)
    ).fetchall()
    conn.close()
    return [dict(r) if not hasattr(r, "_data") else r._data for r in rows]


def compute_badge_tier(history: list[dict]) -> BadgeResult:
    """Calcule le palier technique à partir de l'historique de soumissions
    d'un repo (déjà trié du plus récent au plus ancien)."""
    if not history:
        return BadgeResult("none", None, 0, "Aucune vérification soumise pour ce serveur.")

    latest = history[0]
    latest_score = latest["axiom_score"]

    if latest_score < EMMA_MIN_AXIOM_SCORE:
        return BadgeResult(
            "none", latest_score, 0,
            f"Score AXIOM ({latest_score}%) sous le seuil requis pour EMMA ({EMMA_MIN_AXIOM_SCORE}%)."
        )

    # --- Vérifie la récurrence pour Silver ---
    # Exige un vrai étalement dans le temps (pas juste 3 vérifications
    # rapprochées) : la première et la dernière vérification qualifiante
    # doivent être espacées d'au moins SILVER_MIN_SPAN_DAYS.
    cutoff = datetime.now() - timedelta(days=SILVER_WINDOW_DAYS)
    qualifying = [
        h for h in history
        if _parse_timestamp(h["submitted_at"]) > cutoff
        and h["axiom_score"] >= SILVER_MIN_AXIOM_SCORE
    ]

    if len(qualifying) < SILVER_MIN_SUBMISSIONS:
        return BadgeResult(
            "EMMA", latest_score, len(qualifying),
            f"Score AXIOM valide ({latest_score}%), mais seulement "
            f"{len(qualifying)}/{SILVER_MIN_SUBMISSIONS} vérifications "
            f"à ≥{SILVER_MIN_AXIOM_SCORE}% requises pour Silver."
        )

    timestamps = sorted(_parse_timestamp(h["submitted_at"]) for h in qualifying)
    span_days = (timestamps[-1] - timestamps[0]).days

    if span_days < SILVER_MIN_SPAN_DAYS:
        return BadgeResult(
            "EMMA", latest_score, len(qualifying),
            f"Score AXIOM valide ({latest_score}%) et {len(qualifying)} vérifications "
            f"qualifiantes, mais étalées sur seulement {span_days} jour(s) "
            f"(minimum {SILVER_MIN_SPAN_DAYS} requis pour prouver une tenue dans la durée)."
        )

    return BadgeResult(
        "Silver", latest_score, len(qualifying),
        f"{len(qualifying)} vérifications à ≥{SILVER_MIN_AXIOM_SCORE}%, étalées sur "
        f"{span_days} jours — conformité maintenue dans le temps."
    )
