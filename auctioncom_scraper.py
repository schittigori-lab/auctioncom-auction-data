# coding: utf-8
"""
Auction.com Scraper — Maryland Foreclosures
============================================
Scrapes Maryland foreclosure auction listings from auction.com.
Filters: MD residential, active, foreclosures conducted by Auction.com.

Requires login credentials in .env:
  AUCTIONCOM_EMAIL=your@email.com
  AUCTIONCOM_PASSWORD=yourpassword

OUTPUT: auctioncom_auctions.json
RUN:    py auctioncom_scraper.py
"""

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, date, timedelta

# ── Auto-install dependencies ──────────────────────────────────────────────────
def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

try:
    from playwright.async_api import async_playwright, Page
except ImportError:
    install("playwright")
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    from playwright.async_api import async_playwright, Page

try:
    from dotenv import load_dotenv
except ImportError:
    install("python-dotenv")
    from dotenv import load_dotenv

load_dotenv()

# ── MD City → County lookup (common cities) ───────────────────────────────────
CITY_COUNTY = {
    'fruitland': 'Wicomico', 'salisbury': 'Wicomico', 'ocean city': 'Worcester',
    'berlin': 'Worcester', 'snow hill': 'Worcester', 'princess anne': 'Somerset',
    'crisfield': 'Somerset', 'lusby': 'Calvert', 'prince frederick': 'Calvert',
    'chesapeake beach': 'Calvert', 'north beach': 'Calvert', 'dunkirk': 'Calvert',
    'st. mary city': "St. Mary's", 'lexington park': "St. Mary's", 'leonardtown': "St. Mary's",
    'california': "St. Mary's", 'accokeek': 'Prince George\'s', 'bowie': 'Prince George\'s',
    'upper marlboro': 'Prince George\'s', 'uppr marlboro': 'Prince George\'s',
    'hyattsville': 'Prince George\'s', 'college park': 'Prince George\'s',
    'laurel': 'Prince George\'s', 'oxon hill': 'Prince George\'s',
    'clinton': 'Prince George\'s', 'fort washington': 'Prince George\'s',
    'greenbelt': 'Prince George\'s', 'landover': 'Prince George\'s',
    'district heights': 'Prince George\'s', 'capitol heights': 'Prince George\'s',
    'rockville': 'Montgomery', 'gaithersburg': 'Montgomery', 'silver spring': 'Montgomery',
    'bethesda': 'Montgomery', 'potomac': 'Montgomery', 'germantown': 'Montgomery',
    'olney': 'Montgomery', 'takoma park': 'Montgomery', 'wheaton': 'Montgomery',
    'annapolis': 'Anne Arundel', 'glen burnie': 'Anne Arundel', 'pasadena': 'Anne Arundel',
    'severna park': 'Anne Arundel', 'millersville': 'Anne Arundel', 'odenton': 'Anne Arundel',
    'baltimore': 'Baltimore City', 'towson': 'Baltimore', 'catonsville': 'Baltimore',
    'dundalk': 'Baltimore', 'essex': 'Baltimore', 'parkville': 'Baltimore',
    'pikesville': 'Baltimore', 'owings mills': 'Baltimore', 'reisterstown': 'Baltimore',
    'hagerstown': 'Washington', 'frederick': 'Frederick', 'mount airy': 'Carroll',
    'westminster': 'Carroll', 'bel air': 'Harford', 'aberdeen': 'Harford',
    'havre de grace': 'Harford', 'edgewood': 'Harford', 'elkton': 'Cecil',
    'easton': 'Talbot', 'cambridge': 'Dorchester', 'denton': 'Caroline',
    'chestertown': 'Kent', 'centreville': 'Queen Anne\'s', 'new market': 'Frederick',
}

