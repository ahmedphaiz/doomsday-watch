"""
Doomsday Watch - checks cinema.mv for Avengers: Doomsday ticket sales
and sends an email when tickets are available.

How it decides (based on how cinema.mv is built):
  * The film's own page (MOVIE_URL) says "There are no screenings of this
    show available" while it's coming soon. Once sales open it lists
    showtimes with "seats available".
  * As a backup it also checks the homepage: the film moving into the
    "Now Showing" row, or its banner showing "Book tickets".

Environment variables:
  GMAIL_USER          Gmail address that sends the alert (required to email)
  GMAIL_APP_PASSWORD  16-character Gmail App Password (required to email)
  NOTIFY_TO           Where to send the alert (defaults to GMAIL_USER)
  MOVIE_URL           Film page (default https://cinema.mv/movie/avengers-doomsday)
  HOME_URL            Homepage (default https://cinema.mv/)
  MOVIE_KEYWORD       Text that identifies the film (default "doomsday")
  TEST_EMAIL          "1" = just send a test email and exit

Always exits 0 so GitHub doesn't spam you with failure emails.
Writes found=true/false to $GITHUB_OUTPUT when running in GitHub Actions.
"""

import os
import re
import smtplib
import ssl
from email.message import EmailMessage

from playwright.sync_api import sync_playwright

MOVIE_URL = os.environ.get("MOVIE_URL", "https://cinema.mv/movie/avengers-doomsday")
HOME_URL = os.environ.get("HOME_URL", "https://cinema.mv/")
KEYWORD = os.environ.get("MOVIE_KEYWORD", "doomsday").lower()

NO_SCREENINGS = re.compile(r"no\s+screenings", re.I)
SHOWTIME_SIGNS = re.compile(r"seats?\s+available|showtimes\s*-|book\s+at\s+counter|\b([01]\d|2[0-3]):[0-5]\d\b", re.I)
BLOCK_SIGNS = re.compile(r"just a moment|attention required|verify you are human|access denied|cf-chl", re.I)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

HOME_JS = r"""
(kw) => {
  const has = (el) => (el.innerText || '').toLowerCase().includes(kw)
                   || [...el.querySelectorAll('img')].some(i => (i.alt || '').toLowerCase().includes(kw));
  const nowRow = document.querySelector('#now-showing');
  const inNowShowing = !!nowRow && [...nowRow.querySelectorAll('a, .poster-card')].some(has);
  const slide = [...document.querySelectorAll('.banner-slide')].find(has);
  const bannerBook = !!slide && /book\s*tickets?|showtimes/i.test(slide.innerText || '');
  const bannerLabel = slide ? ((slide.querySelector('.banner-label') || {}).innerText || '') : '';
  return { inNowShowing, bannerBook, bannerLabel, found: !!slide || [...document.querySelectorAll('a')].some(has) };
}
"""


def send_email(subject: str, body: str) -> None:
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("NOTIFY_TO") or user
    if not (user and pw):
        print("!! GMAIL_USER / GMAIL_APP_PASSWORD not set - cannot send email")
        print(f"Would have sent: {subject}\n{body}")
        return
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pw.replace(" ", ""))
        s.send_message(msg)
    print(f"Email sent to {to}")


def set_output(found: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"found={'true' if found else 'false'}\n")


def load(page, url: str) -> str:
    """Open a page, wait for real content, return its visible text."""
    resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    status = resp.status if resp else "?"
    # Give Cloudflare challenges / late scripts up to ~20s to clear
    text = ""
    for _ in range(10):
        page.wait_for_timeout(2000)
        text = page.inner_text("body") if page.query_selector("body") else ""
        if KEYWORD in text.lower() or NO_SCREENINGS.search(text):
            break
    snippet = re.sub(r"\s+", " ", text)[:200]
    print(f"  {url} -> HTTP {status}, title={page.title()!r}")
    print(f"    text: {snippet}")
    if BLOCK_SIGNS.search(page.title() + " " + text[:500]):
        print("    !! looks like the site served a bot check / block page")
    return text


def check() -> tuple[bool, str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 900})
        page = ctx.new_page()

        # 1) The film's own page
        movie = load(page, MOVIE_URL)
        movie_ok = KEYWORD in movie.lower()
        if movie_ok and SHOWTIME_SIGNS.search(movie) and not NO_SCREENINGS.search(movie):
            browser.close()
            return True, f"Showtimes are listed on the film page:\n{MOVIE_URL}"

        # 2) Backup: the homepage
        load(page, HOME_URL)
        r = page.evaluate(HOME_JS, KEYWORD)
        print(f"  homepage: {r}")
        browser.close()

        if r["inNowShowing"] or r["bannerBook"]:
            return True, f"Avengers: Doomsday is now under Now Showing / has a Book tickets button on {HOME_URL}"

        if not movie_ok and not r["found"]:
            return False, "could not see the film on either page (site may be blocking the checker - see log above)"
        if NO_SCREENINGS.search(movie):
            return False, f"film page says no screenings yet ({r.get('bannerLabel') or 'coming soon'})"
        return False, "film is listed but no showtimes yet"


def main() -> None:
    if os.environ.get("TEST_EMAIL") == "1":
        send_email("Doomsday Watch: test email",
                   f"This is a test. The checker is set up and watching {MOVIE_URL}.")
        set_output(False)
        return

    try:
        found, why = check()
    except Exception as e:  # noqa: BLE001  - site down / timeout: try again next run
        print(f"Check failed this time: {e}")
        set_output(False)
        return

    print(("TICKETS ON SALE: " if found else "Not yet: ") + why)
    if found:
        send_email("🎬 Avengers: Doomsday tickets are on sale at cinema.mv!",
                   f"{why}\n\nGo book: {MOVIE_URL}\n\n(The checker has now switched itself off.)")
    set_output(found)


if __name__ == "__main__":
    main()
