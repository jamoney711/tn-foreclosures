import json,csv,time,re
from datetime import datetime,timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

# 8 highest-volume TN counties with their exact checkbox indices from the live HTML
TARGET_COUNTIES={
    "Shelby":78,"Davidson":18,"Knox":46,"Hamilton":32,
    "Rutherford":74,"Montgomery":62,"Williamson":93,"Sullivan":81
}

OUTPUT_DIR=Path(__file__).parent.parent/"data"
OUTPUT_DIR.mkdir(exist_ok=True)
BASE_URL="https://foreclosurestn.com"

def parse_notice_text(text):
    """Parse all fields from notice body text."""
    data={
        "owner":"","trustee":"","beneficiary":"","original_loan_amount":"",
        "property_address":"","property_city":"","property_state":"TN",
        "property_zip":"","auction_date":"","auction_time":"",
        "auction_location":"","parcel_id":""
    }
    # Owner - person who executed deed of trust
    for pat in [
        r"executed by\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\s+to\s+|\s+dated|\s+herein)",
        r"(?:Grantor|Maker|Borrower)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|executed|granted)",
        r"^([A-Z][A-Z\s,\.]+),\s+(?:a single|a married|husband|wife)",
    ]:
        m=re.search(pat,text,re.IGNORECASE|re.MULTILINE)
        if m:
            data["owner"]=m.group(1).strip().title()
            break
    # Property address
    for pat in [
        r"Property Address[:\s]+([^\n]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Hwy|Highway)[^\n]*)",
        r"(?:property located at|situated at|known as|being known as)[:\s]+(\d+[^\n,]+?(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Hwy|Highway)[^\n,]*)",
        r"(\d{3,5}\s+[A-Z][A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Highway|Hwy)\.?)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            addr=m.group(1).strip()
            # Clean up trailing garbage
            addr=re.sub(r'\s+Tax Parcel.*','',addr,flags=re.IGNORECASE)
            data["property_address"]=addr
            break
    # City and zip
    for pat in [
        r"([A-Z][a-zA-Z\s]+),\s*(?:Tennessee|TN)[,\s]+(\d{5})",
        r"([A-Z][a-zA-Z ]+),\s*TN\s*(\d{5})",
    ]:
        m=re.search(pat,text)
        if m:
            data["property_city"]=m.group(1).strip()
            data["property_zip"]=m.group(2).strip()
            break
    # Auction date and time
    for pat in [
        r"(?:sale will be|sold on|auction on|sale date)[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4})(?:[,\s]+at\s+(\d{1,2}:\d{2}\s*[AaPp]\.?[Mm]\.?))?",
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})(?:[,\s]+at\s+(\d{1,2}:\d{2}\s*[AaPp]\.?[Mm]\.?))?",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["auction_date"]=m.group(1).strip()
            if m.lastindex and m.lastindex>=2 and m.group(2):
                data["auction_time"]=m.group(2).strip()
            break
    # Auction location
    for pat in [
        r"(?:front door|north door|south door|courthouse door|steps of)[^\n]*(?:Courthouse|Building)[^\n]*",
        r"(?:sale will be held at|auction at)[:\s]+([^\n]+)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["auction_location"]=m.group(0).strip()[:200]
            break
    # Original loan amount
    for pat in [
        r"(?:original principal|principal amount|indebtedness of)[:\s]*\$\s*([\d,]+(?:\.\d{2})?)",
        r"\$\s*([\d,]+(?:\.\d{2})?)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            amt=m.group(1).replace(",","")
            try:
                if 5000<float(amt)<50000000:
                    data["original_loan_amount"]=amt
                    break
            except:
                pass
    # Trustee
    for pat in [
        r"(?:Substitute Trustee|substitute trustee)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at\s|\n)",
        r"(?:^|\n)Trustee[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at\s|\n)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["trustee"]=m.group(1).strip()
            break
    # Beneficiary / lender
    for pat in [
        r"(?:requested by|for the benefit of|beneficiary)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)",
        r"(?:in favor of|payable to)\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["beneficiary"]=m.group(1).strip()
            break
    # Parcel ID
    for pat in [
        r"Tax Parcel\s+I\.?D\.?[:\s#]+([0-9\-\.A-Za-z:]+)",
        r"(?:Map|Parcel|Tax Map|Parcel ID|PIN)[:\s#]+([0-9\-\.A-Za-z]+)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["parcel_id"]=m.group(1).strip()
            break
    return data

def extract_detail_urls(html):
    """Pull Details.aspx URLs from onclick attributes in search results."""
    matches=re.findall(r"location\.href='(Details\.aspx\?SID=[^']+)'",html)
    urls=[]
    for m in matches:
        url=BASE_URL+"/"+m.replace("&amp;","&")
        if url not in urls:
            urls.append(url)
    return urls

def scrape_county(page,county,idx):
    """
    Scrape one county:
    1. Select county via __doPostBack
    2. Set date to last 7 days via DOM
    3. Click search button
    4. Paginate through results collecting URLs
    5. Visit each detail page for full notice text
    """
    cb_name="ctl00$ContentPlaceHolder1$as1$lstCounty$"+str(idx)
    btn_name="ctl00$ContentPlaceHolder1$as1$btnGo"
    all_records=[]
    seen_urls=set()

    try:
        page.goto(BASE_URL+"/Search.aspx",wait_until="domcontentloaded",timeout=30000)
        page.wait_for_load_state("networkidle",timeout=15000)

        # Set date filter to last 7 days BEFORE selecting county
        page.evaluate("""
            var rb=document.getElementById('ctl00_ContentPlaceHolder1_as1_rbLastNumDays');
            if(rb){rb.checked=true;}
            var tb=document.getElementById('ctl00_ContentPlaceHolder1_as1_txtLastNumDays');
            if(tb){tb.value='7';}
        """)

        # Select the county checkbox via postback (triggers server-side state update)
        page.evaluate("__doPostBack('"+cb_name+"','')")
        page.wait_for_load_state("networkidle",timeout=20000)
        time.sleep(1.5)

        # Re-apply date filter after postback (postback resets the form)
        page.evaluate("""
            var rb=document.getElementById('ctl00_ContentPlaceHolder1_as1_rbLastNumDays');
            if(rb){rb.checked=true;}
            var tb=document.getElementById('ctl00_ContentPlaceHolder1_as1_txtLastNumDays');
            if(tb){tb.value='7';}
        """)
        time.sleep(0.5)

        # Click search button
        btn=page.locator("input[name='"+btn_name+"']")
        if btn.count()>0:
            btn.first.evaluate("el=>el.click()")
        else:
            page.evaluate("__doPostBack('ctl00$ContentPlaceHolder1$as1$btnGo','')")
        page.wait_for_load_state("networkidle",timeout=20000)
        time.sleep(2)

        # Check date range shown on results page to confirm filter worked
        try:
            date_label=page.locator("#ctl00_ContentPlaceHolder1_as1_lblDateFrom").text_content()
            date_label_to=page.locator("#ctl00_ContentPlaceHolder1_as1_lblDateTo").text_content()
            print("    Date range: "+str(date_label)+" to "+str(date_label_to))
        except:
            pass

        # Collect all detail URLs across pages
        page_num=1
        while True:
            html=page.content()
            urls=extract_detail_urls(html)
            new_urls=[u for u in urls if u not in seen_urls]
            if not new_urls:
                print("    ["+county+"] page "+str(page_num)+" no new URLs, done")
                break
            for u in new_urls:
                seen_urls.add(u)
            print("    ["+county+"] page "+str(page_num)+" +"+str(len(new_urls))+" notices (total: "+str(len(seen_urls))+")")
            next_btn=page.locator("input[name*='btnNext']")
            if next_btn.count()==0:
                break
            next_btn.first.evaluate("el=>el.click()")
            page.wait_for_load_state("networkidle",timeout=15000)
            time.sleep(1.5)
            page_num+=1
            if page_num>30:
                break

    except Exception as e:
        print("    ["+county+"] Search error: "+str(e))

    print("    ["+county+"] Fetching "+str(len(seen_urls))+" detail pages...")

    # Visit each detail page for full notice text
    for url in list(seen_urls):
        try:
            page.goto(url,wait_until="domcontentloaded",timeout=20000)
            page.wait_for_load_state("networkidle",timeout=10000)
            # Check for CAPTCHA
            body_text=page.locator("body").text_content() or ""
            if "reCAPTCHA" in body_text or "not a robot" in body_text.lower():
                print("    CAPTCHA on detail page - skipping")
                continue
            parsed=parse_notice_text(body_text)
            parsed["source_url"]=url
            parsed["county"]=county
            parsed["scraped_date"]=datetime.now().strftime("%Y-%m-%d")
            all_records.append(parsed)
            time.sleep(0.5)
        except Exception as e:
            print("    Detail error: "+str(e))

    print("    ["+county+"] "+str(len(all_records))+" records collected")
    return all_records

def is_recent(date_str,days=7):
    if not date_str:
        return True
    try:
        d=datetime.strptime(date_str,"%B %d, %Y")
        return d>=datetime.now()-timedelta(days=days)
    except:
        return True

def scrape_all_notices(days_back=7):
    print("Scrape started - "+datetime.now().strftime("%Y-%m-%d %H:%M"))
    all_results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled"]
        )
        context=browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width":1280,"height":900}
        )
        context.set_default_timeout(20000)
        page=context.new_page()
        try:
            page.goto(BASE_URL+"/",wait_until="domcontentloaded",timeout=30000)
            time.sleep(2)
            print("Session ready\n")
        except Exception as e:
            print("Warmup: "+str(e))
        for i,(county,idx) in enumerate(TARGET_COUNTIES.items()):
            print("["+str(i+1)+"/8] "+county+"...")
            try:
                records=scrape_county(page,county,idx)
                records=[r for r in records if is_recent(r.get("auction_date",""),days_back)]
                all_results.extend(records)
                print("    -> "+str(len(records))+" within last "+str(days_back)+" days")
            except Exception as e:
                print("    COUNTY FAIL: "+str(e))
            time.sleep(2)
        browser.close()
    print("\nTotal: "+str(len(all_results))+" records")
    return all_results

def save_results(results,output_dir=OUTPUT_DIR):
    ts=datetime.now().strftime("%Y-%m-%d")
    json_path=output_dir/("foreclosures_"+ts+".json")
    with open(json_path,"w") as f:
        json.dump(results,f,indent=2)
    csv_path=output_dir/("foreclosures_"+ts+".csv")
    if results:
        fields=["county","owner","property_address","property_city","property_state",
                "property_zip","auction_date","auction_time","auction_location",
                "original_loan_amount","beneficiary","trustee","parcel_id",
                "scraped_date","source_url"]
        with open(csv_path,"w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
            w.writeheader()
            w.writerows(results)
    latest_path=output_dir/"latest.json"
    existing=[]
    if latest_path.exists():
        try:
            existing=json.load(open(latest_path))
        except:
            pass
    seen=set()
    merged=[]
    for r in existing+results:
        key=str(r.get("property_address",""))+"-"+str(r.get("auction_date",""))+"-"+str(r.get("owner",""))
        if key not in seen:
            seen.add(key)
            merged.append(r)
    cutoff=datetime.now()-timedelta(days=90)
    merged=[r for r in merged if datetime.strptime(r.get("scraped_date","2000-01-01"),"%Y-%m-%d")>cutoff]
    with open(latest_path,"w") as f:
        json.dump(merged,f,indent=2)
    print("Saved "+json_path.name+" — latest.json: "+str(len(merged))+" total records")
    return json_path,csv_path

if __name__=="__main__":
    results=scrape_all_notices(days_back=7)
    save_results(results)
