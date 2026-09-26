# MCP Trust Score

[🇬🇧 English version](./README.md)

GitHub Action de conformité et de disponibilité pour serveurs MCP (Model
Context Protocol). Elle se connecte à un serveur MCP, vérifie son bon
fonctionnement, et calcule trois scores complémentaires pour donner un
signal de confiance rapide, dans le flux CI/CD d'un développeur.

## Ce que l'outil vérifie

À chaque exécution, l'outil :
1. Se connecte au serveur MCP fourni et vérifie qu'il répond correctement
   au protocole (handshake, liste des outils, liste des ressources)
2. Calcule un **score NIST** — auto-évaluation heuristique alignée sur les
   4 fonctions du NIST AI RMF (Govern, Map, Measure, Manage)
3. Calcule un **score AXIOM** — signaux techniques inspirés du Domaine 5
   ("Data & AI Technical Integrity") d'un référentiel de maturité IA propriétaire
4. Peut faire échouer le job CI si le score passe sous un seuil configurable

## ⚠️ Ce que ces scores sont, et ne sont pas

Ni le score NIST ni le score AXIOM ne sont des certifications officielles.
Ce sont des **auto-évaluations heuristiques**, basées sur des contrôles
techniques vérifiables automatiquement (présence de descriptions, de
métadonnées, réponse correcte au protocole). Ils donnent un signal utile
et rapide, pas un audit de conformité complet — ni le NIST AI RMF ni AXIOM
ne se réduisent à ce qu'un script peut observer depuis l'extérieur d'un
serveur MCP.

Ce n'est également **pas un outil de sécurité/pentest**. Pour ça, voir des
outils comme les scanners dédiés à l'OWASP MCP Top 10, qui inspectent le
trafic en temps réel — un rôle différent et complémentaire à celui-ci.

## Installation dans ton propre repo

Ajoute ce fichier à `.github/workflows/mcp-trust-score.yml` :

```yaml
name: MCP Trust Score

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  mcp-trust-score:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip install -r requirements.txt   # adapte à ton projet

      - name: Vérifier la conformité MCP
        uses: TON-PSEUDO/mcp-trust-score@v1
        with:
          server-command: 'python3 my_server.py'
          min-score: '70'
```

## Inputs

| Nom | Description | Défaut |
|---|---|---|
| `server-command` | Commande pour lancer ton serveur MCP | requis |
| `min-score` | Score NIST minimum (%) requis pour que le job réussisse | `70` |
| `enable-blockchain-anchor` | Ancre un hash du rapport sur OpenTimestamps (Bitcoin) | `false` |

## Outputs

| Nom | Description |
|---|---|
| `score` | Score NIST (%) |
| `axiom_score` | Score AXIOM (%) |
| `blockchain_proof` | Chemin du fichier de preuve `.ots`, vide si non activé ou échec |
| `passed` | `true`/`false` selon le seuil `min-score` |
| `reachable` | `true`/`false` selon que le serveur a répondu |

## Traçabilité par ancrage OpenTimestamps

Active `enable-blockchain-anchor: true` dans ton workflow pour que chaque
run calcule un hash SHA-256 du rapport (score NIST + AXIOM + nom du
serveur + date) et l'ancre sur la blockchain Bitcoin via le protocole
ouvert OpenTimestamps — gratuit, sans portefeuille crypto à gérer.

✅ **Testé** : la logique Python (calcul de hash, appel du CLI `ots`,
gestion d'erreur) fonctionne correctement — vérifié avec le CLI officiel,
qui produit l'erreur réseau attendue quand les serveurs de calendrier ne
sont pas joignables. Cette fonctionnalité est conçue pour échouer
**silencieusement** (elle n'affecte jamais `passed`/le succès du job) si
l'ancrage réseau échoue — seule la ligne `blockchain_proof` reste vide.

⚠️ **Non vérifié en conditions réelles** : la soumission effective aux
serveurs de calendrier OpenTimestamps nécessite un accès réseau sortant
que l'environnement de développement utilisé n'avait pas. Teste-la sur
un vrai run GitHub Actions pour confirmer qu'un fichier `.ots` valide est
généré.

Une preuve fraîchement créée n'est pas immédiatement vérifiable — il faut
généralement attendre qu'un bloc Bitcoin la confirme (jusqu'à quelques
heures). Utilise `ots upgrade <fichier>.ots` puis `ots verify <fichier>.ots`
plus tard pour la confirmer.

**Alternative** : `blockchain_anchor.py` documente aussi une option
d'ancrage direct sur Polygon (plus rapide, nécessite un portefeuille
crypto) — non branchée au workflow principal, à activer manuellement si
préférée à OpenTimestamps.

## Structure du projet

