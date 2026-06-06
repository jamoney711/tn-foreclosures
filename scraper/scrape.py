"""
foreclosurestn.com scraper
Pulls all foreclosure notices from the last 7 days for every TN county.
Runs via GitHub Actions every Friday.
"""

import json
import csv
import time
import re
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# All 95 Tennessee counties
TN_COUNTIES = [
    "Anderson","Bedford","Benton","Bledsoe","Blount","Bradley","Campbell",
    "Cannon","Carroll","Carter","Cheatham","Chester","Claiborne","Clay",
    "Cocke","Coffee","Crockett","Cumberland","Davidson","Decatur","DeKalb",
    "Dickson","Dyer","Fayette","Fentress","Franklin","Gibson","Giles",
    "Grainger","Greene","Grundy","Hamblen","Hamilton","Hancock","Hardeman",
    "Hardin","Hawkins","Haywood","Henderson","Henry","Hickman","Houston",
    "Humphreys","Jackson","Jefferson","Johnson","Knox","Lake","Lauderdale",
    "Lawrence","Lewis","Lincoln","Loudon","Macon","Madison","Marion",
    "Marshall","Maury","McMinn","McNairy","Meigs","Monroe","Montgomery",
    "Moore","Morgan","Obion","Overton","Perry","Pickett","Polk","Putnam",
    "Rhea","Roane","Robertson","Rutherford","Scott","Sequatchie","Sevier",
    "Shelby","Smith","Stewart","Sullivan","Sumner","Tipton","Trousdale",
    "Unicoi","Union","Van Buren","Warren","Washington","Wayne","Weakley",
    "White","Williamson","Wilson"
]

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

def parse_notice_text(text):
    """Extract structured fields from raw foreclosure notice text."""
    data = {
        "raw_text": text,
        "owner": "",
        "trustee": "",
        "beneficiary": "",
        "original_loan_amount": "",
        "property_address": "",
        "property_city": "",
        "property_state": "TN",
        "property_zip": "",
        "auction_date": "",
        "auction_time": "",
        "auction_location": "",
        "substitute_trustee": "",
        "deed_book": "",
        "deed_page": "",
        "parcel_id": "",
    }

    # Owner / grantor of deed of trust
    owner_patterns = [
        r"(?:Grantor|Maker|Borrower|Owner)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|executed|granted|herein|did|and)",
        r"executed by\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\s+to\s+|\s+dated)",
        r"^([A-Z][A-Z\s,\.]+),\s+(?:a single|a married|husband|wife|as trustee)",
    ]
    for pat in owner_patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            data["owner"] = m.group(1).strip().title()
            break

    # Property address - look for street number + street name patterns
    addr_patterns = [
        r"(?:property located at|situated at|known as|described as)[:\s]+(\d+[^,\n]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Hwy|Highway)[^,\n]*)",
        r"(\d{3,5}\s+[A-Z][A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Highway|Hwy)\.?)",
    ]
    for pat in addr_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data["property_address"] = m.group(1).strip()
            break

    # City extraction
    city_patterns = [
        r"(?:City of|city of|,\s*)([A-Z][a-zA-Z\s]+),\s*(?:Tennessee|TN)\s*(\d{5})",
        r"([A-Z][a-zA-Z\s]+),\s*(?:Tennessee|TN)[,\s]+(\d{5})",
        r"([A-Z][a-zA-Z ]+),\s*TN\s*(\d{5})",
    ]
    for pat in city_patterns:
        m = re.search(pat, text)
        if m:
            data["property_city"] = m.group(1).strip()
            data["property_zip"] = m.group(2).strip()
            break

    # Auction date
    date_patterns = [
        r"(?:sale date|auction date|will be sold|sold on)[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        r"(?:on the \d+(?:st|nd|rd|th) day of [A-Za-z]+,\s+\d{4})",
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})(?:.*?(?:at|@)\s+(\d{1,2}:\d{2}\s*[AaPp][Mm]))?",
    ]
    for pat in date_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data["auction_date"] = m.group(1).strip() if m.lastindex >= 1 else ""
            if m.lastindex and m.lastindex >= 2 and m.group(2):
                data["auction_time"] = m.group(2).strip()
            break

    # Loan amount
    loan_patterns = [
        r"\$\s*([\d,]+(?:\.\d{2})?)",
        r"(?:original principal|principal amount|indebtedness)[:\s]+\$?\s*([\d,]+(?:\.\d{2})?)",
    ]
    for pat in loan_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data["original_loan_amount"] = m.group(1).replace(",", "")
            break

    # Trustee / Substitute Trustee
    trustee_patterns = [
        r"(?:Substitute Trustee|substitute trustee)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at|will)",
        r"(?:Trustee)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at|will)",
    ]
    for pat in trustee_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data["trustee"] = m.group(1).strip()
            break

    # Beneficiary / lender
    ben_patterns = [
        r"(?:beneficiary|lender|mortgagee|holder)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)",
        r"(?:in favor of|payable to)\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)",
    ]
    for pat in ben_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data["beneficiary"] = m.group(1).strip()
            break

    # Parcel ID / Map/Parcel
    parcel_patterns = [
        r"(?:Map|Parcel|Tax Map|Parcel ID|PIN)[:\s#]+([0-9\-\.A-Za-z]+)",
        r"(?:parcel number|tax parcel)[:\s]+([0-9\-\.]+)",
    ]
    for pat in parcel_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            data["parcel_id"] = m.group(1).strip()
            break

    return data


