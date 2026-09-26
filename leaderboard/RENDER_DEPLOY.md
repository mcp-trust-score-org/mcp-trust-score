# Déployer le serveur combiné (classement + audit) sur Render

`server.py` fusionne l'API du classement ET le formulaire d'audit
organisationnel, avec une base de données SQLite partagée — nécessaire
pour que le calcul du palier Platinum puisse vérifier le palier
technique Silver d'un repo lié.

✅ **Testé réellement, y compris sous gunicorn** (le vrai serveur de
production, pas juste le serveur de développement Flask) : les deux
pages se chargent, la soumission de score fonctionne, et le cas complet
Platinum (audit organisationnel excellent + repo technique Silver) a
été vérifié de bout en bout pour la première fois — ça fonctionne.

## Déploiement sur Render (gratuit pour démarrer)

1. Crée un compte sur https://render.com (gratuit)
2. "New +" → "Web Service"
3. Connecte ton repo GitHub `mcp-trust-score-org/mcp-trust-score`
4. **Root Directory** : `leaderboard` (important — sinon Render cherche
   les fichiers à la racine du repo, pas dans ce sous-dossier)
5. **Build Command** : `pip install -r requirements.txt`
6. **Start Command** : `gunicorn server:app`
7. Plan : **Free**
8. "Create Web Service"

Render te donne une URL publique (type
`https://mcp-trust-score.onrender.com`) une fois le déploiement terminé
(quelques minutes).

## ⚠️ Limite du tier gratuit Render à connaître

Le plan gratuit met le service en veille après 15 minutes d'inactivité
— la première requête après une pause peut prendre 30-60 secondes à
répondre (le temps que le service se réveille). Pas un problème pour
un usage occasionnel, à garder en tête si tu veux une réactivité
constante (passerait alors sur un plan payant, ~7$/mois).

## ⚠️ Limite de la base SQLite sur Render (à connaître avant que ça pose problème)

Sur le tier gratuit, le système de fichiers de Render est **éphémère** —
la base `leaderboard.db` sera **réinitialisée à chaque redéploiement**
(nouveau push, ou simple redémarrage du service). Pour un usage sérieux
à moyen terme, il faudra migrer vers une vraie base de données
persistante (Render propose du PostgreSQL managé, gratuit sur un tier
limité) plutôt que le fichier SQLite local. Pas bloquant pour tester,
mais à anticiper avant de compter dessus pour de vraies données.

## Une fois déployé : branche l'Action dessus

Dans le workflow d'un utilisateur (`.github/workflows/*.yml`) :

Le job doit autoriser le jeton OIDC (sinon la soumission est refusée) :

```yaml
    permissions:
      contents: read
      id-token: write
    steps:
      - name: Vérifier la conformité MCP
        uses: mcp-trust-score-org/mcp-trust-score@v1
        with:
          server-command: 'python3 my_server.py'
          submit-to-leaderboard: 'true'
          leaderboard-api-url: 'https://ton-url-render.onrender.com'
```

## 🔒 Contrôles d'accès (variables d'environnement)

Tout est fermé par défaut : sans ces variables, les routes concernées
répondent 503 au lieu d'accepter n'importe qui.

| Variable | Rôle |
|---|---|
| `AUDITOR_TOKENS` | `alice:<jeton>,bob:<jeton>` — seuls ces auditeurs peuvent soumettre un audit (`/submit-audit`). Jetons de 24 caractères minimum, ex. `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Le nom de l'auditeur est enregistré avec l'audit. |
| `ADMIN_TOKEN` | protège `/badge/anchor`, `/framework-check`, `/test-email` (en-tête `Authorization: Bearer <jeton>`). 24 caractères minimum. |
| `OIDC_AUDIENCE` | audience attendue dans le jeton OIDC GitHub (défaut `mcp-trust-score`). |

`/submit` vérifie la signature du jeton OIDC avec les clés publiques de
GitHub (`token.actions.githubusercontent.com`) : le serveur doit pouvoir
joindre cette adresse.

Au premier démarrage, la base est migrée automatiquement : colonnes de
traçabilité ajoutées, anciennes soumissions (non attestées) et anciens
audits (sans auditeur) conservés en base mais retirés de l'affichage
public, et chaque ancien rapport d'audit reçoit un nouveau lien non
devinable (colonne `report_token`) : les anciens liens `/audit-report/<numéro>`
ne marchent plus, il faut renvoyer le nouveau lien aux entreprises concernées.

Pour un cron (ex. vérification des référentiels) :
`curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" https://…/framework-check`

