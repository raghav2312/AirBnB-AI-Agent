# main.py
# main.py (TOP of file, before other imports)
import sys
import asyncio

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


from typing import Optional

from fastapi import FastAPI, HTTPException

from config import HEADLESS_BROWSER
from schemas import AirbnbSearchRequest, AirbnbSearchResponse
from tools import search_airbnb_top_result
import traceback


app = FastAPI(
    title="Airbnb AI Agent (MVP)",
    version="0.1.0",
    description="Takes Where/When/Who and returns the top Airbnb search result via Playwright automation.",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/airbnb/top", response_model=AirbnbSearchResponse)
async def airbnb_top(req: AirbnbSearchRequest):
    """
    Input: where, check_in, check_out, guests
    Output: top listing info (best-effort)
    """
    try:
        result = await search_airbnb_top_result(
            where=req.where,
            check_in=req.check_in,
            check_out=req.check_out,
            adults=req.guests.adults,
            children=req.guests.children,
            infants=req.guests.infants,
            pets=req.guests.pets,
            headless=HEADLESS_BROWSER,
        )
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)  # shows full error in terminal
        raise HTTPException(status_code=500, detail=f"Search failed: {repr(e)}")

    # If Airbnb blocks or results don't load
    if not result.link and not result.title:
        raise HTTPException(
            status_code=404,
            detail="No listing found (possible no results, blocked, or page structure changed).",
        )

    return AirbnbSearchResponse(
        title=result.title,
        price=result.price_text,
        rating=result.rating_text,
        reviews=result.reviews_text,
        link=result.link,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