def scrape_county(page, county, date_from, date_to):
    """Scrape all foreclosure notices for a single county within date range."""
    results = []
    
    try:
        page.goto("https://foreclosurestn.com/Search.aspx", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        
        # Select county checkbox - the checkboxes use label text matching county name
        county_selectors = [
            f"label:has-text('{county}')",
            f"input[value='{county}']",
            f"//label[normalize-space(text())='{county}']",
        ]
        
        county_found = False
        for sel in county_selectors:
            try:
                if sel.startswith("//"):
                    el = page.locator(f"xpath={sel}").first
                else:
                    el = page.locator(sel).first
                if el.count() > 0:
                    el.click()
                    county_found = True
                    break
            except Exception:
                continue
        
        if not county_found:
            print(f"  [WARN] Could not find county checkbox for: {county}")
        
        # Set date range - look for date input fields
        date_inputs = page.query_selector_all("input[type='text'][id*='date'], input[type='text'][id*='Date'], input[id*='from'], input[id*='From']")
        
        # Try setting via visible date fields
        try:
            # Look for the "From" date field
            from_field = page.locator("input[id*='From'], input[id*='from'], input[placeholder*='from' i], input[placeholder*='start' i]").first
            if from_field.count() > 0:
                from_field.fill(date_from)
            
            to_field = page.locator("input[id*='To'], input[id*='to'], input[placeholder*='to' i], input[placeholder*='end' i]").first
            if to_field.count() > 0:
                to_field.fill(date_to)
        except Exception as e:
            print(f"  [WARN] Date field issue: {e}")

        # Click search button
        search_btn = page.locator("input[type='submit'][value*='Search' i], button:has-text('Search'), input[id*='btnSearch']").first
        if search_btn.count() > 0:
            search_btn.click()
        else:
            # Try __doPostBack
            page.evaluate("__doPostBack('ctl00$ContentPlaceHolder1$as1$btnSearch','')")
        
        page.wait_for_load_state("networkidle", timeout=20000)
        time.sleep(1)
        
        # Collect results - look for notice links/rows
        notices = page.query_selector_all("a[href*='NoticeDetail'], a[href*='notice'], .notice-result, .search-result, tr.result, div.result")
        
        if not notices:
            # Try generic approach - find all links that look like notice detail pages
            notices = page.query_selector_all("a[href*='detail' i], a[href*='Detail' i], a[href*='notice' i]")
        
        print(f"  [{county}] Found {len(notices)} notices")
        
        for notice in notices:
            try:
                href = notice.get_attribute("href")
                title = notice.text_content().strip()
                
                if href and not href.startswith("http"):
                    href = "https://foreclosurestn.com/" + href.lstrip("/")
                
                # Click into detail page
                with page.context.expect_page() as new_page_info:
                    notice.click()
                detail_page = new_page_info.value
                detail_page.wait_for_load_state("networkidle", timeout=15000)
                
                notice_text = detail_page.query_selector("body")
                if notice_text:
                    text = notice_text.text_content()
                    parsed = parse_notice_text(text)
                    parsed["county"] = county
                    parsed["source_url"] = detail_page.url
                    parsed["scraped_date"] = datetime.now().strftime("%Y-%m-%d")
                    results.append(parsed)
                
                detail_page.close()
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  [ERROR] Notice detail error: {e}")
                continue
        
        # Also try scraping inline results (no separate page)
        if not results:
            result_rows = page.query_selector_all(".result-row, .notice-row, tbody tr, .listing")
            for row in result_rows:
                text = row.text_content()
                if len(text.strip()) > 50:  # filter out header rows
                    parsed = parse_notice_text(text)
                    parsed["county"] = county
                    parsed["scraped_date"] = datetime.now().strftime("%Y-%m-%d")
                    results.append(parsed)
    
    except Exception as e:
        print(f"  [ERROR] County {county}: {e}")
    
    return results


def scrape_all_notices(days_back=7):
    """Main scrape function — iterates all TN counties."""
    date_to = datetime.now()
    date_from = date_to - timedelta(days=days_back)
    
    date_from_str = date_from.strftime("%m/%d/%Y")
    date_to_str = date_to.strftime("%m/%d/%Y")
    
    print(f"Scraping foreclosures from {date_from_str} to {date_to_str}")
    print(f"Targeting {len(TN_COUNTIES)} counties...")
    
    all_results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        # First visit - get session cookie
        try:
            page.goto("https://foreclosurestn.com/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            print("Session established")
        except Exception as e:
            print(f"Initial page load warning: {e}")
        
        for i, county in enumerate(TN_COUNTIES):
            print(f"[{i+1}/{len(TN_COUNTIES)}] Scraping {county} County...")
            county_results = scrape_county(page, county, date_from_str, date_to_str)
            all_results.extend(county_results)
            print(f"  -> {len(county_results)} records collected")
            time.sleep(1.5)  # polite delay between counties
        
        browser.close()
    
    print(f"\nTotal records scraped: {len(all_results)}")
    return all_results


def save_results(results, output_dir=OUTPUT_DIR):
    """Save results to JSON and CSV."""
    timestamp = datetime.now().strftime("%Y-%m-%d")
    
    # Save JSON (full data)
    json_path = output_dir / f"foreclosures_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved JSON: {json_path}")
    
    # Save CSV (flat export)
    csv_path = output_dir / f"foreclosures_{timestamp}.csv"
    if results:
        fieldnames = [
            "county", "owner", "property_address", "property_city",
            "property_state", "property_zip", "auction_date", "auction_time",
            "auction_location", "original_loan_amount", "beneficiary",
            "trustee", "parcel_id", "deed_book", "deed_page",
            "scraped_date", "source_url"
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
    print(f"Saved CSV: {csv_path}")
    
    # Update latest.json (always current, used by dashboard)
    latest_path = output_dir / "latest.json"
    
    # Merge with existing latest if it exists (rolling 30-day window)
    existing = []
    if latest_path.exists():
        with open(latest_path) as f:
            existing = json.load(f)
    
    # Deduplicate by address + auction_date
    seen = set()
    merged = []
    for r in existing + results:
        key = f"{r.get('property_address','')}-{r.get('auction_date','')}-{r.get('owner','')}"
        if key not in seen:
            seen.add(key)
            merged.append(r)
    
    # Keep only last 90 days in latest.json
    cutoff = datetime.now() - timedelta(days=90)
    merged = [r for r in merged if _parse_scraped_date(r.get("scraped_date","")) > cutoff]
    
    with open(latest_path, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"Updated latest.json: {len(merged)} total records")
    
    return json_path, csv_path


def _parse_scraped_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return datetime.now() - timedelta(days=200)


if __name__ == "__main__":
    results = scrape_all_notices(days_back=7)
    save_results(results)
    print("Done.")