```
mcp-health-check/
├── action.yml              # Déclaration de la GitHub Action
├── run_action.py           # Point d'entrée, orchestre les 3 étapes
├── checker.py               # Connexion au serveur MCP + contrôles de base
├── nist_score.py            # Score aligné NIST AI RMF
├── axiom_score.py           # Score inspiré du référentiel AXIOM (Domaine 5)
├── blockchain_anchor.py     # Traçabilité par hash (optionnel, non branché)
├── test_server.py           # Serveur MCP minimal pour tester l'Action
└── action-package/
    └── example-workflow.yml # Exemple de workflow à copier dans un repo cible
```

## Licence

MIT — voir le fichier `LICENSE`. Réutilisation, modification et
redistribution libres, y compris commerciales, à condition de conserver
la mention de copyright.

## Classement public (leaderboard)

Un classement public des serveurs MCP par score, dans `LEADERBOARD.md`,
généré automatiquement depuis `leaderboard/entries.json`.

**Pour y ajouter ton serveur** : ouvre une Pull Request ajoutant ton entrée
dans `leaderboard/entries.json` (format visible dans le fichier), avec ton
score obtenu via cette Action. Le fichier `LEADERBOARD.md` se régénère
automatiquement au merge (voir `action-package/update-leaderboard-workflow.yml`
pour l'activer sur ta propre instance).

✅ **Testé** : le script de génération (`leaderboard/generate_leaderboard.py`)
a été vérifié avec plusieurs entrées, dont une volontairement invalide —
il trie correctement par score, ignore proprement les entrées mal formées
avec un message d'erreur clair, et affiche un hash de preuve tronqué quand
disponible.

⚠️ **Honnêteté à garder en tête** : ces scores sont des auto-évaluations
soumises par les développeurs eux-mêmes, pas auditées par un tiers. La
preuve blockchain garantit l'intégrité du score dans le temps (pas modifié
après coup), pas son exactitude initiale.

## Soumission automatique au classement (alternative à la PR manuelle)

En plus (ou à la place) de la soumission par Pull Request, l'Action peut
soumettre automatiquement le score à une API centralisée, sans aucune
intervention manuelle du développeur.

```yaml
jobs:
  mcp-trust-score:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write   # obligatoire : GitHub atteste le dépôt qui soumet
    steps:
      - uses: actions/checkout@v4
      - name: Vérifier la conformité MCP
        uses: TON-PSEUDO/mcp-trust-score@v1
        with:
          server-command: 'python3 my_server.py'
          submit-to-leaderboard: 'true'
          leaderboard-api-url: 'https://ton-api-hebergee.com'
```

🔒 **Soumission authentifiée** : l'Action joint un jeton OIDC signé par
GitHub, qui atteste le dépôt d'où vient la soumission. L'API ignore le
`repo_url` déclaré et utilise celui du jeton : impossible de soumettre au
nom d'un dépôt qui n'est pas le sien. Seules ces soumissions attestées
apparaissent au classement et comptent pour les paliers EMMA/Silver.
Limite : le jeton prouve *qui* soumet, pas que le score a été calculé
honnêtement (un workflow peut être modifié).

✅ **Testé de bout en bout** : l'API (`leaderboard/api.py`) a été lancée
en local, l'Action a envoyé une vraie requête HTTP, la donnée est arrivée
correctement en base — vérifié avec succès, y compris les protections
anti-abus (score hors limites rejeté, hash incohérent détecté, limite de
fréquence par repo à 10 minutes).

⚠️ **Limite honnête** : cette automatisation ne peut pas vérifier
l'authenticité du serveur MCP testé — elle fait confiance au score
envoyé par le checker. La preuve blockchain (si activée en même temps)
garantit seulement que le rapport n'a pas été modifié après soumission,
pas que le score initial est authentique.

### Héberger ta propre instance de l'API

1. `pip install flask` (déjà dans `requirements.txt`)
2. Héberge `leaderboard/api.py` sur Render, Railway, ou un petit VPS
   (mêmes options que documentées pour d'autres projets — quelques
   euros/mois ou gratuit selon le tier)
3. Utilise l'URL publique obtenue comme `leaderboard-api-url`
4. Le classement est visible sur `/` (page HTML) et `/leaderboard.json`
   (API brute) une fois hébergé

## Site public du classement (GitHub Pages, gratuit)

Une vraie page web (`docs/index.html`), générée automatiquement par
`leaderboard/generate_leaderboard.py`, hébergeable gratuitement sur
GitHub Pages — zéro serveur à maintenir, zéro coût, contrairement à
l'API optionnelle décrite plus haut.

✅ **Testé** : la page HTML se génère correctement depuis `entries.json`,
affichage vérifié (lien cliquable, score coloré, disclaimer).

**Pour l'activer sur ton repo :**
1. Repo GitHub → Settings → Pages
2. "Source" → "Deploy from a branch"
3. Branche `main`, dossier `/docs`
4. Sauvegarde

Ton site sera visible sous quelques minutes à `https://mcp-trust-score-org.github.io/mcp-trust-score/`.

Combine avec `action-package/update-leaderboard-workflow.yml` pour que le
site se mette à jour automatiquement à chaque Pull Request mergée sur
`leaderboard/entries.json`.
