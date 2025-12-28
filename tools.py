# tools.py
import os
import re
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# pyairbnb is sync, so we will call it in a thread executor
import pyairbnb


@dataclass
class AirbnbTopResult:
    title: Optional[str]
    price_text: Optional[str]
    rating_text: Optional[str]
    reviews_text: Optional[str]
    link: Optional[str]
    debug: Dict[str, Any]


def _clean_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip()


def _absolute_airbnb(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return "https://www.airbnb.com" + url
    return "https://www.airbnb.com/" + url


# -------------------------
# 1) PLAYWRIGHT SCRAPER (your existing logic, just renamed)
# -------------------------
async def search_airbnb_top_result_playwright(
    where: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    pets: int = 0,
    headless: bool = True,
) -> AirbnbTopResult:
    debug: Dict[str, Any] = {}

    params = {"query": where, "checkin": check_in, "checkout": check_out, "adults": str(adults)}
    if children:
        params["children"] = str(children)
    if infants:
        params["infants"] = str(infants)
    if pets:
        params["pets"] = str(pets)

    search_url = f"https://www.airbnb.com/s/homes?{urlencode(params)}"
    debug["search_url"] = search_url

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await context.new_page()
        await page.goto(search_url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector("a[href*='/rooms/']", timeout=20000)
        except PlaywrightTimeoutError:
            await browser.close()
            return AirbnbTopResult(None, None, None, None, None, debug)

        card = page.locator("a[href*='/rooms/']").first
        link = await card.get_attribute("href")
        link = _absolute_airbnb(link)

        raw_text = await card.inner_text()
        debug["card_text_preview"] = (raw_text or "")[:500]
        debug["card_text_lines"] = [l.strip() for l in (raw_text or "").split("\n") if l.strip()][:15]

        text_block = raw_text or ""
        lines = [l.strip() for l in text_block.split("\n") if l.strip()]

        title = _clean_text(lines[0]) if lines else None
        price = rating = reviews = None

        if text_block:
            price_match = re.search(r"(\$|€|£)\s?\d+(?:,\d{3})*(?:\.\d{2})?", text_block)
            if price_match:
                price = price_match.group(0)

            rating_match = re.search(r"\b[0-5]\.\d{1,2}\b", text_block)
            if rating_match:
                rating = rating_match.group(0)

            reviews_match = re.search(r"\b\d{1,5}\+?\s+reviews\b", text_block, re.I)
            if reviews_match:
                reviews = reviews_match.group(0)

        await browser.close()

        return AirbnbTopResult(
            title=_clean_text(title),
            price_text=_clean_text(price),
            rating_text=_clean_text(rating),
            reviews_text=_clean_text(reviews),
            link=link,
            debug=debug,
        )


# -------------------------
# 2) PYAIRBNB SCRAPER
# -------------------------
def _pyairbnb_top_sync(
    where: str,
    check_in: str,
    check_out: str,
    adults: int,
    children: int,
    infants: int,
    pets: int,
) -> AirbnbTopResult:
    """
    pyairbnb calls are synchronous; we run this in a thread to avoid blocking FastAPI.
    """
    debug: Dict[str, Any] = {}

    # Build search URL similar to your Playwright one
    params = {"query": where, "checkin": check_in, "checkout": check_out, "adults": str(adults)}
    if children:
        params["children"] = str(children)
    if infants:
        params["infants"] = str(infants)
    if pets:
        params["pets"] = str(pets)

    search_url = f"https://www.airbnb.com/s/homes?{urlencode(params)}"
    debug["search_url"] = search_url

    try:
        dynamic_hash = pyairbnb.fetch_stays_search_hash()
        debug["stays_search_hash"] = dynamic_hash

        results = pyairbnb.search_all_from_url(
            search_url,
            currency="CAD",
            language="en",
            proxy_url="",
            hash=dynamic_hash,
        )
        debug["results_type"] = type(results).__name__

        # Try to pick first listing in a defensive way
        first = None
        if isinstance(results, list) and results:
            first = results[0]
        elif isinstance(results, dict):
            for k in ["results", "items", "data", "listings"]:
                v = results.get(k)
                if isinstance(v, list) and v:
                    first = v[0]
                    break

        if not first:
            return AirbnbTopResult(None, None, None, None, None, debug)

        # Try to find a URL/title/rating/reviews in common fields
        link = None
        title = None
        rating = None
        reviews = None
        price = None

        if isinstance(first, dict):
            # link
            for k in ["listing_url", "url", "room_url", "web_url", "link"]:
                v = first.get(k)
                if isinstance(v, str) and v.strip():
                    link = v.strip()
                    break
            if not link and isinstance(first.get("listing"), dict):
                for k in ["listing_url", "url", "room_url", "web_url"]:
                    v = first["listing"].get(k)
                    if isinstance(v, str) and v.strip():
                        link = v.strip()
                        break
            link = _absolute_airbnb(link)

            # title / rating / reviews (often nested under "listing")
            listing = first.get("listing") if isinstance(first.get("listing"), dict) else {}
            title = listing.get("name") or listing.get("title")

            # numbers might be int/float
            rating_val = listing.get("avg_rating") or listing.get("star_rating") or listing.get("rating")
            if rating_val is not None:
                rating = str(rating_val)

            reviews_val = listing.get("reviews_count") or listing.get("review_count") or listing.get("reviews")
            if reviews_val is not None:
                reviews = str(reviews_val)

            # pricing may be present in search results
            pq = first.get("pricing_quote") if isinstance(first.get("pricing_quote"), dict) else {}
            if pq:
                # sometimes nested
                rate = pq.get("rate") if isinstance(pq.get("rate"), dict) else {}
                price = (
                    pq.get("amount_formatted")
                    or pq.get("price")
                    or rate.get("amount_formatted")
                    or rate.get("amount")
                )
                if price is not None:
                    price = str(price)

        return AirbnbTopResult(
            title=_clean_text(title),
            price_text=_clean_text(price),
            rating_text=_clean_text(rating),
            reviews_text=_clean_text(reviews),
            link=link,
            debug=debug,
        )

    except Exception as e:
        debug["pyairbnb_error"] = repr(e)
        return AirbnbTopResult(None, None, None, None, None, debug)


async def search_airbnb_top_result_pyairbnb(
    where: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    pets: int = 0,
    headless: bool = True,  # kept for signature compatibility; unused here
) -> AirbnbTopResult:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        _pyairbnb_top_sync,
        where,
        check_in,
        check_out,
        adults,
        children,
        infants,
        pets,
    )


# -------------------------
# 3) ROUTER (this keeps main.py unchanged)
# -------------------------
async def search_airbnb_top_result(
    where: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    pets: int = 0,
    headless: bool = True,
) -> AirbnbTopResult:
    scraper = os.getenv("SCRAPER", "playwright").strip().lower()

    if scraper == "pyairbnb":
        return await search_airbnb_top_result_pyairbnb(
            where=where,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
            infants=infants,
            pets=pets,
            headless=headless,
        )

    # default: playwright
    return await search_airbnb_top_result_playwright(
        where=where,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        children=children,
        infants=infants,
        pets=pets,
        headless=headless,
    )

