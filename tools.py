# tools.py
import re
from dataclasses import dataclass
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


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


def _pick_title_from_lines(lines: list[str]) -> Optional[str]:
    """
    Airbnb cards often have "badge" lines first (e.g., "Guest favourite").
    This tries to select a more title-like line.
    """
    if not lines:
        return None

    skip_exact = {
        "guest favourite",
        "superhost",
        "new",
    }

    for l in lines:
        if not l:
            continue
        lc = l.strip().lower()

        # Skip badge-only or metadata lines
        if lc in skip_exact:
            continue
        if "reviews" in lc:
            continue
        if re.search(r"(\$|€|£)\s?\d", l):
            continue
        if re.fullmatch(r"[0-5]\.\d{1,2}", l.strip()):  # rating-only line
            continue

        # First remaining line is usually closer to a title / listing type
        return _clean_text(l)

    # Fallback: first line
    return _clean_text(lines[0])


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
    debug: Dict[str, Any] = {}

    # Build Airbnb search URL
    params = {
        "query": where,
        "checkin": check_in,
        "checkout": check_out,
        "adults": str(adults),
    }
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

        # First room link
        room_link = page.locator("a[href*='/rooms/']").first
        link = await room_link.get_attribute("href")
        link = _absolute_airbnb(link)

        # IMPORTANT: read text from the card container (not the <a>)
        card_container = room_link.locator("xpath=ancestor::*[self::div or self::li][1]")
        raw_text = await card_container.inner_text()

        debug["card_text_preview"] = (raw_text or "")[:500]
        debug["card_text_lines"] = [l.strip() for l in (raw_text or "").split("\n") if l.strip()][:15]

        text_block = raw_text or ""
        lines = [l.strip() for l in text_block.split("\n") if l.strip()]

        title = _pick_title_from_lines(lines)
        price = rating = reviews = None

        # Regex parse (best-effort)
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