# ── MD County → Courthouse location ───────────────────────────────────────────
COUNTY_COURTHOUSE: dict[str, str] = {
    'Allegany':        'Allegany County Courthouse, Cumberland, MD',
    'Anne Arundel':    'Anne Arundel County Courthouse, Annapolis, MD',
    'Baltimore':       'Baltimore County Courthouse, Towson, MD',
    'Baltimore City':  'Baltimore City Courthouse, Baltimore, MD',
    'Calvert':         'Calvert County Courthouse, Prince Frederick, MD',
    'Caroline':        'Caroline County Courthouse, Denton, MD',
    'Carroll':         'Carroll County Courthouse, Westminster, MD',
    'Cecil':           'Cecil County Courthouse, Elkton, MD',
    'Charles':         'Charles County Courthouse, La Plata, MD',
    'Dorchester':      'Dorchester County Courthouse, Cambridge, MD',
    'Frederick':       'Frederick County Courthouse, Frederick, MD',
    'Garrett':         'Garrett County Courthouse, Oakland, MD',
    'Harford':         'Harford County Courthouse, Bel Air, MD',
    'Howard':          'Howard County Courthouse, Ellicott City, MD',
    'Kent':            'Kent County Courthouse, Chestertown, MD',
    'Montgomery':      'Montgomery County Courthouse, Rockville, MD',
    "Prince George's": "Prince George's County Courthouse, Upper Marlboro, MD",
    "Queen Anne's":    "Queen Anne's County Courthouse, Centreville, MD",
    'Somerset':        'Somerset County Courthouse, Princess Anne, MD',
    "St. Mary's":      "St. Mary's County Courthouse, Leonardtown, MD",
    'Talbot':          'Talbot County Courthouse, Easton, MD',
    'Washington':      'Washington County Courthouse, Hagerstown, MD',
    'Wicomico':        'Wicomico County Courthouse, Salisbury, MD',
    'Worcester':       'Worcester County Courthouse, Snow Hill, MD',
}

# ── Config ─────────────────────────────────────────────────────────────────────
EMAIL       = os.getenv('AUCTIONCOM_EMAIL', '')
PASSWORD    = os.getenv('AUCTIONCOM_PASSWORD', '')
SEARCH_URL  = 'https://www.auction.com/residential/MD/active_lt/auction_date_order,resi_sort_v2_st/y_nbs/foreclosures_at'
LOGIN_URL   = 'https://www.auction.com/login'
OUTPUT_FILE = 'auctioncom_auctions.json'
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

# ── Helpers ────────────────────────────────────────────────────────────────────

def clean(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip())

def parse_beds_baths_sqft(text: str):
    beds = baths = sqft = ''
    m = re.search(r'(\d+)\s*(?:bd|bed)', text, re.IGNORECASE)
    if m: beds = m.group(1)
    m = re.search(r'(\d+(?:\.\d)?)\s*(?:ba|bath)', text, re.IGNORECASE)
    if m: baths = m.group(1)
    m = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft)', text, re.IGNORECASE)
    if m: sqft = m.group(1).replace(',', '')
    return beds, baths, sqft

# ── Login ──────────────────────────────────────────────────────────────────────

async def login(page: Page) -> bool:
    print('Navigating to login page...')
    await page.goto(LOGIN_URL, wait_until='networkidle', timeout=30000)
    await page.wait_for_timeout(2000)

    # Check if already logged in (no login form present)
    email_input = await page.query_selector('input[type="email"], input[name="email"]')
    if not email_input:
        print('Already logged in.')
        return True

    print('Filling credentials...')
    try:
        await page.fill('input[type="email"], input[name="email"], input[id*="email"]', EMAIL)
        await page.fill('input[type="password"], input[name="password"], input[id*="password"]', PASSWORD)
        await page.wait_for_timeout(500)

        # Submit
        await page.click('button[type="submit"], input[type="submit"], button:has-text("Sign In"), button:has-text("Log In")')
        await page.wait_for_load_state('networkidle', timeout=20000)
        await page.wait_for_timeout(3000)

        # Check if login form is gone (successful login)
        email_still = await page.query_selector('input[type="email"], input[name="email"]')
        if email_still:
            print('Login may have failed — email input still visible')
            await page.screenshot(path='debug_login.png')
            return False

        print(f'Login successful — now at {page.url}')
        return True
    except Exception as e:
        print(f'Login error: {e}')
        await page.screenshot(path='debug_login.png')
        return False

# ── Extract listing data from a card ──────────────────────────────────────────

