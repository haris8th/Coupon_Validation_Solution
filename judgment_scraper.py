"""
Search MN judgments by last name + first-name prefix (AA* .. ZZ*),
open every judgment link from the results, and save the full details to CSV.

Usage:
    python judgment_scraper.py                    # run the scraper (resumable)
    python judgment_scraper.py --test page.html   # only test the parser on a saved page
"""

import csv
import logging
import os
import re
import string
import sys
import time
from itertools import product

from scrapy.selector import Selector


# ================= CONFIGURATION =================

BASE_URL = "https://publicaccess.courts.state.mn.us"
SEARCH_URL = f"{BASE_URL}/JudgmentSearch"

OUTPUT_FILE = "judgment_details.csv"
PROGRESS_FILE = "processed_combinations.txt"   # finished name|combination keys
LINKS_DONE_FILE = "processed_links.txt"        # finished judgment URLs
LOG_FILE = "scraper.log"

START_DATE = "01/01/2020"
END_DATE = "04/11/2026"

DETAIL_DELAY = 1.5   # seconds between judgment page loads

Last_names = [
    "Smith",
    "Johnson",
]


COLUMNS = [
    "search_name",
    "combination",
    "total_results",
    "link",
    "case_number",
    "case_title",
    "case_type",
    "case_location",
    "case_details_link",
    "debtor_name",
    "debtor_last_name",
    "debtor_first_name",
    "debtor_address",
    "debtor_city",
    "debtor_state",
    "debtor_zip",
    "all_debtors",
    "creditor_name",
    "creditor_address",
    "all_creditors",
    "judgment_type",
    "judicial_officer",
    "status",
    "docketed_date",
    "entered_date",
    "original_principal",
    "current_principal_due",
    "current_costs_due",
    "interest_rate_type",
]


# ================= DETAIL PAGE PARSER =================

def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def labeled_value(sel, label):
    """Value in the span right after a bold 'Label:' span (the visible one, not sr-only)."""
    value = sel.xpath(
        f'//span[contains(@class, "mpa-text-semi-bold")]'
        f'[normalize-space()="{label}:"]'
        f'/following-sibling::span[1]//text()'
    ).getall()
    return clean(" ".join(value))


def money(text):
    """'$ 2,943.81' -> '2943.81'"""
    return re.sub(r"[^\d.\-]", "", text or "")


def parse_parties(sel, role):
    """List of (name, address) under the 'Debtor' or 'Creditor' heading."""
    parties = []
    items = sel.xpath(
        f'//h3[normalize-space()="{role}"]/following-sibling::ul[1]'
        f'//div[contains(@class, "mpa-judgment-party-item")]'
    )
    for item in items:
        lines = [clean(" ".join(d.xpath(".//text()").getall()))
                 for d in item.xpath("./div")]
        lines = [l for l in lines if l]
        name = lines[0] if lines else ""
        address = ", ".join(lines[1:])
        parties.append((name, address))
    return parties


def split_city_state_zip(address):
    """'Minneapolis, MN 55421' -> ('Minneapolis', 'MN', '55421')"""
    m = re.search(r"([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", address or "")
    if m:
        return clean(m.group(1)), m.group(2), m.group(3)
    return "", "", ""


def split_person_name(name):
    """'SMITH, AARON' -> ('SMITH', 'AARON')"""
    if "," in name:
        last, first = name.split(",", 1)
        return clean(last), clean(first)
    return "", ""


def parse_judgment_page(html):
    sel = Selector(text=html)

    debtors = parse_parties(sel, "Debtor")
    creditors = parse_parties(sel, "Creditor")

    debtor_name, debtor_address = debtors[0] if debtors else ("", "")
    creditor_name, creditor_address = creditors[0] if creditors else ("", "")

    last, first = split_person_name(debtor_name)
    city, state, zip_code = split_city_state_zip(debtor_address)

    roa_href = sel.xpath('//a[contains(@class, "mpa-judgment-roa-btn")]/@href').get()

    return {
        "case_number": labeled_value(sel, "Case Number"),
        "case_title": labeled_value(sel, "Case Title"),
        "case_type": labeled_value(sel, "Case Type"),
        "case_location": labeled_value(sel, "Case Location"),
        "case_details_link": (BASE_URL + roa_href) if roa_href else "",
        "debtor_name": debtor_name,
        "debtor_last_name": last,
        "debtor_first_name": first,
        "debtor_address": debtor_address,
        "debtor_city": city,
        "debtor_state": state,
        "debtor_zip": zip_code,
        "all_debtors": " | ".join(f"{n} ({a})" if a else n for n, a in debtors),
        "creditor_name": creditor_name,
        "creditor_address": creditor_address,
        "all_creditors": " | ".join(f"{n} ({a})" if a else n for n, a in creditors),
        "judgment_type": labeled_value(sel, "Judgment Type"),
        "judicial_officer": labeled_value(sel, "Judicial Officer"),
        "status": labeled_value(sel, "Status"),
        "docketed_date": labeled_value(sel, "Docketed Date"),
        "entered_date": labeled_value(sel, "Entered Date"),
        "original_principal": money(labeled_value(sel, "Original Principal")),
        "current_principal_due": money(labeled_value(sel, "Current Principal Due")),
        "current_costs_due": money(labeled_value(sel, "Current Costs Due")),
        "interest_rate_type": labeled_value(sel, "Interest Rate Type"),
    }


