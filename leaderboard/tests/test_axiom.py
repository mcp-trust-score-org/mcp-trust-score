"""Tests du moteur AXIOM (grille fictive), + recoupement optionnel avec la vraie grille."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import axiom  # noqa: E402

TEST_GRID = str(Path(__file__).parent / "fixtures" / "axiom_test_grid.json")


@pytest.fixture(autouse=True)
def test_grid(monkeypatch):
    monkeypatch.setenv(axiom.GRID_ENV, TEST_GRID)
    axiom.load_methodology.cache_clear()
    yield
    axiom.load_methodology.cache_clear()


def _entries(levels, evidence="Source publique"):
    return axiom.parse_entries([{"id": k, "level": v, "evidence": evidence, "justification": "source"}
                                for k, v in levels.items()])


def test_public_part_has_no_confidential_fields():
    public = axiom.load_public()
    assert public["version"] == "1.1" and len(public["sub_domains"]) == 27
    for s in public["sub_domains"]:
        assert set(s) == {"id", "domain_number", "domain", "title", "measured_required_from_n3"}
    assert [s["id"] for s in public["sub_domains"] if s["measured_required_from_n3"]] == ["9.3", "9.4", "9.6"]


def test_grid_missing_or_inconsistent(monkeypatch, tmp_path):
    monkeypatch.delenv(axiom.GRID_ENV)
    axiom.load_methodology.cache_clear()
    assert not axiom.is_available()
    with pytest.raises(axiom.MethodologyUnavailable):
        axiom.parse_entries([])
    bad = tmp_path / "bad.json"
    bad.write_text('{"version": "9.9", "sub_domains": []}')
    monkeypatch.setenv(axiom.GRID_ENV, str(bad))
    axiom.load_methodology.cache_clear()
    with pytest.raises(axiom.MethodologyUnavailable):
        axiom.load_methodology()


def test_score_and_coverage():
    # grille fictive : pondération 5 (domaines 1-8, 20 sous-domaines) et 8 (domaine 9, 7 sous-domaines) = 156
    r = axiom.evaluate(_entries({"1.1": 2, "1.2": 1}, "Document"))
    assert r["score"] == round(100 * (2 * 5 + 1 * 5) / (4 * 10), 1)
    assert r["coverage"] == round(100 * 10 / 156, 1)
    assert r["evaluated"] == 2


def test_evidence_caps():
    assert axiom.evaluate(_entries({"1.1": 4}, "Entretien"))["details"][0]["retained"] == 2
    assert axiom.evaluate(_entries({"1.1": 4}, "Document"))["details"][0]["retained"] == 3
    assert axiom.evaluate(_entries({"1.1": 4}, "Vérifiée par l'évaluateur"))["details"][0]["retained"] == 4
    assert axiom.evaluate(axiom.parse_entries([{"id": "1.1", "level": 3}]))["details"][0]["retained"] == 0


def test_measured_evidence_required_for_agent_subdomains():
    r = axiom.evaluate(_entries({"9.4": 4}, "Vérifiée par l'évaluateur"))
    d = next(x for x in r["details"] if x["id"] == "9.4")
    assert d["retained"] == 2 and "mesure technique" in d["capped"]
    r = axiom.evaluate(_entries({"9.4": 4}, "Mesure technique"))
    assert next(x for x in r["details"] if x["id"] == "9.4")["retained"] == 4


def test_not_evaluated():
    assert axiom.evaluate(axiom.parse_entries([]))["score"] is None
    assert axiom.evaluate(_entries({"1.1": "N/A"}))["evaluated"] == 0


@pytest.mark.parametrize("bad", [
    [{"id": "99.1", "level": 2}],
    [{"id": "1.1", "level": 5}],
    [{"id": "1.1", "level": 1.3}],
    [{"id": "1.1", "level": True}],
    [{"id": "1.1", "level": "2"}],
    [{"id": "1.1", "level": 2, "evidence": "Intuition"}],
    [{"id": "1.1", "level": 2}, {"id": "1.1", "level": 3}],
    "pas une liste",
])
def test_invalid_entries(bad):
    with pytest.raises(axiom.ValidationError):
        axiom.parse_entries(bad)


@pytest.mark.skipif(not os.environ.get("AXIOM_REAL_GRID"), reason="vraie grille non fournie (confidentielle)")
def test_real_grid_matches_spreadsheet(monkeypatch):
    """Avec la vraie grille (AXIOM_REAL_GRID=chemin), le moteur retrouve l'onglet « Exemple Mon Marché »
    du classeur : 33,2 % sur 32,8 % de couverture."""
    monkeypatch.setenv(axiom.GRID_ENV, os.environ["AXIOM_REAL_GRID"])
    axiom.load_methodology.cache_clear()
    levels = {"1.1": 1, "1.2": 1.5, "1.3": 1.5, "2.2": 1.5, "3.1": 1, "4.1": 2.5, "7.3": 2, "8.1": 0, "8.2": 1}
    r = axiom.evaluate(_entries(levels))
    assert (r["score"], r["coverage"], r["evaluated"]) == (33.2, 32.8, 9)
