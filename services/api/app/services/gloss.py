"""English → Indian Sign Language (ISL) gloss conversion.

Four layers, tried in order, each one a fallback for the layer above:

    Redis cache  →  spaCy rule engine  →  GPT-4o-mini  →  raw uppercase words

The rule engine is the normal path: it tokenizes, lemmatizes content words,
drops function words, and reorders the clause to ISL's Subject-Object-Verb
shape with WH-words and negation pushed after the verb. The LLM is consulted
only when the rules produce almost nothing (fewer than `_MIN_TOKENS` tokens),
which in practice means a parse the grammar rules could not make sense of.

Nothing in this module raises: `convert()` degrades to word-by-word uppercase
tokens rather than failing, because a live caption stream must keep moving.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import spacy
from openai import AsyncOpenAI
from spacy.tokens import Doc, Token

from app.core import state
from app.core.config import settings

logger = logging.getLogger(__name__)

_SPACY_MODEL = "en_core_web_sm"
_PROMPT_PATH = Path(__file__).parents[1] / "prompts" / "gloss.txt"

_CACHE_PREFIX = "gloss:"
_CACHE_TTL_SECONDS = 86_400  # 24 hours

_LLM_MODEL = "gpt-4o-mini"
_LLM_TIMEOUT_SECONDS = 8.0

# Below this, the rule output is assumed to be a parse failure rather than a
# genuinely terse sentence, and the LLM is asked for a second opinion.
_MIN_TOKENS = 2

# How far to recurse into embedded clauses ("need to finish the homework").
_MAX_CLAUSE_DEPTH = 2

_WORD_RE = re.compile(r"[A-Za-z0-9']+")


# ── Lexicons ──────────────────────────────────────────────────────────────────

# POS tags whose tokens carry no ISL content. Negation and WH-words are matched
# *before* this set is consulted, so "not"/"n't" (PART) and "how" (SCONJ) survive.
_DROP_POS: frozenset[str] = frozenset(
    {"DET", "AUX", "CCONJ", "SCONJ", "INTJ", "PART", "SPACE"}
)

# Dropped whatever the tagger decides they are. "please" flips between INTJ and
# VERB depending on the sentence; ISL has no politeness particle either way.
_DROP_WORDS: frozenset[str] = frozenset({"please"})

_WH_WORDS: frozenset[str] = frozenset(
    {"what", "where", "when", "why", "how", "who", "whom", "whose", "which"}
)

# "How" is glossed as a unit with the degree word it modifies — HOW MANY, HOW
# OLD — so that partner travels to the end of the sentence with it.
_HOW_PARTNERS: frozenset[str] = frozenset(
    {"many", "much", "old", "long", "far", "often", "big", "tall"}
)

_NEGATION_WORDS: frozenset[str] = frozenset(
    {"not", "n't", "nt", "cannot", "can't", "cant", "never"}
)

# Time adverbs keep the position they were said in (ISL rule 9) instead of being
# pulled into the object slot, which would move them in front of the verb.
_TIME_WORDS: frozenset[str] = frozenset(
    {
        "today", "yesterday", "tomorrow", "now", "later", "tonight",
        "soon", "already", "then",
    }
)

# Pronoun surface form → ISL gloss, one entry per person. Subject, object and
# reflexive forms all collapse onto the person's base sign.
_PRONOUN_MAP: dict[str, str] = {
    "i": "I", "me": "I", "my": "I", "myself": "I",
    "you": "YOU", "your": "YOU", "yourself": "YOU", "yourselves": "YOU",
    "he": "HE", "him": "HE", "his": "HE", "himself": "HE",
    "she": "SHE", "her": "SHE", "herself": "SHE",
    "we": "WE", "us": "WE", "our": "WE", "ourselves": "WE",
    "they": "THEY", "them": "THEY", "their": "THEY", "themselves": "THEY",
    "it": "IT", "its": "IT", "itself": "IT",
}

# The same pronouns used possessively. "her" is the reason this cannot be one
# flat map: "I saw her" is SHE, "her book" is HER. A possessive keeps its own
# gloss because in a verbless clause it carries the predicate — "What is your
# name?" is YOUR NAME WHAT, not YOU NAME WHAT.
_POSSESSIVE_PRONOUN_MAP: dict[str, str] = {
    "my": "MY", "mine": "MY",
    "your": "YOUR", "yours": "YOUR",
    "his": "HIS",
    "her": "HER", "hers": "HER",
    "our": "OUR", "ours": "OUR",
    "their": "THEIR", "theirs": "THEIR",
    "its": "ITS",
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

# Dependency labels pulled along with the noun that heads a slot. Without this a
# numeral is stranded and surfaces after the verb: "I have three books" would
# gloss as I BOOK HAVE 3 instead of I BOOK 3 HAVE.
_PRE_MODIFIER_DEPS: frozenset[str] = frozenset({"amod", "compound"})
_POST_MODIFIER_DEPS: frozenset[str] = frozenset({"nummod"})

_SUBJECT_DEPS: frozenset[str] = frozenset({"nsubj", "nsubjpass"})
_OBJECT_DEPS: frozenset[str] = frozenset(
    {"dobj", "iobj", "dative", "attr", "xcomp", "oprd"}
)
_PREP_DEPS: frozenset[str] = frozenset({"prep", "agent"})


# ── spaCy model (loaded once, at import) ──────────────────────────────────────

def _load_nlp() -> spacy.Language | None:
    """Load the pipeline once. Returns None when the model is unavailable."""
    try:
        return spacy.load(_SPACY_MODEL)
    except Exception:
        logger.exception(
            "Could not load spaCy model %r — gloss conversion will fall back to the "
            "LLM. Install it with: python -m spacy download %s",
            _SPACY_MODEL,
            _SPACY_MODEL,
        )
        return None


_nlp: spacy.Language | None = _load_nlp()


def _get_nlp() -> spacy.Language | None:
    """The process-wide pipeline, retrying the load if the import-time one failed."""
    global _nlp
    if _nlp is None:
        _nlp = _load_nlp()
    return _nlp


# ── Token classification ──────────────────────────────────────────────────────

@lru_cache(maxsize=1024)
def _pronoun_gloss(word: str, possessive: bool = False) -> str | None:
    """ISL gloss for a pronoun surface form, or None if it is not a pronoun.

    `possessive` selects the possessive reading of an ambiguous form: "her" is
    SHE in "I saw her" and HER in "her book".
    """
    key = word.lower()
    if possessive:
        return _POSSESSIVE_PRONOUN_MAP.get(key) or _PRONOUN_MAP.get(key)
    # Forms that are only ever possessive (mine, yours, hers) have no base entry.
    return _PRONOUN_MAP.get(key) or _POSSESSIVE_PRONOUN_MAP.get(key)


@lru_cache(maxsize=1024)
def _number_gloss(word: str) -> str | None:
    """Digit string for a number word, or None if it is not one."""
    return _NUMBER_WORDS.get(word.lower())


def _is_wh(token: Token) -> bool:
    return token.lower_ in _WH_WORDS


def _is_negation(token: Token) -> bool:
    return token.dep_ == "neg" or token.lower_ in _NEGATION_WORDS


def _is_time_word(token: Token) -> bool:
    return token.lower_ in _TIME_WORDS or token.lemma_.lower() in _TIME_WORDS


def _should_drop(token: Token, *, has_root_verb: bool) -> bool:
    if token.is_punct or token.is_space:
        return True
    if token.lower_ in _DROP_WORDS:
        return True
    # Prepositions carry no sign; verb particles ("sit down") do.
    if token.pos_ == "ADP" and token.dep_ != "prt":
        return True
    # A possessive is redundant once a verb fixes the actor ("open your books" →
    # BOOK OPEN), but is the predicate itself in a verbless clause ("it is my
    # book" → IT MY BOOK), so it only goes when there is a verb to lean on.
    if token.dep_ == "poss" and token.pos_ == "PRON" and has_root_verb:
        return True
    return token.pos_ in _DROP_POS


def _gloss_token(token: Token, *, is_root: bool = False) -> str:
    """The ISL gloss for a single token, uppercased."""
    possessive = token.tag_ == "PRP$" or token.dep_ == "poss"
    pronoun = _pronoun_gloss(token.lower_, possessive)
    if pronoun is not None:
        return pronoun

    number = _number_gloss(token.lower_) or _number_gloss(token.lemma_)
    if number is not None:
        return number
    if token.like_num:
        return token.text.upper()

    # Proper nouns are names — lemmatizing them mangles the spelling.
    if token.pos_ == "PROPN":
        return token.text.upper()

    # A gerund outside the verb slot is a nominal ("I love LEARNING"); only the
    # clause's own verb is reduced to its lemma ("I am going" → GO).
    if token.tag_ == "VBG" and not is_root:
        return token.text.upper()

    # -ics nouns (mathematics, physics) are uncountable; the lemmatizer reads the
    # "s" as a plural and strips it.
    if token.pos_ == "NOUN" and token.lower_.endswith("ics"):
        return token.lower_.upper()

    lemma = token.lemma_.strip()
    return (lemma or token.text).upper()


def _negation_gloss(token: Token) -> str:
    """NEVER has its own sign; every other negator collapses to NOT."""
    return "NEVER" if token.lower_ == "never" else "NOT"


# ── Clause structure ──────────────────────────────────────────────────────────

def _find_root_verb(doc: Doc) -> Token | None:
    """The ROOT token, but only when it is a content verb rather than a copula."""
    for token in doc:
        if token.dep_ == "ROOT" and token.pos_ == "VERB":
            return token
    return None


def _how_partner(token: Token) -> Token | None:
    """The degree word "how" modifies, e.g. the "many" of "how many"."""
    if token.lower_ != "how":
        return None
    head = token.head
    if head is not token and head.lower_ in _HOW_PARTNERS:
        return head
    return None


def _slot_tokens(head: Token, excluded: set[int]) -> list[Token]:
    """A head noun plus its modifiers, ordered the way ISL signs them.

    Adjectives and compounds stay in front of the noun; numerals follow it
    (BOOK 3), which is where a signer puts a count.
    """
    pre = sorted(
        (c for c in head.children if c.dep_ in _PRE_MODIFIER_DEPS and c.i not in excluded),
        key=lambda t: t.i,
    )
    post = sorted(
        (c for c in head.children if c.dep_ in _POST_MODIFIER_DEPS and c.i not in excluded),
        key=lambda t: t.i,
    )
    return pre + [head] + post


def _collect_subjects(root: Token, excluded: set[int]) -> list[Token]:
    return sorted(
        (t for t in root.children if t.dep_ in _SUBJECT_DEPS and t.i not in excluded),
        key=lambda t: t.i,
    )


def _collect_objects(root: Token, excluded: set[int]) -> list[Token]:
    """Objects and complements of root, plus the object of any preposition.

    Time words are deliberately left behind: they belong where they were said,
    not hoisted in front of the verb.
    """
    found: list[Token] = []
    for child in root.children:
        # A preposition is itself dropped, so only its object is checked here.
        if child.dep_ in _PREP_DEPS:
            found.extend(
                gc for gc in child.children
                if gc.dep_ == "pobj" and gc.i not in excluded and not _is_time_word(gc)
            )
        elif child.dep_ in _OBJECT_DEPS and child.i not in excluded and not _is_time_word(child):
            found.append(child)
    return sorted(found, key=lambda t: t.i)


def _expand_object(head: Token, excluded: set[int], depth: int = 0) -> list[Token]:
    """Tokens filling one object slot, unpacking an embedded clause if that is what it is.

    "We need to finish the homework" hangs "homework" off "finish", not off the
    root — left alone it would strand after the verb. Recursing gives the
    embedded clause the same object-then-verb shape: HOMEWORK FINISH NEED.
    """
    if head.pos_ != "VERB" or depth >= _MAX_CLAUSE_DEPTH:
        return _slot_tokens(head, excluded)

    inner: list[Token] = []
    seen = excluded | {head.i}
    for sub in _collect_objects(head, seen):
        for token in _expand_object(sub, seen, depth + 1):
            if token.i not in seen:
                inner.append(token)
                seen.add(token.i)
    return inner + [head]


def _dedupe(tokens: list[str]) -> list[str]:
    """Drop blanks and repeats, keeping first-occurrence order."""
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        cleaned = token.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _apply_isl_rules(doc: Doc) -> list[str]:
    """Reorder one parsed sentence into ISL gloss tokens."""
    root = _find_root_verb(doc)
    has_root_verb = root is not None

    wh_ids: list[int] = []      # ordered: each WH word followed by its partner
    neg_ids: list[int] = []
    drop_ids: set[int] = set()

    # WH before negation before drop: "how" is tagged SCONJ and "not" PART, and
    # both of those tags are otherwise discarded.
    for token in doc:
        if _is_wh(token):
            wh_ids.append(token.i)
            partner = _how_partner(token)
            if partner is not None and partner.i not in wh_ids:
                wh_ids.append(partner.i)
        elif _is_negation(token):
            neg_ids.append(token.i)
        elif _should_drop(token, has_root_verb=has_root_verb):
            drop_ids.add(token.i)

    reserved = drop_ids | set(wh_ids) | set(neg_ids)
    negations = [_negation_gloss(doc[i]) for i in neg_ids]

    if root is not None:
        subject_heads = _collect_subjects(root, reserved)
        subject_tokens = [t for h in subject_heads for t in _slot_tokens(h, reserved)]

        taken = reserved | {t.i for t in subject_tokens} | {root.i}
        object_heads = _collect_objects(root, taken)
        object_tokens = [t for h in object_heads for t in _expand_object(h, taken)]

        handled = taken | {t.i for t in object_tokens}

        # Whatever the grammar did not claim — adverbs, time words — trails the
        # verb in the order it was spoken.
        trailing = [
            _gloss_token(t) for t in doc
            if t.i not in handled and not _should_drop(t, has_root_verb=True)
        ]

        result = (
            [_gloss_token(t) for t in subject_tokens]
            + [_gloss_token(t) for t in object_tokens]
            + [_gloss_token(root, is_root=True)]
            + negations
            + trailing
        )
    else:
        # No content verb (copular or verbless): keep spoken order, drop the
        # function words, and let negation and WH move to the end.
        result = [_gloss_token(t) for t in doc if t.i not in reserved] + negations

    result += [_gloss_token(doc[i]) for i in wh_ids]
    return _dedupe(result)


# ── Rule pipeline ─────────────────────────────────────────────────────────────

def gloss_sync(sentence: str) -> list[str]:
    """Run the spaCy rule engine. Raises if the model is missing or parsing fails."""
    nlp = _get_nlp()
    if nlp is None:
        raise RuntimeError(f"spaCy model {_SPACY_MODEL!r} is not available")
    return _apply_isl_rules(nlp(sentence))


def _fallback_tokens(sentence: str) -> list[str]:
    """Last resort: the sentence's own words, uppercased and stripped of punctuation."""
    return _dedupe([m.group(0).upper() for m in _WORD_RE.finditer(sentence)])