async def extract_listings(page: Page) -> list:
    await page.wait_for_timeout(2000)
    listings = []

    # Each property card is a link with /details/ in href.
    # The link element itself (link.parent in DOM) is the card container.
    links = await page.query_selector_all('a[href*="/details/"]')

    if not links:
        print('  No /details/ links found — dumping page for inspection')
        await page.screenshot(path='debug_results.png')
        with open('debug_results.html', 'w', encoding='utf-8') as f:
            f.write(await page.content())
        return listings

    print(f'  Found {len(links)} detail links')

    seen_ids = set()
    for link_el in links:
        try:
            href = await link_el.get_attribute('href') or ''
            if not href:
                continue
            if not href.startswith('http'):
                href = 'https://www.auction.com' + href

            # Property ID is the trailing number in the slug
            m = re.search(r'-(\d+)$', href.rstrip('/').split('?')[0])
            if not m:
                continue
            prop_id = m.group(1)
            if prop_id in seen_ids:
                continue
            seen_ids.add(prop_id)

            # Card text lives in the link's parent container
            card_el = await link_el.evaluate_handle('el => el.parentElement')
            text = clean(await card_el.as_element().inner_text())
            if not text or len(text) < 20:
                continue

            # Address: "NNN Street, City, MD ZZZZZ"
            # Card text has "N,NNN sq. ft. NNN Street..." — skip past sq. ft. if present
            full_address = ''
            m_addr = re.search(r'sq\.?\s*ft\.?\s+(\d{1,5}[A-Za-z]?\s+[^,]+,\s*[^,]+,\s*MD\s+\d{5})', text)
            if not m_addr:
                m_addr = re.search(r'(\d{1,5}[A-Za-z]?\s+[A-Z][^,]+,\s*[^,]+,\s*MD\s+\d{5})', text)
            if m_addr:
                full_address = clean(m_addr.group(1))

            # Beds / baths / sqft
            beds, baths, sqft = parse_beds_baths_sqft(text)

            # Auction date: "Starts in N days" → compute from today
            auction_date = ''
            m_days = re.search(r'Starts\s+in\s+(\d+)\s+day', text, re.IGNORECASE)
            if m_days:
                days_out = int(m_days.group(1))
                auction_date = (date.today() + timedelta(days=days_out)).isoformat()
            else:
                # Try explicit date string
                m_date = re.search(
                    r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}',
                    text, re.IGNORECASE
                )
                if m_date:
                    try:
                        parsed = datetime.strptime(re.sub(r',', '', m_date.group(0)), '%B %d %Y')
                        auction_date = parsed.strftime('%Y-%m-%d')
                    except:
                        pass

            # Opening bid (Est. Credit Bid takes priority over Est. Market Value)
            opening_bid = ''
            m_credit = re.search(r'\$([\d,]+)\s+Est\.?\s+Credit\s+Bid', text, re.IGNORECASE)
            m_market = re.search(r'\$([\d,]+)\s+Est\.?\s+Market\s+Value', text, re.IGNORECASE)
            if m_credit:
                opening_bid = '$' + m_credit.group(1)
            elif m_market:
                opening_bid = '$' + m_market.group(1)
            else:
                m_price = re.search(r'\$([\d,]+)', text)
                if m_price:
                    opening_bid = '$' + m_price.group(1)

            # County — derive from MD city lookup or address
            county = ''
            # Try extracting city from address for county mapping
            if full_address:
                m_city = re.search(r',\s*([^,]+),\s*MD', full_address)
                if m_city:
                    city = m_city.group(1).strip()
                    county = CITY_COUNTY.get(city.lower(), '')

            listings.append({
                'id':               f'auctioncom-{prop_id}',
                'property_address': full_address,
                'auction_date':     auction_date,
                'auction_time':     '10:00 AM',   # auction.com foreclosures typically 10am
                'auction_location': 'Auction.com Online',
                'opening_bid':      opening_bid,
                'bid_deposit':      '',
                'beds':             beds,
                'baths':            baths,
                'sqft':             sqft,
                'county':           county,
                'state':            'MD',
                'source':           'AUCTIONCOM',
                'status':           'active',
                'detail_url':       href,
            })
        except Exception as e:
            continue

    return listings

# ── County name normalization ──────────────────────────────────────────────────
COUNTY_NAME_MAP = {
    'PRINCE GEORGES': "Prince George's",
    "PRINCE GEORGE'S": "Prince George's",
    'SAINT MARYS': "St. Mary's",
    "ST. MARY'S": "St. Mary's",
    "SAINT MARY'S": "St. Mary's",
    "QUEEN ANNE'S": "Queen Anne's",
    'QUEEN ANNES': "Queen Anne's",
    'PRINCE GEORGE': "Prince George's",
}

def normalize_county(raw: str) -> str:
    raw = (raw or '').strip()
    upper = raw.upper().replace('`', "'")
    if upper in COUNTY_NAME_MAP:
        return COUNTY_NAME_MAP[upper]
    # Title-case without capitalizing after apostrophes
    parts = raw.split()
    return ' '.join(w.capitalize() for w in parts)


