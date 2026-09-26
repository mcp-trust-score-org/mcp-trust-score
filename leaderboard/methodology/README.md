# Méthodologie AXIOM

- `axiom_public_v1_1.json` (publique) : domaines, titres des sous-domaines, échelle, types de preuve et
  plafonds, formule du score. Affichée sur `/methodologie`.
- La grille complète (confidentielle : texte des niveaux, règles de preuve, pondérations,
  correspondances) n'est **pas** dans ce dépôt. Le serveur la lit dans le fichier indiqué par
  `AXIOM_METHODOLOGY_FILE`. Sur Render : Environment → Secret Files → ajouter `axiom_v1_1.json`
  (monté dans `/etc/secrets/axiom_v1_1.json`), puis `AXIOM_METHODOLOGY_FILE=/etc/secrets/axiom_v1_1.json`.
- Le classeur `AXIOM_methode_v1.1.xlsx` reste chez l'auteure. Ne jamais committer la grille complète :
  le dépôt est public, et l'historique Git garde tout ce qui y a été ajouté.

Le serveur vérifie que la grille confidentielle correspond à la partie publique (même version, mêmes
sous-domaines). Pour recouper le moteur avec le classeur :
`AXIOM_REAL_GRID=/chemin/axiom_v1_1.json python -m pytest tests/test_axiom.py -k real`.