## ⚠️ Point de vigilance technique : format des timestamps

Toutes les insertions en base utilisent `datetime('now')` de SQLite
(format `YYYY-MM-DD HH:MM:SS`). Si tu ajoutes un jour un script externe
qui insère des lignes avec `datetime.now().isoformat()` de Python
(format `YYYY-MM-DDTHH:MM:SS.ffffff`, avec un "T"), le tri
chronologique (`ORDER BY submitted_at`) se casse silencieusement — les
deux formats ne se trient pas correctement ensemble en comparaison de
chaînes de caractères. Toujours utiliser `datetime('now')` côté SQL
pour rester cohérent.

## Migration vers PostgreSQL (résout le problème de base éphémère)

✅ **Testée réellement** : un vrai serveur PostgreSQL 16 a été installé,
démarré, et utilisé pour tester l'intégralité du pipeline (soumission,
badges, audit, limite de fréquence, ancrage). Un vrai bug a été trouvé
et corrigé en cours de route : PostgreSQL inclut le fuseau horaire dans
ses timestamps, contrairement à SQLite, ce qui cassait la comparaison de
dates — corrigé dans `badge_tier._parse_timestamp()`.

### Créer la base PostgreSQL sur Render

1. Sur Render, "New +" → "PostgreSQL"
2. Nom : `mcp-trust-score-db`, plan **Free**
3. Une fois créée, copie l'**"Internal Database URL"** (pas l'externe —
   l'interne est plus rapide et gratuite pour la communication entre
   services Render)

### Connecter le service web à cette base

1. Va sur ton service `mcp-trust-score` → Environment Variables
2. Ajoute `DATABASE_URL` avec la valeur copiée à l'étape précédente
3. Sauvegarde — Render redéploie automatiquement

Le code bascule **automatiquement** sur PostgreSQL dès que cette
variable est présente — aucun autre changement nécessaire. Sans elle,
le code continue de fonctionner en SQLite (utile pour tester en local).

⚠️ **Limite du tier gratuit PostgreSQL Render** : expire après 90 jours
d'inactivité du compte de facturation (vérifie les conditions actuelles
sur render.com au moment de la mise en prod) — suffisant pour valider
le produit, mais prévoir un plan payant avant un usage long terme sérieux.

## Envoi d'emails d'alerte (Brevo — API HTTP, pas SMTP)

⚠️ **Découverte importante en conditions réelles** : la première version
utilisait SMTP classique, mais **Render bloque tous les ports SMTP (25,
465, 587) sur son tier gratuit** depuis septembre 2025 — confirmé par un
vrai crash du worker (`SystemExit` via timeout de connexion) lors d'un
test réel sur Render. Corrigé en passant par l'**API HTTP de Brevo**
(port 443, jamais bloqué par les hébergeurs cloud, puisque ça casserait
le web entier).

✅ **Testé** : gestion d'erreur (clé API manquante, pas d'abonnés) vérifiée.
⚠️ **Non testé** : le vrai appel réseau à `api.brevo.com` — bloqué par la
restriction réseau spécifique à cet environnement de dev (pas une
restriction Render). À confirmer au premier vrai test sur Render.

### Configurer Brevo (API, pas SMTP)

1. Sur Brevo : Menu (photo de profil) → **SMTP & API** → onglet **"API Keys"**
   (pas "SMTP", cette fois)
2. Génère une nouvelle clé API si tu n'en as pas déjà une
3. Sur Render, service `mcp-trust-score` → Environment Variables :
   - `BREVO_API_KEY` = ta clé API (pas la clé SMTP utilisée avant)
   - `SENDER_EMAIL` = ton adresse email vérifiée sur Brevo

Tu peux **retirer** les anciennes variables `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD` — elles ne sont plus utilisées.

Une fois configuré, teste avec :
```bash
curl -X POST https://mcp-trust-score.onrender.com/test-email
```