# ================= TEST MODE =================

if len(sys.argv) == 3 and sys.argv[1] == "--test":
    with open(sys.argv[2], encoding="utf-8") as f:
        for k, v in parse_judgment_page(f.read()).items():
            print(f"{k:24} {v}")
    sys.exit(0)


# ================= SELENIUM IMPORTS =================

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ================= LOGGING =================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ================= CSV / PROGRESS =================

if not os.path.exists(OUTPUT_FILE):
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writeheader()


def save_row(row):
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=COLUMNS).writerow(row)
        f.flush()
        os.fsync(f.fileno())


def load_set(path):
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def append_line(path, value, target_set):
    with open(path, "a", encoding="utf-8") as f:
        f.write(value + "\n")
        f.flush()
        os.fsync(f.fileno())
    target_set.add(value)


processed = load_set(PROGRESS_FILE)
links_done = load_set(LINKS_DONE_FILE)


# ================= STEPS =================

def run_search(driver, last_name, combination):
    """Fill the search form, submit, and return (total_results, [absolute links])."""
    driver.get(SEARCH_URL)

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.ID, "LastName"))
    )

    driver.find_element(By.ID, "LastName").send_keys(last_name)
    driver.find_element(By.ID, "FirstName").send_keys(combination)

    driver.find_element(
        By.XPATH, '//label[@for="mpaJudgmentSearchDocketedDateToggleRange"]'
    ).click()
    time.sleep(1)

    driver.find_element(By.ID, "DocketedDateFrom").send_keys(START_DATE)
    driver.find_element(By.ID, "DocketedDateTo").send_keys(END_DATE)

    driver.find_element(
        By.XPATH, '//select[@id="JudgmentStatus"]/option[2]'
    ).click()
    time.sleep(2)

    driver.find_element(By.ID, "btnJudgmentSearch").click()

    WebDriverWait(driver, 30).until(
        EC.visibility_of_element_located(
            (By.XPATH, '//h1[contains(., "Judgment Search Results")]')
        )
    )

    resp = Selector(text=driver.page_source)

    total_results = 0
    total_text = resp.xpath('//div[@class="mpa-text-sm"]/text()').get()
    if total_text:
        digits = "".join(c for c in total_text if c.isdigit())
        if digits:
            total_results = int(digits)

    hrefs = resp.xpath(
        '//a[contains(@class, "mpa-judgment-search-results-btn")]/@href'
    ).getall()

    # absolute + de-duplicated, keeping order
    links = list(dict.fromkeys(BASE_URL + h for h in hrefs))
    return total_results, links


def scrape_detail(driver, link):
    """Open a judgment page and return its parsed fields."""
    driver.get(link)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.ID, "judCaseInformation"))
    )
    return parse_judgment_page(driver.page_source)


# ================= MAIN =================

driver = uc.Chrome(version_main=156)
driver.get(SEARCH_URL)
input("Complete any check in the browser, then press Enter to start...")

try:
    for names in Last_names:

        logger.info("=" * 60)
        logger.info(f"STARTING LAST NAME: {names}")
        logger.info("=" * 60)

        for a, b in product(string.ascii_uppercase, repeat=2):

            combination = f"{a}{b}*"
            progress_key = f"{names}|{combination}"

            if progress_key in processed:
                logger.info(f"SKIPPED: {names} | {combination}")
                continue

            logger.info(f"SEARCHING: {names} | {combination}")

            # ---- 1. search ----
            try:
                total_results, links = run_search(driver, names, combination)
            except Exception as e:
                logger.exception(f"SEARCH ERROR: {names} | {combination} | {e}")
                continue

            logger.info(
                f"FOUND: {names} | {combination} | "
                f"Total Results: {total_results} | Links: {len(links)}"
            )

            # ---- 2. open each judgment and save details ----
            failed = 0
            for i, link in enumerate(links, 1):

                if link in links_done:
                    continue

                try:
                    data = scrape_detail(driver, link)
                    data.update({
                        "search_name": names,
                        "combination": combination,
                        "total_results": total_results,
                        "link": link,
                    })

                    save_row(data)
                    append_line(LINKS_DONE_FILE, link, links_done)

                    logger.info(
                        f"  [{i}/{len(links)}] {data['case_number']} | "
                        f"{data['debtor_name']} | ${data['original_principal']}"
                    )

                except Exception as e:
                    failed += 1
                    logger.exception(f"  [{i}/{len(links)}] DETAIL ERROR: {link} | {e}")

                time.sleep(DETAIL_DELAY)

            # Only mark the combination done when every judgment was saved,
            # so a rerun retries the failed ones (saved ones are skipped).
            if failed == 0:
                append_line(PROGRESS_FILE, progress_key, processed)
                logger.info(f"COMPLETED: {names} | {combination}")
            else:
                logger.warning(
                    f"INCOMPLETE: {names} | {combination} | {failed} failed, will retry next run"
                )

finally:
    driver.quit()
    logger.info("=" * 60)
    logger.info("SCRAPING PROCESS FINISHED")
    logger.info("=" * 60)
