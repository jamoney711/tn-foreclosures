import json,csv,time,re
from datetime import datetime,timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
TARGET_COUNTIES={"Shelby":78,"Davidson":18,"Knox":46,"Hamilton":32,"Rutherford":74,"Montgomery":62,"Williamson":93,"Sullivan":81}
OUTPUT_DIR=Path(__file__).parent.parent/"data"
OUTPUT_DIR.mkdir(exist_ok=True)
BASE_URL="https://foreclosurestn.com"
def parse_notice_text(text):
    data={"owner":"","trustee":"","beneficiary":"","original_loan_amount":"","property_address":"","property_city":"","property_state":"TN","property_zip":"","auction_date":"","auction_time":"","auction_location":"","parcel_id":""}
    for pat in [r"executed by\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\s+to\s+|\s+dated|\s+herein)",r"(?:Grantor|Maker|Borrower)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|executed|granted)"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["owner"]=m.group(1).strip().title()
            break
    for pat in [r"(?:property located at|situated at|known as|being known as)[:\s]+(\d+[^\n,]+?(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Hwy|Highway)[^\n,]*)",r"(\d{3,5}\s+[A-Z][A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Highway|Hwy)\.?)"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["property_address"]=m.group(1).strip()
            break
    for pat in [r"([A-Z][a-zA-Z\s]+),\s*(?:Tennessee|TN)[,\s]+(\d{5})",r"([A-Z][a-zA-Z ]+),\s*TN\s*(\d{5})"]:
        m=re.search(pat,text)
        if m:
            data["property_city"]=m.group(1).strip()
            data["property_zip"]=m.group(2).strip()
            break
    for pat in [r"(?:sale date|auction date|will be sold on|sold on)[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4})",r"([A-Za-z]+\s+\d{1,2},\s+\d{4})(?:[,\s]+at\s+(\d{1,2}:\d{2}\s*[AaPp][Mm]))?"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["auction_date"]=m.group(1).strip()
            if m.lastindex and m.lastindex>=2 and m.group(2):
                data["auction_time"]=m.group(2).strip()
            break
    m=re.search(r"\$\s*([\d,]+(?:\.\d{2})?)",text)
    if m:
        data["original_loan_amount"]=m.group(1).replace(",","")
    for pat in [r"(?:Substitute Trustee|substitute trustee)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at\s)",r"Trustee[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at\s)"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["trustee"]=m.group(1).strip()
            break
    for pat in [r"(?:beneficiary|lender|mortgagee)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)",r"(?:in favor of|payable to)\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)"]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["beneficiary"]=m.group(1).strip()
            break
    m=re.search(r"(?:Map|Parcel|Tax Map|Parcel ID|PIN)[:\s#]+([0-9\-\.A-Za-z]+)",text,re.IGNORECASE)
    if m:
        data["parcel_id"]=m.group(1).strip()
    return data
def extract_detail_urls(html):
    matches=re.findall(r"location\.href='(Details\.aspx\?SID=[^']+)'",html)
    urls=[]
    for m in matches:
        url=BASE_URL+"/"+m.replace("&amp;","&")
        if url not in urls:
            urls.append(url)
    return urls
def scrape_county(page,county,idx):
    cb_name="ctl00$ContentPlaceHolder1$as1$lstCounty$"+str(idx)
    btn_name="ctl00$ContentPlaceHolder1$as1$btnGo"
    all_urls=[]
    try:
        page.goto(BASE_URL+"/Search.aspx",wait_until="domcontentloaded",timeout=30000)
        page.wait_for_load_state("networkidle",timeout=15000)
        page.evaluate("__doPostBack('"+cb_name+"','')")
        page.wait_for_load_state("networkidle",timeout=20000)
        time.sleep(1)
        btn=page.locator("input[name='"+btn_name+"']")
        if btn.count()>0:
            btn.first.evaluate("el=>el.click()")
        else:
            page.evaluate("__doPostBack('ctl00$ContentPlaceHolder1$as1$btnGo','')")
        page.wait_for_load_state("networkidle",timeout=20000)
        time.sleep(2)
        while True:
            html=page.content()
            urls=extract_detail_urls(html)
            for u in urls:
                if u not in all_urls:
                    all_urls.append(u)
            print("    ["+county+"] page has "+str(len(urls))+" notices, total so far: "+str(len(all_urls)))
            next_links=page.locator("a[href*='Page$Next'], a:has-text('>')")
            if next_links.count()==0:
                break
            next_links.first.click()
            page.wait_for_load_state("networkidle",timeout=15000)
            time.sleep(1.5)
            new_html=page.content()
            if new_html==html:
                break
    except Exception as e:
        print("    ["+county+"] ERROR: "+str(e))
    print("    ["+county+"] "+str(len(all_urls))+" total notices")
    results=[]
    for url in all_urls:
        try:
            page.goto(url,wait_until="domcontentloaded",timeout=20000)
            page.wait_for_load_state("networkidle",timeout=10000)
            text=page.locator("body").text_content() or ""
            parsed=parse_notice_text(text)
            parsed["source_url"]=url
            parsed["county"]=county
            parsed["scraped_date"]=datetime.now().strftime("%Y-%m-%d")
            results.append(parsed)
            time.sleep(0.4)
        except Exception as e:
            print("    Detail error: "+str(e))
    return results
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
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",viewport={"width":1280,"height":900})
        context.set_default_timeout(20000)
        page=context.new_page()
        try:
            page.goto(BASE_URL+"/",wait_until="domcontentloaded",timeout=30000)
            time.sleep(2)
            print("Session ready")
        except Exception as e:
            print("Warmup: "+str(e))
        for i,(county,idx) in enumerate(TARGET_COUNTIES.items()):
            print("["+str(i+1)+"/8] "+county+"...")
            try:
                records=scrape_county(page,county,idx)
                records=[r for r in records if is_recent(r.get("auction_date",""),days_back)]
                all_results.extend(records)
                print("    -> "+str(len(records))+" kept")
            except Exception as e:
                print("    FAIL: "+str(e))
            time.sleep(2)
        browser.close()
    print("Total: "+str(len(all_results)))
    return all_results
def save_results(results,output_dir=OUTPUT_DIR):
    ts=datetime.now().strftime("%Y-%m-%d")
    json_path=output_dir/("foreclosures_"+ts+".json")
    with open(json_path,"w") as f:
        json.dump(results,f,indent=2)
    csv_path=output_dir/("foreclosures_"+ts+".csv")
    if results:
        fields=["county","owner","property_address","property_city","property_state","property_zip","auction_date","auction_time","original_loan_amount","beneficiary","trustee","parcel_id","scraped_date","source_url"]
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
    print("Saved - latest.json: "+str(len(merged))+" records")
    return json_path,csv_path
if __name__=="__main__":
    results=scrape_all_notices(days_back=7)
    save_results(results)
