"""
Questionnaire d'audit organisationnel — Domaines 1, 2, 3, 6, 7, 8 du
Framework AXIOM, appliqué à l'ENTREPRISE qui publie un agent/serveur MCP
(pas à l'agent lui-même — voir badge_tier.py pour les paliers techniques
EMMA/Silver, qui portent sur l'agent).

⚠️ Ce module NE calcule PAS de score automatiquement. Chaque question
nécessite un jugement humain (entretien, preuve documentaire) — c'est
volontaire et honnête : ces domaines ne sont pas vérifiables par un
script (contrairement aux Domaines 4 et 5, techniques, déjà automatisés).

Usage prévu : un auditeur humain remplit ce questionnaire lors d'un
entretien avec l'entreprise, note chaque critère selon l'échelle AXIOM
originale (absence -> bonne pratique en place), puis le score global
détermine l'éligibilité aux paliers Gold/Platinum.

Sources : reformulation fidèle des critères du fichier de notation AXIOM
original de l'auteure (Domaines 1, 2, 3, 6, 7, 8 — les domaines non
automatisables).
"""

from dataclasses import dataclass, field


@dataclass
class AuditQuestion:
    domain: str
    sub_domain: str
    question: str
    good_practice_description: str
    score: int = None
    evidence_notes: str = ""


AUDIT_QUESTIONNAIRE = [
    AuditQuestion(
        domain="1. Strategy & Vision",
        sub_domain="Vision IA",
        question="Le dirigeant porte-t-il une vision claire et des convictions sur l'IA, "
                  "au-delà d'un sujet purement technologique ?",
        good_practice_description="Des convictions claires sont portées par le dirigeant, "
                                   "cohérentes avec le business de l'entreprise.",
    ),
    AuditQuestion(
        domain="2. Governance & Organizational Maturity",
        sub_domain="Pilotage et gouvernance 360°",
        question="Existe-t-il un dispositif de pilotage (type AI-value cockpit) avec des "
                  "indicateurs clés (OKR) permettant aux dirigeants de suivre la stratégie IA ?",
        good_practice_description="Déploiement d'indicateurs clés répondant à la stratégie "
                                   "de l'organisation, suivis par les dirigeants.",
    ),
    AuditQuestion(
        domain="2. Governance & Organizational Maturity",
        sub_domain="Modèle organisationnel",
        question="Des valeurs éthiques et une culture de l'IA responsable sont-elles "
                  "diffusées dans les processus et la compétence des employés ?",
        good_practice_description="Gouvernance et processus robustes, culture IA intégrée "
                                   "à la compréhension des objectifs de l'entreprise.",
    ),
    AuditQuestion(
        domain="2. Governance & Organizational Maturity",
        sub_domain="Information & Communication",
        question="Des canaux de communication existent-ils pour diffuser les politiques IA "
                  "et remonter les problèmes/préoccupations des parties prenantes ?",
        good_practice_description="Canaux de diffusion des politiques ET canaux de "
                                   "remontée des préoccupations, dans les deux sens.",
    ),
    AuditQuestion(
        domain="3. Vendor Dependency",
        sub_domain="Gestion de l'écosystème IA",
        question="L'entreprise a-t-elle une gestion structurée de ses partenaires et "
                  "tiers IA pour sécuriser l'exécution de ses solutions ?",
        good_practice_description="Dépendance aux fournisseurs identifiée et gérée — "
                                   "critère à affiner lors de l'audit (peu détaillé dans "
                                   "le référentiel original).",
    ),
    AuditQuestion(
        domain="6. Financial Impact",
        sub_domain="Maîtrise des coûts",
        question="Un modèle de coûts est-il appliqué, avec un suivi régulier des dépenses "
                  "liées aux modèles/solutions IA ?",
        good_practice_description="Vision claire des coûts engagés + suivi régulier pour "
                                   "piloter les dépenses.",
    ),
    AuditQuestion(
        domain="7. Sustainability",
        sub_domain="Responsabilité",
        question="La supervision humaine et la responsabilité sont-elles intégrées tout "
                  "au long du cycle de vie de l'IA (conformité légale/réglementaire) ?",
        good_practice_description="Supervision humaine et responsabilité intégrées pour "
                                   "gérer les risques et respecter la réglementation.",
    ),
    AuditQuestion(
        domain="7. Sustainability",
        sub_domain="Équité",
        question="Les solutions IA sont-elles conçues pour réduire ou éliminer les biais "
                  "envers des individus, communautés ou groupes ?",
        good_practice_description="Conception explicitement orientée réduction des biais.",
    ),
    AuditQuestion(
        domain="7. Sustainability",
        sub_domain="Durabilité",
        question="Les solutions IA sont-elles conçues pour être économes en énergie et "
                  "réduire les émissions de carbone ?",
        good_practice_description="Sobriété énergétique et impact carbone pris en compte "
                                   "dès la conception.",
    ),
    AuditQuestion(
        domain="8. AI Empowerment",
        sub_domain="Manifeste et charte",
        question="Existe-t-il un manifeste et une charte IA déployés à grande échelle "
                  "dans l'organisation ?",
        good_practice_description="Manifeste/charte existants et effectivement déployés, "
                                   "pas juste rédigés.",
    ),
    AuditQuestion(
        domain="8. AI Empowerment",
        sub_domain="Acculturation et adoption",
        question="Une organisation est-elle en place pour faire monter en compétences les "
                  "équipes métiers sur l'IA au quotidien ?",
        good_practice_description="Pilotage actif de la montée en compétences et des "
                                   "usages IA, pas une formation ponctuelle isolée.",
    ),
]