# ── LLM fallback ──────────────────────────────────────────────────────────────

_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


@lru_cache(maxsize=1)
def _load_prompt() -> str:
    """The few-shot system prompt, read once from app/prompts/gloss.txt."""
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Could not read gloss prompt from %s — using a minimal prompt", _PROMPT_PATH)
        return (
            "Convert the English sentence into Indian Sign Language gloss: "
            "uppercase tokens, Subject-Object-Verb order, no articles or auxiliaries, "
            "WH-words and negation last. Output only the tokens."
        )


def _parse_llm_response(raw: str) -> list[str]:
    """Uppercase space-separated tokens, ignoring any prose the model wrapped them in."""
    # Models occasionally answer "Output: I WATER WANT" despite the instruction.
    text = raw.strip().rsplit(":", 1)[-1] if raw.strip().lower().startswith("output") else raw
    return _dedupe([m.group(0).upper() for m in _WORD_RE.finditer(text)])


async def _llm_gloss(sentence: str) -> list[str]:
    """Ask GPT-4o-mini for the gloss. Raises on API failure or an empty answer."""
    response = await asyncio.wait_for(
        _get_openai_client().chat.completions.create(
            model=_LLM_MODEL,
            messages=[
                {"role": "system", "content": _load_prompt()},
                {"role": "user", "content": sentence},
            ],
            temperature=0,
            max_tokens=64,
        ),
        timeout=_LLM_TIMEOUT_SECONDS,
    )
    tokens = _parse_llm_response(response.choices[0].message.content or "")
    if not tokens:
        raise ValueError("LLM returned no usable gloss tokens")
    return tokens


