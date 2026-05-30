from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import spacy
from openai import AsyncOpenAI

from app.core import state
from app.core.config import settings

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# POS tags whose tokens are always dropped from ISL output
_DROP_POS: frozenset[str] = frozenset({"DET", "AUX", "CCONJ", "INTJ", "SPACE"})

# Specific words dropped regardless of POS ("to" covers both infinitive PART and prep ADP)
_DROP_WORDS: frozenset[str] = frozenset({"please", "to"})

_WH_WORDS: frozenset[str] = frozenset(
    {"what", "where", "when", "why", "how", "who", "whom", "whose", "which"}
)

# Maps English pronoun surface forms to their ISL gloss tokens
_PRONOUN_MAP: dict[str, str] = {
    "i": "I", "me": "I", "my": "I", "mine": "I", "myself": "I",
    "you": "YOU", "your": "YOUR", "yours": "YOUR", "yourself": "YOU",
    "he": "HE", "him": "HE", "his": "HIS",
    "she": "SHE", "her": "HER", "hers": "HER",
    "we": "WE", "us": "WE", "our": "OUR", "ours": "OUR",
    "they": "THEY", "them": "THEY", "their": "THEIR", "theirs": "THEIR",
}

_NUMBER_WORDS: dict[str, str] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
}

_nlp: spacy.Language | None = None


def _get_nlp() -> spacy.Language:
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            from spacy.cli import download  # type: ignore[import]
            download("en_core_web_sm")
            _nlp = spacy.load("en_core_web_sm")
    return _nlp


def _surface(token: spacy.tokens.Token) -> str:
    """Return the ISL gloss text for a single token (not yet uppercased)."""
    lower = token.lower_
    if lower in _PRONOUN_MAP:
        return _PRONOUN_MAP[lower]
    lemma = token.lemma_.lower().strip()
    if lemma in _NUMBER_WORDS:
        return _NUMBER_WORDS[lemma]
    if lower in _NUMBER_WORDS:
        return _NUMBER_WORDS[lower]
    # Proper nouns keep their surface form
    if token.pos_ == "PROPN":
        return token.text
    # -ics nouns (mathematics, physics) are uncountable; spaCy strips the 's' incorrectly
    if token.pos_ == "NOUN" and lower.endswith("ics"):
        return lower
    return lemma or lower


def _is_negation(token: spacy.tokens.Token) -> bool:
    return token.dep_ == "neg" or token.lower_ in {
        "not", "never", "n't", "cannot", "can't", "cant"
    }


def _should_drop(token: spacy.tokens.Token) -> bool:
    if token.is_punct or token.is_space:
        return True
    if token.lower_ in _DROP_WORDS:
        return True
    return token.pos_ in _DROP_POS


def _find_root_verb(doc: spacy.tokens.Doc) -> spacy.tokens.Token | None:
    """Return the ROOT token only when it is a content VERB (not AUX)."""
    for token in doc:
        if token.dep_ == "ROOT" and token.pos_ == "VERB":
            return token
    return None


def _collect_objects(
    root: spacy.tokens.Token, excluded: set[int]
) -> list[spacy.tokens.Token]:
    """Direct dobj/attr/xcomp of root, plus pobj of any prep child of root."""
    result: list[spacy.tokens.Token] = []
    for child in root.children:
        if child.dep_ in {"dobj", "attr", "xcomp"} and child.i not in excluded:
            result.append(child)
        elif child.dep_ in {"prep", "agent"}:
            for gc in child.children:
                if gc.dep_ == "pobj" and gc.i not in excluded:
                    result.append(gc)
    return result


def _apply_isl_rules(doc: spacy.tokens.Doc) -> list[str]:
    drop_ids: set[int] = set()
    neg_ids: set[int] = set()
    wh_ids: set[int] = set()

    # Negation is checked before drop so "cannot" isn't swallowed by AUX rule
    for token in doc:
        if _is_negation(token):
            neg_ids.add(token.i)
        elif _should_drop(token):
            drop_ids.add(token.i)
        elif token.lower_ in _WH_WORDS:
            wh_ids.add(token.i)

    root = _find_root_verb(doc)

    if root is not None:
        base_excluded = drop_ids | neg_ids | wh_ids
        subj_tokens = sorted(
            [
                t for t in doc
                if t.dep_ in {"nsubj", "nsubjpass"}
                and t.head.i == root.i
                and t.i not in base_excluded
            ],
            key=lambda t: t.i,
        )
        obj_tokens = sorted(
            _collect_objects(root, base_excluded | {t.i for t in subj_tokens}),
            key=lambda t: t.i,
        )
        subj_ids = {t.i for t in subj_tokens}
        obj_ids = {t.i for t in obj_tokens}
        handled = drop_ids | neg_ids | wh_ids | subj_ids | obj_ids | {root.i}

        subjects = [_surface(t).upper() for t in subj_tokens]
        objects = [_surface(t).upper() for t in obj_tokens]
        verb = _surface(root).upper()
        negs = ["NOT"] if neg_ids else []
        remaining = [_surface(t).upper() for t in doc if t.i not in handled]
        result = subjects + objects + [verb] + negs + remaining
    else:
        kept = [
            _surface(t).upper()
            for t in doc
            if t.i not in (drop_ids | neg_ids | wh_ids)
        ]
        negs = ["NOT"] if neg_ids else []
        result = kept + negs

    wh = [_surface(t).upper() for t in doc if t.i in wh_ids]
    result += wh

    return [tok for tok in result if tok.strip()]


class GlossService:
    def __init__(self) -> None:
        self._openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._prompt = (_PROMPTS_DIR / "gloss.txt").read_text(encoding="utf-8")

    async def convert(self, text: str) -> list[str]:
        key = "gloss:" + hashlib.sha256(text.encode()).hexdigest()

        try:
            cached = await state.redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception:
            logger.warning("Redis get failed for key=%s", key)

        nlp = _get_nlp()
        doc = nlp(text)
        tokens = _apply_isl_rules(doc)

        if len(tokens) < 2:
            tokens = await self._llm_fallback(text)

        try:
            await state.redis_client.setex(key, 86400, json.dumps(tokens))
        except Exception:
            logger.warning("Redis set failed for key=%s", key)

        return tokens

    async def _llm_fallback(self, text: str) -> list[str]:
        try:
            response = await self._openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self._prompt},
                    {"role": "user", "content": text},
                ],
                temperature=0,
            )
            raw = response.choices[0].message.content or ""
            tokens = [t.strip().upper() for t in raw.split() if t.strip()]
            return tokens if tokens else [text.upper()]
        except Exception:
            logger.exception("LLM fallback failed for: %s", text)
            return [text.upper()]