# ── Parse a single seek_listings_from_filters content item ────────────────────

def parse_gql_asset(item: dict) -> dict | None:
    """Convert a seek_listings_from_filters content item into a listing dict."""
    try:
        prop_id = str(item.get('listing_id', '') or '')
        if not prop_id:
            return None

        # Detail URL
        page_path = item.get('listing_page_path', '') or ''
        detail_url = f'https://www.auction.com{page_path}' if page_path else f'https://www.auction.com/details/{prop_id}'

        # Address from seller_property
        sp = item.get('seller_property') or {}
        street = sp.get('street_description', '').title()
        city   = sp.get('municipality', '').title()
        state  = sp.get('country_primary_subdivision', 'MD')
        zip_   = sp.get('postal_code', '')
        county = normalize_county(sp.get('country_secondary_subdivision', ''))
        full_address = f'{street}, {city}, {state} {zip_}'.strip(', ')

        # Fallback: use formatted_address
        if not street and item.get('formatted_address'):
            parts = item['formatted_address']
            full_address = ', '.join(p for p in parts if p)

        # Beds / baths / sqft
        pp = item.get('primary_property') or {}
        summary = pp.get('summary') or {}
        beds  = str(summary.get('total_bedrooms', '') or '')
        baths = str(summary.get('total_bathrooms', '') or '')
        sqft  = str(summary.get('square_footage', '') or '')
        # Don't show 0 for beds
        beds  = '' if beds == '0' else beds

        # Auction date / time — timestamps are UTC, convert to Eastern
        auction = item.get('auction') or {}
        start_ts = (auction.get('visible_auction_start_date_time') or
                    auction.get('start_date') or '')
        auction_date = auction_time = ''
        if start_ts:
            try:
                from datetime import timezone
                dt_utc = datetime.fromisoformat(start_ts.replace('Z', '+00:00'))
                # Maryland auctions — Eastern time (EDT=UTC-4, EST=UTC-5)
                # April–October: EDT (UTC-4); Nov–March: EST (UTC-5)
                month = dt_utc.month
                offset = timedelta(hours=-4 if 3 <= month <= 11 else -5)
                dt_et = dt_utc + offset
                auction_date = dt_et.strftime('%Y-%m-%d')
                h = dt_et.hour
                m = dt_et.minute
                auction_time = f'{h % 12 or 12}:{str(m).zfill(2)} {"AM" if h < 12 else "PM"}'
            except:
                auction_date = start_ts[:10]

        # Opening bid: prefer starting_bid, fall back to composite (Est. Market Value)
        opening_bid = ''
        starting_bid = auction.get('starting_bid')
        if starting_bid:
            opening_bid = f'${int(starting_bid):,}'
        else:
            # Use composite (est. market value) from external_information
            ei = item.get('external_information') or {}
            collateral = ei.get('collateral') or {}
            for entry in (collateral.get('summary') or []):
                if entry.get('type') == 'composite':
                    val = entry.get('estimated')
                    if val:
                        opening_bid = f'${int(val):,}'
                    break

        # Auction location — live trustee sale at county courthouse
        auction_location = COUNTY_COURTHOUSE.get(county, 'MD Courthouse (see listing)')

        return {
            'id':               f'auctioncom-{prop_id}',
            'property_address': full_address,
            'auction_date':     auction_date,
            'auction_time':     auction_time or '10:00 AM',
            'auction_location': auction_location,
            'opening_bid':      opening_bid,
            'bid_deposit':      '',
            'beds':             beds,
            'baths':            baths,
            'sqft':             sqft,
            'county':           county,
            'state':            state or 'MD',
            'source':           'AUCTIONCOM',
            'status':           'active',
            'detail_url':       detail_url,
        }
    except Exception:
        return None


# ── Intercept GraphQL API responses ───────────────────────────────────────────

