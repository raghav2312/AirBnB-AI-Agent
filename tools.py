    # tools.py

import re
from dataclasses import dataclass
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


@dataclass
#class AirbnbtopResult returns the mentioned attributes of the top result
class AirbnbTopResult:
    title: Optional[str]
    price_text: Optional[str]
    rating_text: Optional[str]
    reviews_text: Optional[str]
    link: Optional[str]
    debug: Dict[str, Any]
    
    

#function _clean_text handles empty string and None values. And it also removes multiple places/newline characters along with leading or trailing white spaces
# For example: "  Cozy\n\nApartment   Downtown  "
#              → "Cozy Apartment Downtown"
def _clean_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip()



#Core tool, provides the input for airbnb search, mirroring the when, where, and who UI
#Most of the parameter values will be provided by the user, either manually or in a form of a nlp query
#The user query will then help us build the url, which search the airbnb website
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
    """
    Opens Airbnb search results via Playwright and returns the top listing.
    """

    debug: Dict[str, Any] = {}

    
    #entering the paramater values as provided by the user, inorder to build the search_url
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
    
    
    #building the airbnb search url
    search_url = f"https://www.airbnb.com/s/homes?{urlencode(params)}"
    
    #debugging the search url to check for any failures
    debug["search_url"] = search_url

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"] #Anti-bot detection mitigation
        )
        
        
        #context method is used for mimicing a real user, and ensures to use the english text
        #We're using await cuz we're waiting for the browser to respond
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await context.new_page() #Waits until HTML is loaded (not full JS execution — faster).
        await page.goto(search_url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector("a[href*='/rooms/']", timeout=20000) #Waits for listings to appear.
        except PlaywrightTimeoutError:
            await browser.close()
            return AirbnbTopResult(None, None, None, None, None, debug)

        card = page.locator("a[href*='/rooms/']").first #Grab the first listing, Airbnb sorts by relevance by default

        link = await card.get_attribute("href") #Fetches the url of the first listing
        
        
        #The following code converts the raw airbnb listing card into the structured data
        
        #Sometimes airbnb uses relative links, eg: /rooms/121212. So we'll have to convert them into absolute urls
        if link and not link.startswith("http"):
            link = f"https://www.airbnb.com{link}"
        
        
        
        raw_text = await card.inner_text()  #Fetches the visible text of the first listing
        
        debug["card_text_preview"] = raw_text[:500]
        debug["card_text_lines"] = [l.strip() for l in raw_text.split("\n") if l.strip()][:15]

        
        text_block = raw_text or ""
        lines = [l.strip() for l in text_block.split("\n") if l.strip()]

        title = _clean_text(lines[0]) if lines else None
        price = rating = reviews = None

        # Regex parse from the full text block (fallback extraction)
        #the if condition exists cuz we will only parse the text if it exists in the first place
        if text_block:
            price_match = re.search(r"(\$|€|£)\s?\d+(?:,\d{3})*(?:\.\d{2})?", text_block)  #\s?: optional space and \d+: one or more digits
            if price_match:
                price = price_match.group(0)

            rating_match = re.search(r"\b[0-5]\.\d{1,2}\b", text_block)  # broader #[34]: ratings are typically 3* or 4* and \.: Decimal point and \d{1,2}: 1-2 decimal points and \b: word boundary
            if rating_match:
                rating = rating_match.group(0)

            reviews_match = re.search(r"\b\d{1,5}\+?\s+reviews\b", text_block, re.I) #\d+: one or more numbers and \s+: one or more spaces and reviews: literal text and re.I: case insensitive
            if reviews_match:
                reviews = reviews_match.group(0)


        await browser.close()

        
        #returns the airbnb top result extracted info in a structured manner
        return AirbnbTopResult(
            title=_clean_text(title),
            price_text=_clean_text(price),
            rating_text=_clean_text(rating),
            reviews_text=_clean_text(reviews),
            link=link,
            debug=debug,
        )
