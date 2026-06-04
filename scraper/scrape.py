import json,csv,time,re
from datetime import datetime,timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

TARGET_COUNTIES={
    "Shelby":78,"Davidson":18,"Knox":46,"Hamilton":32,
    "Rutherford":74,"Montgomery":62,"Williamson":93,"Sullivan":81
}

OUTPUT_DIR=Path(__file__).parent.parent/"data"
OUTPUT_DIR.mkdir(exist_ok=True)
BASE_URL="https://foreclosurestn.com"

def parse_notice_text(text):
    data={
        "owner":"","trustee":"","beneficiary":"","original_loan_amount":"",
        "property_address":"","property_city":"","property_state":"TN",
        "property_zip":"","auction_date":"","auction_time":"",
        "auction_location":"","parcel_id":""
    }
    for pat in [
        r"executed by\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\s+to\s+|\s+dated|\s+herein)",
        r"(?:Grantor|Maker|Borrower)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|executed|granted)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["owner"]=m.group(1).strip().title()
            break
    for pat in [
        r"Property Address[:\s]+([^\n]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Hwy|Highway)[^\n]*)",
        r"(?:property located at|situated at|known as|being known as)[:\s]+(\d+[^\n,]+?(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Hwy|Highway)[^\n,]*)",
        r"((?:Believed to be[:\s]+)?(\d{3,5}\s+[A-Z][A-Za-z0-9\s]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Circle|Cir|Way|Blvd|Boulevard|Pike|Highway|Hwy))\.?)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            addr=m.group(1).strip()
            addr=re.sub(r'\s+Tax Parcel.*','',addr,flags=re.IGNORECASE).strip()
            addr=re.sub(r'\s+',' ',addr).strip()
            if re.match(r'^\d{3,5}\s+[A-Za-z]',addr):
                data["property_address"]=addr
            break
    for pat in [
        r"([A-Z][a-zA-Z\s]+),\s*(?:Tennessee|TN)[,\s]+(\d{5})",
        r"([A-Z][a-zA-Z ]+),\s*TN\s*(\d{5})",
    ]:
        m=re.search(pat,text)
        if m:
            data["property_city"]=m.group(1).strip()
            data["property_zip"]=m.group(2).strip()
            break
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
    m=re.search(r"(?:front door|north door|south door|courthouse)[^\n]*",text,re.IGNORECASE)
    if m:
        data["auction_location"]=m.group(0).strip()[:200]
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
    for pat in [
        r"(?:Substitute Trustee|substitute trustee)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at\s|\n)",
        r"Trustee[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|at\s|\n)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["trustee"]=m.group(1).strip()
            break
    for pat in [
        r"(?:requested by|for the benefit of|beneficiary)[:\s,]+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)",
        r"(?:in favor of|payable to)\s+([A-Z][A-Za-z\s,\.]+?)(?:,|\.|;|\n)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["beneficiary"]=m.group(1).strip()
            break
    for pat in [
        r"Tax Parcel\s+I\.?D\.?[:\s#]+([0-9\-\.A-Za-z:]+)",
        r"(?:Map|Parcel|Tax Map|Parcel ID|PIN)[:\s#]+([0-9\-\.A-Za-z]+)",
    ]:
        m=re.search(pat,text,re.IGNORECASE)
        if m:
            data["parcel_id"]=m.group(1).strip()
            break
    return data

def set_date_filter(page):
    page.evaluate("""
        var rb=document.getElementById('ctl00_ContentPlaceHolder1_as1_rbLastNumDays');
        if(rb){rb.checked=true;rb.dispatchEvent(new Event('change',{bubbles:true}));}
        var tb=document.getElementById('ctl00_ContentPlaceHolder1_as1_txtLastNumDays');
        if(tb){tb.value='7';}
    """)

def scrape_county(page,county,idx):
    cb_name="ctl00$ContentPlaceHolder1$as1$lstCounty$"+str(idx)
    btn_name="ctl00$ContentPlaceHolder1$as1$btnGo"
    all_records=[]

    try:
        page.goto(BASE_URL+"/Search.aspx",wait_until="domcontentloaded",timeout=30000)
        page.wait_for_load_state("networkidle",timeout=15000)
        set_date_filter(page)
        page.evaluate("__doPostBack('"+cb_name+"','')")
        page.wait_for_load_state("networkidle",timeout=20000)
        time.sleep(1.5)
        set_date_filter(page)
        time.sleep(0.5)
        btn=page.locator("input[name='"+btn_name+"']")
        if btn.count()>0:
            btn.first.evaluate("el=>el.click()")
        else:
            page.evaluate("__doPostBack('ctl00$ContentPlaceHolder1$as1$btnGo','')")
        page.wait_for_load_state("networkidle",timeout=20000)
        time.sleep(2)

        try:
            d1=page.locator("#ctl00_ContentPlaceHolder1_as1_lblDateFrom").text_content()
            d2=page.locator("#ctl00_ContentPlaceHolder1_as1_lblDateTo").text_content()
            print("    Date range: "+str(d1)+" to "+str(d2))
        except:
            pass

        page_num=1
        while True:
            view_buttons=page.locator("input.viewButton")
            count=view_buttons.count()
            if count==0:
                print("    ["+county+"] No VIEW buttons on page "+str(page_num))
                break

            print("    ["+county+"] page "+str(page_num)+" — "+str(count)+" notices")

            for i in range(count):
                try:
                    btns=page.locator("input.viewButton")
                    if i>=btns.count():
                        break
                    btns.nth(i).evaluate("el=>el.click()")
                    page.wait_for_load_state("networkidle",timeout=15000)
                    time.sleep(2)

                    body_text=page.locator("body").text_content() or ""
                    if "reCAPTCHA" in body_text or "not a robot" in body_text.lower():
                        print("    CAPTCHA - going back and retrying...")
                        page.go_back(wait_until="networkidle",timeout=15000)
                        time.sleep(4)
                        btns=page.locator("input.viewButton")
                        if i<btns.count():
                            btns.nth(i).evaluate("el=>el.click()")
                            page.wait_for_load_state("networkidle",timeout=15000)
                            time.sleep(3)
                            body_text=page.locator("body").text_content() or ""

                    if "reCAPTCHA" not in body_text and "not a robot" not in body_text.lower():
                        source_url=page.url
                        parsed=parse_notice_text(body_text)
                        parsed["source_url"]=source_url
                        parsed["county"]=county
                        parsed["scraped_date"]=datetime.now().strftime("%Y-%m-%d")
                        all_records.append(parsed)

                    page.go_back(wait_until="networkidle",timeout=15000)
                    time.sleep(2)

                except Exception as e:
                    print("    Notice error: "+str(e))
                    try:
                        page.go_back(wait_until="networkidle",timeout=10000)
                        time.sleep(1)
                    except:
                        pass

            print("    ["+county+"] page "+str(page_num)+" done, total: "+str(len(all_records)))

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
        print("    ["+county+"] ERROR: "+str(e))

    print("    ["+county+"] "+str(len(all_records))+" total records")
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
            viewport={"width":1280,"height":900},
            extra_http_headers={
                "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language":"en-US,en;q=0.9",
            }
        )
        context.set_default_timeout(20000)
        page=context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
            Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3]});
            Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
        """)
        try:
            page.goto(BASE_URL+"/",wait_until="domcontentloaded",timeout=30000)
            time.sleep(2)
            page.goto(BASE_URL+"/Search.aspx",wait_until="domcontentloaded",timeout=30000)
            page.wait_for_load_state("networkidle",timeout=15000)
            time.sleep(3)
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
    print("Saved — latest.json: "+str(len(merged))+" total records")
    return json_path,csv_path

if __name__=="__main__":
    results=scrape_all_notices(days_back=7)
    save_results(results)