def compute_full_report(questionnaire, scores: list[int], evidences: list[str] = None) -> dict:
    """Calcule un vrai bilan structuré à partir des réponses : score
    global, score par domaine (pour le radar), points forts/faibles
    identifiés automatiquement, et détail avec preuves.

    ⚠️ "Points forts/faibles" = les domaines avec le score moyen le plus
    haut/bas parmi ceux évalués — pas un jugement qualitatif indépendant,
    juste un classement relatif des propres réponses de l'entreprise."""
    if evidences is None:
        evidences = [""] * len(questionnaire)

    # Regroupe les scores par domaine
    domain_scores: dict[str, list[int]] = {}
    for q, score in zip(questionnaire, scores):
        domain_scores.setdefault(q.domain, []).append(score)

    domain_percentages = {
        domain: round(100 * sum(s) / (len(s) * 4), 1)
        for domain, s in domain_scores.items()
    }

    overall_percentage = round(100 * sum(scores) / (len(scores) * 4), 1)

    sorted_domains = sorted(domain_percentages.items(), key=lambda x: x[1], reverse=True)
    strengths = [d for d, p in sorted_domains[:2]]
    weaknesses = [d for d, p in sorted_domains[-2:]]

    details = []
    for q, score, evidence in zip(questionnaire, scores, evidences):
        details.append({
            "domain": q.domain,
            "sub_domain": q.sub_domain,
            "question": q.question,
            "score": score,
            "evidence": evidence,
        })

    return {
        "overall_percentage": overall_percentage,
        "domain_percentages": domain_percentages,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "details": details,
    }


RADAR_DOMAIN_ORDER = [
    "1. Strategy & Vision",
    "2. Governance & Organizational Maturity",
    "3. Vendor Dependency",
    "6. Financial Impact",
    "7. Sustainability",
    "8. AI Empowerment",
]


def generate_radar_svg(domain_percentages: dict, size: int = 420, order: list | None = None) -> str:
    """Génère un graphique radar en SVG pur — pas de librairie JS externe,
    donc pas de dépendance réseau côté navigateur, robuste et autonome.

    ✅ Testé : géométrie vérifiée mathématiquement (cas 100% partout =
    hexagone parfait au rayon max, cas 0% partout = point central)."""
    import math

    order = order or RADAR_DOMAIN_ORDER
    cx, cy = size / 2, size / 2
    max_r = size * 0.35
    n = len(order)

    def point_for(index: int, percentage: float) -> tuple:
        angle = math.radians(-90 + index * (360 / n))
        r = (percentage / 100) * max_r
        return (cx + r * math.cos(angle), cy + r * math.sin(angle))

    def axis_end(index: int) -> tuple:
        angle = math.radians(-90 + index * (360 / n))
        return (cx + max_r * math.cos(angle), cy + max_r * math.sin(angle))

    def label_pos(index: int) -> tuple:
        angle = math.radians(-90 + index * (360 / n))
        r = max_r * 1.22
        return (cx + r * math.cos(angle), cy + r * math.sin(angle))

    # Axes + grille (cercles concentriques à 25/50/75/100%)
    axes_svg = ""
    for i in range(n):
        ax, ay = axis_end(i)
        axes_svg += f'<line x1="{cx}" y1="{cy}" x2="{ax:.1f}" y2="{ay:.1f}" stroke="#e2e8f0" stroke-width="1"/>\n'

    grid_svg = ""
    for frac in [0.25, 0.5, 0.75, 1.0]:
        pts = [point_for(i, frac * 100) for i in range(n)]
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        grid_svg += f'<polygon points="{pts_str}" fill="none" stroke="#e2e8f0" stroke-width="1"/>\n'

    # Polygone des scores réels
    score_points = [
        point_for(i, domain_percentages.get(domain, 0))
        for i, domain in enumerate(order)
    ]
    score_pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in score_points)

    # Labels courts (juste le nom du domaine, sans le numéro/préfixe long)
    labels_svg = ""
    for i, domain in enumerate(order):
        lx, ly = label_pos(i)
        short_label = domain.split(". ", 1)[-1] if ". " in domain else domain
        anchor = "middle"
        if lx < cx - 10:
            anchor = "end"
        elif lx > cx + 10:
            anchor = "start"
        labels_svg += (
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="12" fill="#334155" '
            f'text-anchor="{anchor}" dominant-baseline="middle">{short_label}</text>\n'
        )

    pad = size * 0.3  # marge pour que les libellés longs ne soient pas coupés
    return f"""<svg viewBox="{-pad:.0f} 0 {size + 2 * pad:.0f} {size}" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">
{grid_svg}
{axes_svg}
<polygon points="{score_pts_str}" fill="#3b82f6" fill-opacity="0.25" stroke="#2563eb" stroke-width="2"/>
{labels_svg}
</svg>"""


def audit_summary(questionnaire):
    answered = [q for q in questionnaire if q.score is not None]
    if not answered:
        return {"status": "not_started", "domains_covered": 0}

    total_possible = len(answered) * 4
    total_scored = sum(q.score for q in answered)

    return {
        "status": "complete" if len(answered) == len(questionnaire) else "in_progress",
        "questions_answered": f"{len(answered)}/{len(questionnaire)}",
        "percentage": round(100 * total_scored / total_possible, 1) if total_possible else 0,
    }


if __name__ == "__main__":
    print(f"Questionnaire d'audit organisationnel AXIOM — {len(AUDIT_QUESTIONNAIRE)} questions\n")
    current_domain = None
    for q in AUDIT_QUESTIONNAIRE:
        if q.domain != current_domain:
            current_domain = q.domain
            print(f"\n=== {current_domain} ===")
        print(f"\n[{q.sub_domain}]")
        print(f"Q: {q.question}")
        print(f"Bonne pratique attendue: {q.good_practice_description}")
