"""
Contrôles d'accès du service de classement.

Trois mécanismes, tous « fermés par défaut » : si la configuration
manque, la route refuse au lieu d'accepter.

1. Soumission de score (/submit) — jeton OIDC GitHub Actions.
   GitHub signe un JWT qui atteste « ce job tourne dans le dépôt X ».
   On vérifie la signature (clés publiques de GitHub), l'émetteur,
   l'audience et l'expiration, et c'est le dépôt du jeton qui fait foi :
   plus personne ne peut soumettre au nom d'un dépôt qui n'est pas le sien.
   ⚠️ Limite : ça prouve QUI soumet, pas que le score a été calculé
   honnêtement (le workflow du dépôt peut être modifié). Pour les paliers
   payants, la mesure doit être faite par notre propre infrastructure.

2. Audits organisationnels (/audit, /submit-audit) — jetons évaluateurs.
   Variable AUDITOR_TOKENS = "alice:<jeton>,bob:<jeton>". Chaque audit
   enregistre l'évaluateur qui l'a soumis. Le formulaire (qui affiche la
   grille confidentielle) demande les identifiants via le navigateur
   (authentification HTTP Basic : identifiant = nom, mot de passe = jeton) ;
   l'API accepte aussi « Authorization: Bearer <jeton> ».

3. Actions d'administration (ancrage, vérification des référentiels,
   email de test) — jeton ADMIN_TOKEN.
"""

from __future__ import annotations

import base64
import hmac
import os
import re
import secrets
from functools import wraps

from flask import Response, g, jsonify, request

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"
DEFAULT_AUDIENCE = "mcp-trust-score"

REPO_URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")

_jwks_client = None


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def oidc_audience() -> str:
    return os.environ.get("OIDC_AUDIENCE", DEFAULT_AUDIENCE)


def _get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        import jwt

        _jwks_client = jwt.PyJWKClient(GITHUB_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client


def verify_github_oidc(token: str) -> dict:
    """Vérifie un JWT OIDC émis par GitHub Actions et retourne ses claims."""
    import jwt

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=oidc_audience(),
            issuer=GITHUB_OIDC_ISSUER,
            options={"require": ["exp", "iat", "iss", "aud", "repository"]},
            leeway=30,
        )
    except jwt.PyJWTError as e:
        raise AuthError(f"Jeton OIDC GitHub invalide : {e}") from e
    except Exception as e:  # réseau (JWKS injoignable), clé inconnue...
        raise AuthError(f"Impossible de vérifier le jeton OIDC : {e}", status=503) from e
    return claims


def repo_url_from_claims(claims: dict) -> str:
    url = f"https://github.com/{claims['repository']}"
    if not REPO_URL_RE.match(url):
        raise AuthError("Claim 'repository' inattendu dans le jeton OIDC", status=400)
    return url


def normalize_repo_url(url: str | None) -> str | None:
    """URL de dépôt GitHub stricte, ou None. Bloque aussi les liens javascript: & co."""
    if not url:
        return None
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url if REPO_URL_RE.match(url) else None


def _bearer() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def _parse_auditor_tokens() -> dict[str, str]:
    """AUDITOR_TOKENS="alice:tokA,bob:tokB" -> {tokA: alice, tokB: bob}."""
    tokens = {}
    for item in os.environ.get("AUDITOR_TOKENS", "").split(","):
        if ":" in item:
            label, tok = item.split(":", 1)
            if label.strip() and len(tok.strip()) >= 24:
                tokens[tok.strip()] = label.strip()
    return tokens


def _auditor_from_request(tokens: dict[str, str]) -> str | None:
    """Bearer <jeton>, ou Basic <nom:jeton> (le nom doit correspondre au jeton)."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("basic "):
        try:
            user, _, pwd = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
        except Exception:  # noqa: BLE001
            return None
        label = _match(pwd, tokens)
        return label if label and (not user or hmac.compare_digest(user.encode(), label.encode())) else None
    return _match(_bearer(), tokens)


def _match(presented: str | None, candidates: dict[str, str]) -> str | None:
    if not presented:
        return None
    found = None
    for tok, label in candidates.items():
        if hmac.compare_digest(presented.encode(), tok.encode()):
            found = label
    return found


def require_github_oidc(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _bearer()
        if not token:
            return jsonify({"error": "Authentification requise : jeton OIDC GitHub Actions "
                                     "(permissions: id-token: write) dans l'en-tête Authorization."}), 401
        try:
            g.oidc_claims = verify_github_oidc(token)
            g.repo_url = repo_url_from_claims(g.oidc_claims)
        except AuthError as e:
            return jsonify({"error": str(e)}), e.status
        return view(*args, **kwargs)
    return wrapper


def require_auditor(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        tokens = _parse_auditor_tokens()
        if not tokens:
            return jsonify({"error": "Soumission d'audit désactivée : aucun auditeur configuré (AUDITOR_TOKENS)."}), 503
        label = _auditor_from_request(tokens)
        if not label:
            return jsonify({"error": "Jeton auditeur invalide ou manquant."}), 401
        g.auditor = label
        return view(*args, **kwargs)
    return wrapper


def require_auditor_page(view):
    """Pages réservées aux évaluateurs : le navigateur affiche une demande d'identifiants."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        tokens = _parse_auditor_tokens()
        if not tokens:
            return Response("Audit désactivé : aucun évaluateur configuré (AUDITOR_TOKENS).", 503,
                            {"Content-Type": "text/plain; charset=utf-8"})
        label = _auditor_from_request(tokens)
        if not label:
            return Response("Accès réservé aux évaluateurs.", 401,
                            {"WWW-Authenticate": 'Basic realm="Evaluateurs AXIOM", charset="UTF-8"',
                             "Content-Type": "text/plain; charset=utf-8"})
        g.auditor = label
        return view(*args, **kwargs)
    return wrapper


def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        admin = os.environ.get("ADMIN_TOKEN", "")
        if len(admin) < 24:
            return jsonify({"error": "Action d'administration désactivée : ADMIN_TOKEN absent ou trop court."}), 503
        if not _match(_bearer(), {admin: "admin"}):
            return jsonify({"error": "Jeton administrateur invalide ou manquant."}), 401
        return view(*args, **kwargs)
    return wrapper


def new_report_token() -> str:
    """Identifiant non devinable pour l'URL d'un rapport d'audit."""
    return secrets.token_urlsafe(24)
