"""
jobs.ge სრული სკრეიფერი
for_scroll=yes endpoint-ს იყენებს
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import time
import logging
from datetime import datetime
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://jobs.ge"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "ka-GE,ka;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://jobs.ge/ge/",
}
DB_PATH = "jobs.db"
DELAY = 1.0


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
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
    con.execute("""
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


def fetch_scroll_page(page: int):
    url = (
        f"{BASE_URL}/ge/"
        f"?page={page}&q=&cid=0&lid=0&jid=0"
        f"&in_title=0&has_salary=0&is_ge=0&for_scroll=yes"
    )
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            log.warning(f"Page {page} attempt {attempt+1}: {e}")
            time.sleep(3)
    return None


def parse_jobs(soup) -> list[dict]:
    jobs = []
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

            url = f"{BASE_URL}/ge/{href}" if href.startswith("?") else href
            all_links = row.find_all("a", href=True)

            # კომპანია
            company = ""
            for lnk in all_links:
                h = lnk.get("href", "")
                if "employer" in h or "uid=" in h:
                    company = lnk.get_text(strip=True)
                    break

            # კატეგორია
            category = ""
            for lnk in all_links:
                h = lnk.get("href", "")
                if "cid=" in h and "cid=0" not in h:
                    category = lnk.get_text(strip=True)
                    break

            # ლოკაცია
            location = ""
            for lnk in all_links:
                h = lnk.get("href", "")
                if "lid=" in h and "lid=0" not in h:
                    location = lnk.get_text(strip=True)
                    break

            # თარიღები
            tds = [td.get_text(strip=True) for td in row.find_all("td")]
            date_pat = re.compile(r"\d{1,2}[\s\.]\w+|\d{2}\.\d{2}\.\d{4}")
            date_vals = [t for t in tds if date_pat.search(t)]
            posted   = date_vals[0] if len(date_vals) > 0 else ""
            deadline = date_vals[1] if len(date_vals) > 1 else (date_vals[0] if date_vals else "")

            # VIP
            vip = 1 if (
                row.find(class_=re.compile(r"vip", re.I)) or
                row.find("img", src=re.compile(r"vip", re.I))
            ) else 0

            # ხელფასი
            salary = 1 if (
                row.find(class_=re.compile(r"salary", re.I)) or
                row.find("img", src=re.compile(r"salary|lari|gel", re.I))
            ) else 0

            # დღეს გამოქვეყნებული
            today = datetime.now()
            today_strs = [today.strftime("%d.%m.%Y"), today.strftime("%d %B")]
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
            log.debug(f"Row error: {e}")
            continue

    return jobs


def save_jobs(jobs: list[dict]):
    if not jobs:
        return
    con = sqlite3.connect(DB_PATH)
    con.executemany("""
        INSERT OR REPLACE INTO jobs
            (id, title, company, category, location, salary, vip,
             posted, deadline, url, is_new, scraped_at)
        VALUES
            (:id, :title, :company, :category, :location, :salary, :vip,
             :posted, :deadline, :url, :is_new, :scraped_at)
    """, jobs)
    con.commit()
    con.close()


def run_scrape():
    started = datetime.now().isoformat()
    log.info("=== Scrape started ===")
    init_db()

    total_saved = 0
    page = 1
    empty_streak = 0

    while True:
        soup = fetch_scroll_page(page)
        if not soup:
            empty_streak += 1
            if empty_streak >= 3:
                break
            page += 1
            continue

        jobs = parse_jobs(soup)
        log.info(f"Page {page}: {len(jobs)} jobs")

        if not jobs:
            empty_streak += 1
            if empty_streak >= 3:
                log.info("3 empty pages in a row — done")
                break
        else:
            empty_streak = 0
            save_jobs(jobs)
            total_saved += len(jobs)

        page += 1
        time.sleep(DELAY)

    ended = datetime.now().isoformat()
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO scrape_log (started_at, ended_at, total, status) VALUES (?,?,?,?)",
        (started, ended, total_saved, "ok")
    )
    con.commit()
    con.close()

    log.info(f"=== Done: {total_saved} jobs, {page-1} pages ===")
    return total_saved


if __name__ == "__main__":
    run_scrape()
