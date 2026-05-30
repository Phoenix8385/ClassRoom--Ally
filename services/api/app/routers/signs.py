from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import sign_mapper
from app.services.sign_mapper import SignAction

router = APIRouter(prefix="/signs", tags=["signs"])


@router.get("/{word}", response_model=SignAction)
async def get_sign(word: str) -> SignAction:
    actions = sign_mapper.map([word])
    if not actions:
        raise HTTPException(status_code=404, detail="No action produced")
    return actions[0]
