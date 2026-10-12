"""Pronunciation map from config/pronunciation.yaml, applied to text just before TTS.

For Kokoro, entries with `phonemes` become its inline override `[word](/ipa/)` and
entries with only `say` are respelled. Chatterbox-Turbo reads no phonemes, so for
it every entry is respelled from `say`. Matching is whole-word and case-insensitive:
"Tri", "tri" and "TRI" are all his name (Whisper and the model spell it every way).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    replacement: str


def load_rules(path: Path, phonemes: bool = True) -> list[Rule]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = []
    for word, entry in data.items():
        word = str(word)
        entry = entry or {}
        if phonemes and entry.get("phonemes"):
            # the override keeps the word as it was written
            replacement = f"[{{word}}](/{entry['phonemes']}/)"
        elif entry.get("say"):
            replacement = str(entry["say"])
        else:
            continue
        # not inside an existing [..](..) override, not part of a longer word
        pattern = re.compile(rf"(?<![\w\[]){re.escape(word)}(?![\w\]])", re.IGNORECASE)
        rules.append(Rule(pattern, replacement))
    return rules


def apply(text: str, rules: list[Rule]) -> str:
    for rule in rules:
        text = rule.pattern.sub(lambda m, r=rule.replacement: r.replace("{word}", m.group(0)), text)
    return text
