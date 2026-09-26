"""Les tests utilisent une grille FICTIVE (tests/fixtures/axiom_test_grid.json) : mêmes identifiants et
titres que la partie publique, mais textes et pondérations inventés. La vraie grille est confidentielle
et n'est pas dans le dépôt."""

import os
from pathlib import Path

TEST_GRID = Path(__file__).parent / "fixtures" / "axiom_test_grid.json"
os.environ.setdefault("AXIOM_METHODOLOGY_FILE", str(TEST_GRID))
