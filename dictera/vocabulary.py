"""Dictionnaire personnel (amorce de Whisper) et corrections automatiques par règles.

Tout reste local : les mots servent d'initial_prompt au modèle sur ce PC, les
corrections sont appliquées après la transcription. Les valeurs ci-dessous (spec § 6,
§ 9) pré-remplissent la base SQLite au premier lancement ; ensuite, la base fait foi
(Vocabulary.reload).
"""

import re
from dataclasses import dataclass, field

DEFAULT_WORDS = ["Claude Code", "skill", "prompt", "to-do"]
DEFAULT_CORRECTIONS = {"ski": "skill"}

# Whisper n'exploite que les ≈224 derniers jetons de l'amorce : on la garde courte.
MAX_PROMPT_CHARS = 600


@dataclass
class Vocabulary:
    words: list[str] = field(default_factory=lambda: list(DEFAULT_WORDS))
    corrections: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CORRECTIONS))

    def reload(self, words: list[str], corrections: dict[str, str]) -> None:
        """Remplace le contenu EN PLACE : les objets qui partagent ces listes (amorce de
        Whisper, termes protégés de la reformulation) voient aussitôt les changements."""
        self.words[:] = words
        self.corrections.clear()
        self.corrections.update(corrections)

    def initial_prompt(self) -> str | None:
        """Phrase d'amorce en français : Whisper suit mieux un texte naturel qu'une liste brute."""
        words = [w.strip() for w in self.words if w.strip()]
        if not words:
            return None
        prompt = "Vocabulaire : " + ", ".join(words) + "."
        return prompt[-MAX_PROMPT_CHARS:]

    def apply_corrections(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """Remplace chaque « entendu » par « à écrire », mot entier, sans tenir compte de la casse.

        Les expressions les plus longues passent d'abord (« claude cod » avant « cod »).
        Renvoie le texte corrigé et la liste des corrections effectivement appliquées.
        """
        applied: list[tuple[str, str]] = []
        for heard in sorted(self.corrections, key=len, reverse=True):
            target = self.corrections[heard]
            if not heard.strip():
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(heard.strip())}(?!\w)", re.IGNORECASE)
            text, n = pattern.subn(lambda _m, t=target: t, text)
            if n:
                applied.append((heard, target))
        return text, applied
