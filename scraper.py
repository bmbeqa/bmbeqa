"""
jobs.ge სრული სკრეიფერი
პარსავს ყველა გვერდს და ინახავს SQLite-ში
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
DELAY = 1.5  # წამი გვერდებს შორის


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
            time.sleep(2 * (attempt + 1))
    return None


def get_total_pages(soup: BeautifulSoup) -> int:
    """ბოლო გვერდის ნომრის ამოღება pagination-იდან"""
    try:
        pages = soup.select("div.pagination a, div#pagination a, a[href*='page=']")
        nums = []
        for a in pages:
            href = a.get("href", "")
            m = re.search(r"page=(\d+)", href)
            if m:
                nums.append(int(m.group(1)))
            txt = a.get_text(strip=True)
            if txt.isdigit():
                nums.append(int(txt))
        return max(nums) if nums else 1
    except Exception as e:
        log.warning(f"Could not get total pages: {e}")
        return 1


def parse_job_row(row) -> Optional[dict]:
    """ერთი ვაკანსიის row-ის დამუშავება"""
    try:
        job = {}

        # ID
        link = row.select_one("a[href*='view=jobs']")
        if not link:
            return None
        href = link.get("href", "")
        m = re.search(r"id=(\d+)", href)
        job["id"] = int(m.group(1)) if m else None
        if not job["id"]:
            return None

        # სათაური
        job["title"] = link.get_text(strip=True)
        job["url"] = BASE_URL + "/ge/?" + href.lstrip("?./") if href.startswith("?") else href

        # კომპანია
        company_el = row.select_one("td.company, .joblist-company-name, a[href*='company']")
        job["company"] = company_el.get_text(strip=True) if company_el else ""

        # კატეგორია
        cat_el = row.select_one("td.category, .joblist-category")
        job["category"] = cat_el.get_text(strip=True) if cat_el else ""

        # ლოკაცია
        loc_el = row.select_one("td.location, .joblist-location")
        job["location"] = loc_el.get_text(strip=True) if loc_el else ""

        # ხელფასი (badge-ს მიხედვით)
        job["salary"] = 1 if row.select_one(".salary-badge, img[src*='salary'], .has-salary") else 0

        # VIP
        job["vip"] = 1 if row.select_one(".vip-badge, img[src*='vip'], .is-vip, td.vip") else 0

        # თარიღები
        dates = row.select("td.date, .joblist-date, td[class*='date']")
        job["posted"] = dates[0].get_text(strip=True) if len(dates) > 0 else ""
        job["deadline"] = dates[1].get_text(strip=True) if len(dates) > 1 else ""

        # ახალია თუ არა (დღეს გამოქვეყნდა)
        today = datetime.now().strftime("%d %B").lstrip("0")
        job["is_new"] = 1 if today in job.get("posted", "") else 0
        job["scraped_at"] = datetime.now().isoformat()

        return job
    except Exception as e:
        log.debug(f"Row parse error: {e}")
        return None


def scrape_page(page_num: int) -> list[dict]:
    """ერთი გვერდის გაპარსვა"""
    url = f"{BASE_URL}/ge/?page={page_num}"
    soup = fetch_page(url)
    if not soup:
        return []

    rows = soup.select("table.jobs-list tr, tr.job-row, div.job-item, .joblist tr[id]")

    # fallback — ნებისმიერი tr რომელსაც view=jobs ბმული აქვს
    if not rows:
        rows = [tr for tr in soup.select("tr") if tr.select_one("a[href*='view=jobs']")]

    jobs = []
    for row in rows:
        job = parse_job_row(row)
        if job:
            jobs.append(job)

    log.info(f"Page {page_num}: {len(jobs)} jobs")
    return jobs


def save_jobs(jobs: list[dict]):
    if not jobs:
        return
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executemany("""
        INSERT OR REPLACE INTO jobs
            (id, title, company, category, location, salary, vip, posted, deadline, url, is_new, scraped_at)
        VALUES
            (:id, :title, :company, :category, :location, :salary, :vip, :posted, :deadline, :url, :is_new, :scraped_at)
    """, jobs)
    con.commit()
    con.close()


def run_scrape():
    """სრული გაპარსვა — ყველა გვერდი"""
    started = datetime.now().isoformat()
    log.info("=== Scrape started ===")
    init_db()

    # პირველი გვერდი — ვიგებთ სულ რამდენი გვერდია
    url_first = f"{BASE_URL}/ge/"
    soup_first = fetch_page(url_first)
    if not soup_first:
        log.error("Cannot reach jobs.ge")
        return

    total_pages = get_total_pages(soup_first)
    log.info(f"Total pages: {total_pages}")

    # პირველი გვერდი დამუშავება
    rows = [tr for tr in soup_first.select("tr") if tr.select_one("a[href*='view=jobs']")]
    all_jobs = []
    for row in rows:
        job = parse_job_row(row)
        if job:
            all_jobs.append(job)
    log.info(f"Page 1: {len(all_jobs)} jobs")

    # დანარჩენი გვერდები
    for p in range(2, total_pages + 1):
        time.sleep(DELAY)
        jobs = scrape_page(p)
        all_jobs.extend(jobs)

    save_jobs(all_jobs)

    ended = datetime.now().isoformat()
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO scrape_log (started_at, ended_at, total, status) VALUES (?,?,?,?)",
                (started, ended, len(all_jobs), "ok"))
    con.commit()
    con.close()

    log.info(f"=== Done: {len(all_jobs)} jobs saved ===")
    return len(all_jobs)


if __name__ == "__main__":
    run_scrape()
