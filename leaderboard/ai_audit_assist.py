"""
Data room + brouillon d'audit AXIOM par un modèle d'IA LOCAL (Ollama).

Principe : l'entreprise auditée remet ses documents (politiques IA, chartes,
rapports RSE, comptes rendus de gouvernance...) dans un dossier « data room ».
Cet outil les lit et demande à un modèle qui tourne sur TA machine, via
Ollama, de proposer un BROUILLON de niveau (0-4) pour chaque sous-domaine de
la grille AXIOM, avec la citation qui l'appuie. Le brouillon est ensuite
plafonné avec les mêmes règles que le formulaire (preuve « Document » : N3 au
maximum ; mesure technique exigée pour certains sous-domaines).

Confidentialité : ni les documents du client ni la grille ne quittent la
machine. L'outil refuse de parler à un serveur Ollama distant, sauf option
explicite --allow-remote.

⚠️ Ceci reste un BROUILLON, pas un audit :
- le modèle ne doit noter QUE ce qui est écrit dans les documents ; un
  sujet non couvert est marqué « aucune preuve » ;
- un évaluateur DOIT relire chaque niveau avant de le saisir dans le
  formulaire (/audit) — rien n'est soumis automatiquement ;
- un modèle local est en général moins fiable qu'un grand modèle en ligne.

Prérequis :
  - Ollama lancé localement (https://ollama.com) avec un modèle téléchargé,
    par ex. `ollama pull mistral-small` ;
  - pip install requests pypdf ;
  - la grille confidentielle : variable AXIOM_METHODOLOGY_FILE.

Usage :
  python3 ai_audit_assist.py <dossier_data_room> --model mistral-small
  (ou variable OLLAMA_MODEL ; OLLAMA_URL, défaut http://localhost:11434)
"""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

import axiom

DEFAULT_OLLAMA_URL = "http://localhost:11434"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MAX_DOCS_CHARS = int(os.environ.get("AXIOM_MAX_DOCS_CHARS", "24000"))
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))

try:
    import pypdf
except ImportError:
    pypdf = None


