"""
60 წუთში ერთხელ გაშვება
APScheduler + Uvicorn ერთ პროცესში
"""

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from scraper import run_scrape
import logging
import os

log = logging.getLogger(__name__)


def start():
    scheduler = BackgroundScheduler(timezone="Asia/Tbilisi")
    scheduler.add_job(
        run_scrape,
        "interval",
        minutes=60,
        id="jobs_ge_scrape",
        max_instances=1,  # ორი პარალელური სკრეიფი არ გაეშვას
    )
    scheduler.start()
    log.info("Scheduler started — scraping every 60 minutes")
    return scheduler


if __name__ == "__main__":
    scheduler = start()
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False)
