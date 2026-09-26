"""
Moteur de calcul de la méthode AXIOM (v1.1).

La méthode a deux parties :
- methodology/axiom_public_v1_1.json (dans le dépôt, publique) : domaines,
  titres des sous-domaines, échelle, types de preuve et plafonds, formule ;
- la grille complète (confidentielle) : texte des niveaux, règles de preuve,
  pondérations, correspondances. Elle n'est PAS dans le dépôt : le serveur la
  lit dans le fichier indiqué par la variable AXIOM_METHODOLOGY_FILE (sur
  Render : un « Secret File », par ex. /etc/secrets/axiom_v1_1.json).
  Sans elle, l'audit est désactivé (la page publique reste disponible).

Règles appliquées (identiques au classeur AXIOM_methode_v1.1.xlsx) :
- niveau proposé de 0 à 4 par pas de 0,5, ou N/A (non évalué) ;
- niveau retenu = min(niveau proposé, plafond du type de preuve,
  plafond « mesure » pour les sous-domaines qui exigent une mesure
  technique dès N3) ;
- score = Σ(retenu × pondération) ÷ Σ(4 × pondération) sur les
  sous-domaines évalués ; couverture = part pondérée évaluée.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PUBLIC_FILE = Path(__file__).parent / "methodology" / "axiom_public_v1_1.json"
GRID_ENV = "AXIOM_METHODOLOGY_FILE"
MAX_JUSTIFICATION_CHARS = 2000
NOT_EVALUATED = "N/A"


class MethodologyUnavailable(RuntimeError):
    """La grille confidentielle n'est pas configurée sur ce serveur."""