def read_document(file_path: Path) -> str:
    """Lit un document texte (.txt, .md) ou PDF (.pdf)."""
    if file_path.suffix.lower() == ".pdf":
        if pypdf is None:
            raise EnvironmentError("Installe pypdf pour lire les fichiers PDF : pip install pypdf")
        reader = pypdf.PdfReader(str(file_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if file_path.suffix.lower() in [".txt", ".md"]:
        return file_path.read_text(encoding="utf-8", errors="ignore")

    raise ValueError(f"Type de fichier non supporté : {file_path.suffix} (utilise .txt, .md ou .pdf)")


def load_data_room(data_room_path: str) -> dict:
    """Lit tous les documents d'un dossier data room et retourne leur
    contenu texte, avec le nom du fichier source pour chaque extrait."""
    folder = Path(data_room_path)
    if not folder.exists():
        raise FileNotFoundError(f"Dossier data room introuvable : {data_room_path}")

    documents = {}
    for file_path in folder.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in [".txt", ".md", ".pdf"]:
            try:
                content = read_document(file_path)
                if content.strip():
                    documents[file_path.name] = content
            except Exception as e:
                print(f"⚠️  Impossible de lire {file_path.name} : {e}")

    return documents


def documents_block(documents: dict) -> str:
    """Contenu des documents, tronqué pour tenir dans le contexte d'un modèle local."""
    per_doc = max(1500, MAX_DOCS_CHARS // max(1, len(documents)))
    return "\n\n".join(f"--- Document : {name} ---\n{content[:per_doc]}" for name, content in documents.items())


def build_subdomain_prompt(sub: dict, docs_text: str) -> str:
    """Un sous-domaine à la fois : prompts courts, plus fiables avec un modèle local."""
    levels = "\n".join(f"  N{i} : {t}" for i, t in enumerate(sub["levels"]))
    return f"""Tu évalues UN sous-domaine de la grille AXIOM à partir UNIQUEMENT des documents fournis.

SOUS-DOMAINE [{sub['id']}] {sub['domain']} / {sub['title']}
Bonne pratique : {sub['good_practice']}
Niveaux (cumulatifs : un niveau suppose tous les précédents) :
{levels}
Preuves attendues :
{sub['evidence_rules']}

RÈGLES STRICTES :
- Ne note QUE ce qui est explicitement écrit dans les documents.
- Si les documents ne couvrent pas ce sous-domaine : "level": null et "confidence": "aucune_preuve".
- Cite un passage court (une phrase) et le nom du document.
- Niveaux possibles : 0 à 4 par pas de 0,5.

DOCUMENTS :
{docs_text}

Réponds UNIQUEMENT avec ce JSON :
{{"level": 2, "evidence_quote": "citation courte — nom du document", "confidence": "haute" | "moyenne" | "aucune_preuve"}}"""


def check_local(url: str, allow_remote: bool) -> None:
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS and not allow_remote:
        raise SystemExit(
            f"Refusé : {url} n'est pas un serveur local. Les documents du client ne doivent pas quitter "
            f"la machine. Utilise --allow-remote seulement si ce serveur t'appartient.")


def check_model(url: str, model: str | None) -> str:
    try:
        tags = requests.get(f"{url}/api/tags", timeout=5).json().get("models", [])
    except requests.RequestException as e:
        raise SystemExit(f"Ollama injoignable sur {url} ({e}). Lance-le avec `ollama serve`.") from e
    installed = [t.get("name", "") for t in tags]
    if not model:
        raise SystemExit("Choisis un modèle avec --model (ou OLLAMA_MODEL). Installés : "
                         + (", ".join(installed) or "aucun — `ollama pull <modèle>`"))
    if not any(n == model or n.split(":")[0] == model for n in installed):
        raise SystemExit(f"Modèle {model!r} absent. Installés : {', '.join(installed) or 'aucun'}. "
                         f"Télécharge-le avec `ollama pull {model}`.")
    return model


def ask_ollama(url: str, model: str, prompt: str) -> dict:
    resp = requests.post(f"{url}/api/chat", timeout=600, json={
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    })
    resp.raise_for_status()
    content = resp.json().get("message", {}).get("content", "")
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {"level": None, "evidence_quote": "réponse illisible du modèle", "confidence": "aucune_preuve"}
    return data if isinstance(data, dict) else {"level": None, "confidence": "aucune_preuve"}


def run_ai_assisted_audit(data_room_path: str, model: str | None, url: str = DEFAULT_OLLAMA_URL,
                          allow_remote: bool = False) -> dict:
    """Lit la data room, interroge le modèle local sous-domaine par sous-domaine,
    et retourne le brouillon plafonné avec les règles de la méthode."""
    check_local(url, allow_remote)
    model = check_model(url, model)
    method = axiom.load_methodology()

    documents = load_data_room(data_room_path)
    if not documents:
        raise ValueError(f"Aucun document lisible trouvé dans {data_room_path} (formats : .txt, .md, .pdf)")
    print(f"📄 {len(documents)} document(s) : {', '.join(documents.keys())}")
    docs_text = documents_block(documents)

    answers = []
    for i, sub in enumerate(method["sub_domains"], start=1):
        print(f"🤖 [{i}/{len(method['sub_domains'])}] {sub['id']} {sub['title'][:60]}…")
        answer = ask_ollama(url, model, build_subdomain_prompt(sub, docs_text))
        answers.append({**answer, "id": sub["id"]})
    draft = draft_from_answers(answers)
    draft["model"] = f"ollama:{model}"
    return draft


def draft_from_answers(answers: list[dict]) -> dict:
    """Transforme les réponses de l'IA en brouillon d'audit : les niveaux sont
    traités comme des preuves « Document » et plafonnés comme dans le formulaire."""
    method = axiom.load_methodology()
    levels = axiom.allowed_levels()
    raw_entries, kept = [], []
    for a in answers:
        if a.get("id") not in method["_by_id"]:
            continue
        lvl = a.get("level")
        if isinstance(lvl, (int, float)) and not isinstance(lvl, bool):
            lvl = min(levels, key=lambda v: abs(v - float(lvl)))  # arrondi au demi-niveau
        else:
            lvl = None
        quote = a.get("evidence_quote") or ""
        has_quote = bool(quote) and "aucune mention" not in quote.lower()
        raw_entries.append({"id": a["id"], "level": lvl,
                            "evidence": "Document" if (lvl is not None and has_quote) else None,
                            "justification": quote})
        kept.append({**a, "level": lvl})
    entries = axiom.parse_entries(raw_entries)
    evaluation = axiom.evaluate(entries)
    for a in kept:
        sub = method["_by_id"][a["id"]]
        detail = next(d for d in evaluation["details"] if d["id"] == a["id"])
        a.update(domain=sub["domain"], sub_domain=sub["title"], retained=detail["retained"],
                 capped=detail["capped"])
    return {
        "methodology": evaluation["methodology"],
        "answers": kept,
        "draft_score": evaluation["score"],
        "draft_coverage": evaluation["coverage"],
        "ai_assisted": True,
        "human_reviewed": False,  # doit être mis à True manuellement après relecture
    }


def print_draft_report(result: dict):
    print("\n" + "=" * 70)
    print(f"BROUILLON D'AUDIT {result['methodology']} — GÉNÉRÉ PAR IA, RELECTURE HUMAINE REQUISE")
    print("=" * 70)

    for a in result["answers"]:
        flag = "⚠️ " if a.get("confidence") == "aucune_preuve" else ""
        print(f"\n{flag}[{a['id']}] {a['domain']} / {a['sub_domain']}")
        if a["level"] is None:
            print("  Non évalué (aucune preuve dans les documents)")
        else:
            capped = f" — {a['capped']}" if a.get("capped") else ""
            print(f"  Proposé : {a['level']:g} · retenu : {a['retained']:g}{capped} (confiance : {a.get('confidence')})")
        print(f"  Preuve citée : {a.get('evidence_quote')}")

    no_evidence = sum(1 for a in result["answers"] if a["level"] is None)
    print(f"\n{'=' * 70}")
    score = result["draft_score"]
    print(f"Score brouillon : {score if score is not None else '—'} % — couverture {result['draft_coverage']} %")
    print(f"⚠️  {no_evidence}/{len(result['answers'])} sous-domaine(s) sans preuve dans les documents.")
    print("Ce brouillon doit être relu et validé par un évaluateur avant saisie dans le formulaire (/audit).")
    print("=" * 70)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Brouillon d'audit AXIOM avec un modèle local (Ollama).")
    parser.add_argument("data_room", help="dossier contenant les documents (.txt, .md, .pdf)")
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL"), help="modèle Ollama, ex. mistral-small")
    parser.add_argument("--url", default=os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL))
    parser.add_argument("--allow-remote", action="store_true",
                        help="autoriser un serveur Ollama non local (les documents quitteraient la machine)")
    args = parser.parse_args(argv)

    result = run_ai_assisted_audit(args.data_room, args.model, args.url, args.allow_remote)
    print_draft_report(result)

    output_path = Path(args.data_room) / "draft_audit_result.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Brouillon sauvegardé : {output_path}")


if __name__ == "__main__":
    main()