# ── Redis cache ───────────────────────────────────────────────────────────────

def _cache_key(sentence: str) -> str:
    digest = hashlib.sha256(sentence.lower().strip().encode("utf-8")).hexdigest()
    return _CACHE_PREFIX + digest


async def _cache_get(key: str) -> list[str] | None:
    """Cached gloss for a key, or None on a miss or any Redis trouble."""
    try:
        raw = await state.redis_client.get(key)
    except Exception:
        logger.warning("Redis lookup failed for %s — continuing uncached", key, exc_info=True)
        return None

    if not raw:
        return None
    try:
        cached = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Discarding malformed cache entry for %s", key)
        return None
    if isinstance(cached, list) and all(isinstance(t, str) for t in cached):
        return cached
    logger.warning("Discarding cache entry of unexpected shape for %s", key)
    return None


async def _cache_set(key: str, tokens: list[str]) -> None:
    try:
        await state.redis_client.setex(key, _CACHE_TTL_SECONDS, json.dumps(tokens))
    except Exception:
        logger.warning("Redis write failed for %s — result not cached", key, exc_info=True)


# ── Public API ────────────────────────────────────────────────────────────────

async def convert(sentence: str) -> list[str]:
    """Convert an English sentence to ISL gloss tokens.

    Returns `[]` for empty, blank or non-string input. Never raises: if every
    layer fails the sentence's own words come back uppercased.
    """
    if not isinstance(sentence, str):
        return []
    text = sentence.strip()
    if not text:
        return []

    key = _cache_key(text)
    cached = await _cache_get(key)
    if cached is not None:
        return cached

    tokens: list[str] = []
    try:
        # spaCy is CPU-bound; off the event loop so a websocket keeps streaming.
        tokens = await asyncio.to_thread(gloss_sync, text)
    except Exception:
        logger.exception("Rule-based gloss failed, falling back to the LLM: %r", text)

    if len(tokens) < _MIN_TOKENS:
        logger.info(
            "Gloss rules produced %d token(s) — using the %s fallback for: %r",
            len(tokens),
            _LLM_MODEL,
            text,
        )
        try:
            tokens = await _llm_gloss(text)
        except Exception:
            logger.exception("LLM gloss fallback failed for: %r", text)
            tokens = tokens or _fallback_tokens(text)

    if tokens:
        await _cache_set(key, tokens)
    return tokens


class GlossService:
    """Object wrapper kept for the websocket pipeline's dependency injection."""

    async def convert(self, text: str) -> list[str]:
        return await convert(text)
