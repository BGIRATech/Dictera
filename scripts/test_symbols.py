"""Symboles dictés à l'oral (reformulation par règles) : arobase, point, tiret…

Teste clean_rules seul, sans GPU ni micro : .venv\\Scripts\\python scripts\\test_symbols.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dictera.reformulate import clean_rules  # noqa: E402

CASES = [
    # Cas demandés
    ("Sophie arobase gmail point com", "sophie@gmail.com"),
    ("mon-site point fr", "mon-site.fr"),
    ("le point de départ", "Le point de départ."),  # « point » reste un mot (point final : règle des 4 mots)
    # Adresses
    ("écris à Jean point Dupont arobase Orange point fr", "Écris à jean.dupont@orange.fr"),
    ("contact at exemple point com", "contact@exemple.com"),
    ("va sur www point mon tiret site point fr slash contact", "Va sur www.mon-site.fr/contact"),
    ("Sophie@Gmail.com", "sophie@gmail.com"),
    # Symboles
    ("hashtag dictera", "#dictera"),
    ("jean tiret du bas dupont", "Jean_dupont"),
    ("dossier antislash Users", "Dossier\\Users"),
    ("la réponse point-virgule la suite", "La réponse ; la suite."),
    ("trois étoile deux", "Trois * deux"),
    ("une hausse de 50 pour cent cette année", "Une hausse de 50 % cette année."),
    ("et slash ou", "Et/ou"),
    # « point » en fin de phrase, et mots normaux préservés
    ("je suis d'accord avec toi point", "Je suis d'accord avec toi."),
    ("on a marqué un point", "On a marqué un point."),
    ("on a deux points d'avance", "On a deux points d'avance."),
    ("il coûte cent pour cent euros", "Il coûte cent pour cent euros."),
    ("au point mort, rien ne bouge", "Au point mort, rien ne bouge."),
    # Non-régression de la mise en forme existante
    ("Euh, bonjour, je teste euh la dictée", "Bonjour, je teste la dictée."),
]


def main() -> int:
    failures = 0
    for spoken, expected in CASES:
        got = clean_rules(spoken)
        ok = got == expected
        failures += not ok
        print(f"[{'OK' if ok else 'ÉCHEC'}] « {spoken} » -> « {got} »" + ("" if ok else f"   (attendu « {expected} »)"))
    print(f"{len(CASES) - failures}/{len(CASES)}", "SUCCÈS" if not failures else "ÉCHEC")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
