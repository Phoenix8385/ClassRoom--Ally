from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services import sign_mapper
from app.services.sign_mapper import SignAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signs", tags=["signs"])

_WORD_RE = re.compile(r"[A-Za-z0-9']+")

WORD_NOT_IN_GLOSSARY = "Word not in glossary, will fingerspell"


class CoverageResponse(BaseModel):
    total: int
    covered_by_clip: int
    covered_by_fingerspell: int
    not_covered: int
    coverage_pct: float
    unknown_words: list[str]
    words: list[str]


class GlossaryStatsResponse(BaseModel):
    total_words: int
    total_aliases: int
    with_clip: int
    clips_downloaded: int
    fingerspell_fallback: int
    by_category: dict[str, int]
    by_priority: dict[str, int]
    glossary_path: str


# Static paths are declared before /{word} so "coverage" and "glossary" are not
# swallowed by the catch-all path parameter.

@router.get("/coverage", response_model=CoverageResponse)
async def get_coverage(
    text: str = Query(..., description="Sentence or passage to score"),
) -> CoverageResponse:
    words = [m.group(0) for m in _WORD_RE.finditer(text)]
    return CoverageResponse(**sign_mapper.coverage(words), words=words)


@router.get("/glossary/stats", response_model=GlossaryStatsResponse)
async def get_glossary_stats() -> GlossaryStatsResponse:
    return GlossaryStatsResponse(**sign_mapper.stats())


@router.get("/{word}", response_model=SignAction)
async def get_sign(word: str) -> SignAction:
    result = await sign_mapper.map([word])
    action = result.actions[0] if result.actions else None

    if action is None or not action.found_in_glossary:
        logger.info("Sign lookup miss: %r", word)
        raise HTTPException(status_code=404, detail=WORD_NOT_IN_GLOSSARY)

    return action