async def scrape_all_listings(page) -> list:
    """Navigate to search URL, intercept GraphQL asset responses."""
    print(f'Loading search results: {SEARCH_URL}')

    collected: list[dict] = []
    seen_ids: set[str] = set()
    gql_responses: list[dict] = []

    async def handle_response(response):
        try:
            if 'graph.auction.com' in response.url and response.status == 200:
                ct = response.headers.get('content-type', '')
                if 'json' in ct:
                    body = await response.json()
                    gql_responses.append(body)
        except:
            pass

    page.on('response', handle_response)

    await page.goto(SEARCH_URL, wait_until='networkidle', timeout=45000)

    # Wait until seek_listings_from_filters is captured (up to 15s)
    for _ in range(15):
        await page.wait_for_timeout(1000)
        if any(_extract_assets_from_gql(r) for r in gql_responses):
            break

    page.remove_listener('response', handle_response)

    # Parse intercepted GraphQL responses
    print(f'  Intercepted {len(gql_responses)} GraphQL responses')
    for body in gql_responses:
        assets = _extract_assets_from_gql(body)
        for asset in assets:
            listing = parse_gql_asset(asset)
            if listing and listing['id'] not in seen_ids:
                seen_ids.add(listing['id'])
                collected.append(listing)

    print(f'  Parsed {len(collected)} listings from GraphQL')

    # Fallback: scrape DOM cards if GraphQL gave nothing
    if not collected:
        print('  GraphQL gave no results — falling back to DOM scrape')
        collected = await extract_listings(page)

    return collected


def _extract_assets_from_gql(body: dict) -> list:
    """Extract content items from seek_listings_from_filters response."""
    if not isinstance(body, dict):
        return []
    data = body.get('data', {})
    if not isinstance(data, dict):
        return []
    seek = data.get('seek_listings_from_filters')
    if isinstance(seek, dict):
        content = seek.get('content') or []
        if content:
            return content
    return []

# ── Save output ────────────────────────────────────────────────────────────────

def save_output(auctions: list):
    today = date.today().isoformat()
    payload = {
        'last_updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'auctions': auctions,
    }
    content = json.dumps(payload, indent=2, ensure_ascii=False)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'\nWrote {OUTPUT_FILE} ({len(auctions)} listings)')

    os.makedirs('archive', exist_ok=True)
    with open(f'archive/{today}.json', 'w', encoding='utf-8') as f:
        f.write(content)

    return content

# ── Push to GitHub via API ─────────────────────────────────────────────────────

def push_to_github(content: str):
    if not GITHUB_TOKEN:
        print('GitHub upload skipped — GITHUB_TOKEN not set')
        return

    import base64
    import urllib.request

    GITHUB_USERNAME = 'schittigori-lab'
    GITHUB_REPO     = 'auctioncom-auction-data'

    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Content-Type':  'application/json',
        'Accept':        'application/vnd.github+json',
    }

    def api(method, path, body=None):
        url = f'https://api.github.com{path}'
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())

    def upload(filename, file_content):
        path = f'/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{filename}'
        existing = api('GET', path)
        sha = existing.get('sha')
        body = {
            'message': f'Update {filename} [{datetime.now().strftime("%Y-%m-%d %H:%M")} UTC]',
            'content': base64.b64encode(file_content.encode()).decode(),
        }
        if sha:
            body['sha'] = sha
        result = api('PUT', path, body)
        if 'content' in result:
            print(f'  Uploaded {filename}')
        else:
            print(f'  Upload error for {filename}: {result.get("message")}')

    print('Pushing to GitHub...')
    upload(OUTPUT_FILE, content)

    today = date.today().isoformat()
    archive_path = f'archive/{today}.json'
    existing_archive = api('GET', f'/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{archive_path}')
    sha = existing_archive.get('sha')
    body = {
        'message': f'Archive {today}',
        'content': base64.b64encode(content.encode()).decode(),
    }
    if sha:
        body['sha'] = sha
    result = api('PUT', f'/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{archive_path}', body)
    if 'content' in result:
        print(f'  Uploaded {archive_path}')
    else:
        print(f'  Archive upload: {result.get("message")}')

# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    if not EMAIL or not PASSWORD:
        print('ERROR: AUCTIONCOM_EMAIL and AUCTIONCOM_PASSWORD must be set in .env')
        sys.exit(1)

    # Use headless=True in CI (no display), headless=False locally for debugging
    headless = os.getenv('CI', '') == 'true' or os.getenv('HEADLESS', '').lower() in ('1', 'true')

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        logged_in = await login(page)
        if not logged_in:
            print('Could not log in — aborting')
            await browser.close()
            return

        auctions = await scrape_all_listings(page)
        await browser.close()

    content = save_output(auctions)
    push_to_github(content)
    print('Done.')

if __name__ == '__main__':
    asyncio.run(main())
