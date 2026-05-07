"""
jobs.ge სრული სკრეიფერი - ყველა ვაკანსია
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import logging
from datetime import datetime
from typing import Optional
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://jobs.ge"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "ka-GE,ka;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DB_PATH = "jobs.db"
DELAY = 1.0


def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          INTEGER PRIMARY KEY,
            title       TEXT,
            company     TEXT,
            category    TEXT,
            location    TEXT,
            salary      INTEGER DEFAULT 0,
            vip         INTEGER DEFAULT 0,
            posted      TEXT,
            deadline    TEXT,
            url         TEXT,
            is_new      INTEGER DEFAULT 0,
            scraped_at  TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scrape_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            ended_at   TEXT,
            total      INTEGER,
            status     TEXT
        )
    """)
    con.commit()
    con.close()
    log.info("DB initialized ✓")


def fetch_page(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.warning(f"Attempt {attempt+1} failed for {url}: {e}")
            time.sleep(3 * (attempt + 1))
    return None


def get_total_pages(soup: BeautifulSoup) -> int:
    """ბოლო გვერდის ნომრის ამოღება — რამდენიმე სტრატეგია"""
    try:
        # სტრატეგია 1: pagination ლინკებიდან მაქსიმუმი
        nums = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            m = re.search(r"[?&]page=(\d+)", href)
            if m:
                nums.append(int(m.group(1)))

        if nums:
            total = max(nums)
            log.info(f"Total pages from pagination links: {total}")
            return total

        # სტრატეგია 2: "გვერდი X / Y" ტექსტი
        for el in soup.find_all(string=re.compile(r"\d+\s*/\s*\d+")):
            m = re.search(r"(\d+)\s*/\s*(\d+)", el)
            if m:
                return int(m.group(2))

        # სტრატეგია 3: jobs რაოდენობიდან გამოთვლა
        total_text = soup.find(string=re.compile(r"სულ.*?(\d+)"))
        if total_text:
            m = re.search(r"(\d+)", total_text)
            if m:
                total_jobs = int(m.group(1))
                return max(1, (total_jobs + 19) // 20)

    except Exception as e:
        log.warning(f"Could not get total pages: {e}")

    return 1


def parse_jobs_from_soup(soup: BeautifulSoup) -> list[dict]:
    """soup-იდან ყველა ვაკანსიის ამოღება"""
    jobs = []

    # ყველა row რომელსაც view=jobs ბმული აქვს
    rows = [tr for tr in soup.find_all("tr") if tr.find("a", href=re.compile(r"view=jobs"))]

    for row in rows:
        try:
            link = row.find("a", href=re.compile(r"view=jobs"))
            if not link:
                continue

            href = link.get("href", "")
            m = re.search(r"id=(\d+)", href)
            if not m:
                continue

            job_id = int(m.group(1))
            title = link.get_text(strip=True)
            if not title:
                continue

            # URL
            if href.startswith("http"):
                url = href
            elif href.startswith("?"):
                url = f"{BASE_URL}/ge/{href}"
            else:
                url = f"{BASE_URL}{href}"

            # ყველა td
            tds = row.find_all("td")
            td_texts = [td.get_text(strip=True) for td in tds]

            # კომპანია — მეორე ბმული ან td
            company = ""
            links = row.find_all("a", href=True)
            for lnk in links:
                if "company" in lnk.get("href", "") or "employer" in lnk.get("href", ""):
                    company = lnk.get_text(strip=True)
                    break
            if not company and len(td_texts) > 1:
                company = td_texts[1] if td_texts[1] != title else ""

            # კატეგორია
            category = ""
            for lnk in links:
                if "cid=" in lnk.get("href", "") or "category" in lnk.get("href", ""):
                    category = lnk.get_text(strip=True)
                    break

            # ლოკაცია
            location = ""
            for lnk in links:
                if "lid=" in lnk.get("href", "") or "location" in lnk.get("href", ""):
                    location = lnk.get_text(strip=True)
                    break

            # თარიღები — ბოლო ორი td-დან
            posted = ""
            deadline = ""
            date_pattern = re.compile(r"\d{1,2}[\s\-/]\w+|\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2}")
            date_tds = [t for t in td_texts if date_pattern.search(t)]
            if len(date_tds) >= 2:
                posted = date_tds[0]
                deadline = date_tds[1]
            elif len(date_tds) == 1:
                deadline = date_tds[0]

            # VIP
            vip = 1 if row.find(class_=re.compile(r"vip", re.I)) or \
                       row.find("img", src=re.compile(r"vip", re.I)) or \
                       "vip" in row.get("class", []) else 0

            # ხელფასი
            salary = 1 if row.find(class_=re.compile(r"salary|wage", re.I)) or \
                          row.find("img", src=re.compile(r"salary|lari", re.I)) else 0

            # is_new — დღეს გამოქვეყნებული
            today = datetime.now()
            today_strs = [
                today.strftime("%d.%m.%Y"),
                today.strftime("%-d %B"),
                today.strftime("%d %B"),
            ]
            is_new = 1 if any(s in posted for s in today_strs) else 0

            jobs.append({
                "id": job_id,
                "title": title,
                "company": company,
                "category": category,
                "location": location,
                "salary": salary,
                "vip": vip,
                "posted": posted,
                "deadline": deadline,
                "url": url,
                "is_new": is_new,
                "scraped_at": datetime.now().isoformat(),
            })

        except Exception as e:
            log.debug(f"Row parse error: {e}")
            continue

    return jobs


def save_jobs(jobs: list[dict]):
    if not jobs:
        return
    con = sqlite3.connect(DB_PATH)
    con.executemany("""
        INSERT OR REPLACE INTO jobs
            (id, title, company, category, location, salary, vip, posted, deadline, url, is_new, scraped_at)
        VALUES
            (:id, :title, :company, :category, :location, :salary, :vip, :posted, :deadline, :url, :is_new, :scraped_at)
    """, jobs)
    con.commit()
    con.close()


def run_scrape():
    """სრული გაპარსვა — ყველა გვერდი, ყველა ვაკანსია"""
    started = datetime.now().isoformat()
    log.info("=== Scrape started ===")
    init_db()

    # გვერდი 1
    soup1 = fetch_page(f"{BASE_URL}/ge/")
    if not soup1:
        log.error("Cannot reach jobs.ge")
        return 0

    total_pages = get_total_pages(soup1)
    log.info(f"Total pages detected: {total_pages}")

    all_jobs = parse_jobs_from_soup(soup1)
    log.info(f"Page 1: {len(all_jobs)} jobs")
    save_jobs(all_jobs)

    total_saved = len(all_jobs)

    # დანარჩენი გვერდები
    for p in range(2, total_pages + 1):
        time.sleep(DELAY)
        url = f"{BASE_URL}/ge/?page={p}"
        soup = fetch_page(url)
        if not soup:
            log.warning(f"Skipping page {p}")
            continue
        jobs = parse_jobs_from_soup(soup)
        if not jobs:
            log.info(f"Page {p}: empty — stopping")
            break
        log.info(f"Page {p}: {len(jobs)} jobs")
        save_jobs(jobs)
        total_saved += len(jobs)

    ended = datetime.now().isoformat()
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO scrape_log (started_at, ended_at, total, status) VALUES (?,?,?,?)",
        (started, ended, total_saved, "ok")
    )
    con.commit()
    con.close()

    log.info(f"=== Done: {total_saved} total jobs ===")
    return total_saved


if __name__ == "__main__":
    run_scrape()