@lru_cache(maxsize=1)
def load_public() -> dict:
    with open(PUBLIC_FILE, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_methodology() -> dict:
    """Grille complète (confidentielle). Lève MethodologyUnavailable si absente ou incohérente."""
    path = os.environ.get(GRID_ENV, "").strip()
    if not path or not os.path.isfile(path):
        raise MethodologyUnavailable(
            f"Grille AXIOM confidentielle non configurée (variable {GRID_ENV}).")
    with open(path, encoding="utf-8") as f:
        method = json.load(f)
    public = load_public()
    if method.get("version") != public["version"] or \
            [s["id"] for s in method["sub_domains"]] != [s["id"] for s in public["sub_domains"]]:
        raise MethodologyUnavailable(
            "La grille confidentielle ne correspond pas à la partie publique (version ou sous-domaines).")
    method["_by_id"] = {s["id"]: s for s in method["sub_domains"]}
    method["_evidence_caps"] = {e["name"]: e["max_level"] for e in method["evidence_types"]}
    method["_domains"] = list(dict.fromkeys(s["domain"] for s in method["sub_domains"]))
    return method


def is_available() -> bool:
    try:
        load_methodology()
        return True
    except MethodologyUnavailable:
        return False


def version_label() -> str:
    m = load_public()
    return f"{m['name']} v{m['version']}"


def allowed_levels() -> list[float]:
    scale = load_public()["scale"]
    steps = int((scale["max"] - scale["min"]) / scale["step"])
    return [scale["min"] + i * scale["step"] for i in range(steps + 1)]


@dataclass
class Entry:
    id: str
    level: float | None  # None = N/A (non évalué)
    evidence: str | None
    justification: str


class ValidationError(ValueError):
    pass


def parse_entries(raw) -> list[Entry]:
    """Valide les réponses envoyées par le formulaire.

    Format : [{"id": "1.1", "level": 2 | "N/A" | null, "evidence": "Document", "justification": "..."}]
    Un sous-domaine absent est considéré comme non évalué."""
    method = load_methodology()
    if not isinstance(raw, list):
        raise ValidationError("entries doit être une liste")
    levels = allowed_levels()
    seen: dict[str, Entry] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("chaque entrée doit être un objet")
        sid = str(item.get("id", ""))
        if sid not in method["_by_id"]:
            raise ValidationError(f"sous-domaine inconnu : {sid!r}")
        if sid in seen:
            raise ValidationError(f"sous-domaine en double : {sid}")
        lvl = item.get("level")
        if lvl in (None, "", NOT_EVALUATED):
            level = None
        elif isinstance(lvl, bool) or not isinstance(lvl, (int, float)) or float(lvl) not in levels:
            raise ValidationError(f"{sid} : niveau invalide {lvl!r} (0 à 4 par pas de 0,5, ou N/A)")
        else:
            level = float(lvl)
        evidence = item.get("evidence") or None
        if evidence is not None and evidence not in method["_evidence_caps"]:
            raise ValidationError(f"{sid} : type de preuve inconnu {evidence!r}")
        just = str(item.get("justification") or "")[:MAX_JUSTIFICATION_CHARS]
        seen[sid] = Entry(sid, level, evidence, just)
    return [seen.get(s["id"], Entry(s["id"], None, None, "")) for s in method["sub_domains"]]


def retained_level(entry: Entry) -> tuple[float | None, str | None]:
    """(niveau retenu, raison du plafonnement éventuel)."""
    if entry.level is None:
        return None, None
    method = load_methodology()
    sub = method["_by_id"][entry.id]
    cap_evidence = method["_evidence_caps"].get(entry.evidence or "Aucune", 0)
    cap_measure = method["scale"]["max"]
    if sub["measured_required_from_n3"] and entry.evidence != method["measured_evidence"]:
        cap_measure = method["measured_cap"]
    retained = min(entry.level, cap_evidence, cap_measure)
    reason = None
    if retained < entry.level:
        if cap_measure < cap_evidence and retained == cap_measure:
            reason = f"plafonné à {cap_measure:g} : mesure technique exigée au-delà"
        else:
            reason = f"plafonné à {cap_evidence:g} par le type de preuve ({entry.evidence or 'aucune'})"
    return retained, reason


def evaluate(entries: list[Entry]) -> dict:
    method = load_methodology()
    scale_max = method["scale"]["max"]
    details = []
    total_weight = 0.0
    num = den = 0.0
    per_domain: dict[str, dict] = {d: {"num": 0.0, "den": 0.0, "weight": 0.0} for d in method["_domains"]}
    for e in entries:
        sub = method["_by_id"][e.id]
        w = float(sub["weight"])
        total_weight += w
        per_domain[sub["domain"]]["weight"] += w
        retained, reason = retained_level(e)
        if retained is not None:
            num += retained * w
            den += scale_max * w
            per_domain[sub["domain"]]["num"] += retained * w
            per_domain[sub["domain"]]["den"] += scale_max * w
        level_idx = int(retained) if retained is not None else None
        details.append({
            "id": e.id, "domain": sub["domain"], "title": sub["title"], "weight": w,
            "level": e.level, "evidence": e.evidence, "retained": retained, "capped": reason,
            "justification": e.justification,
            "retained_text": sub["levels"][level_idx] if level_idx is not None else None,
            "label": method["scale"]["labels"][level_idx] if level_idx is not None else None,
        })

    domains = {}
    for d, v in per_domain.items():
        domains[d] = {
            "score": round(100 * v["num"] / v["den"], 1) if v["den"] else None,
            "coverage": round(100 * v["den"] / (scale_max * v["weight"]), 1) if v["weight"] else None,
        }
    evaluated = [d for d in details if d["retained"] is not None]
    ranked = sorted(((d, v["score"]) for d, v in domains.items() if v["score"] is not None),
                    key=lambda x: x[1], reverse=True)
    return {
        "methodology": version_label(),
        "score": round(100 * num / den, 1) if den else None,
        "coverage": round(100 * den / (scale_max * total_weight), 1) if total_weight else 0.0,
        "evaluated": len(evaluated),
        "total": len(details),
        "mean_level": round(sum(d["retained"] for d in evaluated) / len(evaluated), 2) if evaluated else None,
        "capped_count": sum(1 for d in details if d["capped"]),
        "domains": domains,
        "strengths": [d for d, _ in ranked[:2]],
        "weaknesses": [d for d, _ in ranked[-2:]] if len(ranked) > 2 else [],
        "details": details,
    }


def entries_to_json(entries: list[Entry]) -> list[dict]:
    return [{"id": e.id, "level": e.level, "evidence": e.evidence, "justification": e.justification}
            for e in entries]
