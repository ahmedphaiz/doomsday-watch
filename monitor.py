"""
Doomsday Watch - checks cinema.mv for Avengers: Doomsday ticket sales
and sends an email when tickets look available.

Environment variables:
  GMAIL_USER          Gmail address that sends the alert (required to email)
  GMAIL_APP_PASSWORD  16-character Gmail App Password (required to email)
  NOTIFY_TO           Where to send the alert (defaults to GMAIL_USER)
  CINEMA_URL          Page to check (default https://cinema.mv)
  MOVIE_KEYWORD       Text to look for (default "doomsday")
  ALERT_ON_ANY        "1" = alert as soon as the film appears anywhere,
                      even under "Coming soon" (default "0")
  TEST_EMAIL          "1" = just send a test email and exit

Exit code 0 always (so GitHub doesn't spam you with failure emails).
Writes found=true/false to $GITHUB_OUTPUT when running in GitHub Actions.
"""

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

from playwright.sync_api import sync_playwright

URL = os.environ.get("CINEMA_URL", "https://cinema.mv")
KEYWORD = os.environ.get("MOVIE_KEYWORD", "doomsday").lower()
ALERT_ON_ANY = os.environ.get("ALERT_ON_ANY", "0") == "1"

# Runs inside the page. Finds every element mentioning the keyword, then
# looks at its surrounding "movie card" for booking buttons or showtimes,
# and checks whether it sits under a "Coming soon" heading.
FIND_JS = r"""
(kw) => {
  const BOOK = /\b(book|buy|get)\s*(now|tickets?|seats?)?\b|\btickets?\b|\bshow\s*times?\b|\breserve\b/i;
  const TIME = /\b([01]?\d|2[0-3])[:.][0-5]\d\s*(am|pm)?\b/i;
  const SOON = /coming\s*soon|upcoming|releasing\s*soon|next\s*release/i;

  const mentions = (el) => {
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ');
    const attrs = ['alt', 'title', 'aria-label', 'href', 'src', 'data-title', 'data-name']
      .map(a => el.getAttribute && el.getAttribute(a) || '').join(' ');
    return (own + ' ' + attrs).toLowerCase().includes(kw);
  };

  const underSoon = (el) => {
    // Walk up the page; the nearest section label (id/class or heading) wins.
    let node = el;
    for (let depth = 0; node && depth < 12; depth++, node = node.parentElement) {
      const label = ((node.id || '') + ' ' + (typeof node.className === 'string' ? node.className : '') + ' ' +
                     ((node.getAttribute && node.getAttribute('aria-label')) || '')).replace(/[-_]/g, ' ');
      if (SOON.test(label)) return true;
      if (/now\s*showing|in\s*cinemas|showing\s*now/i.test(label)) return false;
      let sib = node.previousElementSibling;
      for (let i = 0; sib && i < 30; i++, sib = sib.previousElementSibling) {
        if (/^(NAV|HEADER|UL|OL|SCRIPT|STYLE)$/.test(sib.tagName) || sib.querySelector('nav, a[href]')) continue;
        const t = (sib.innerText || '').trim();
        if (/^H[1-6]$/.test(sib.tagName) || (t.length > 0 && t.length < 40)) {
          if (SOON.test(t)) return true;
          if (/now\s*showing|in\s*cinemas|showing\s*now/i.test(t)) return false;
        }
      }
    }
    return false;
  };

  const hits = [...document.querySelectorAll('*')].filter(mentions);
  return hits.slice(0, 20).map(el => {
    // Grow to the enclosing card (stop before it gets page-sized)
    const SECTION = /coming\s*soon|now\s*showing|upcoming|in\s*cinemas/i;
    const count = (n) => n.querySelectorAll('h1,h2,h3,h4,h5,h6,img').length + (/^(H[1-6]|IMG)$/.test(n.tagName) ? 1 : 0);
    let card = el;
    for (let i = 0; i < 6 && card.parentElement; i++) {
      const p = card.parentElement;
      const pt = p.innerText || '', ct = card.innerText || '';
      if (pt.length > 1500) break;
      if (SECTION.test(pt) && !SECTION.test(ct)) break;      // would swallow a section label
      if (count(p) > Math.max(2, count(card) + 1)) break;    // would swallow another film
      card = p;
    }
    const text = (card.innerText || '').replace(/\s+/g, ' ').trim();
    const clickables = [...card.querySelectorAll('a, button, [role=button]')];
    const hasBook = clickables.some(c => BOOK.test((c.innerText || '') + ' ' + (c.getAttribute('aria-label') || '')));
    const links = [...new Set(clickables.map(c => c.href).filter(Boolean))];
    if (el.href) links.unshift(el.href);
    return {
      text: text.slice(0, 300),
      hasBook,
      hasTime: TIME.test(text),
      soon: underSoon(el),
      links: links.slice(0, 5),
    };
  });
}
"""

PAGE_HAS_BOOKING_JS = r"""
() => {
  const BOOK = /\b(book|buy|get)\s*(now|tickets?|seats?)\b|\bselect\s*seats?\b|\bbuy\b/i;
  const TIME = /\b([01]?\d|2[0-3])[:.][0-5]\d\s*(am|pm)?\b/i;
  const clickables = [...document.querySelectorAll('a, button, [role=button]')];
  const book = clickables.some(c => BOOK.test(c.innerText || ''));
  const times = clickables.filter(c => TIME.test(c.innerText || '')).length;
  const h = [...document.querySelectorAll('h1,h2,h3')].map(x => x.innerText).join(' ');
  const soon = /coming\s*soon/i.test(h) && times === 0;
  return { book, times, soon };
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


def check() -> tuple[bool, str]:
    """Returns (tickets_on_sale, explanation)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"))
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)  # let JS-rendered listings settle

        hits = page.evaluate(FIND_JS, KEYWORD)
        if not hits:
            browser.close()
            return False, f"'{KEYWORD}' not found on {URL}"

        for h in hits:
            print(f"  match: soon={h['soon']} book={h['hasBook']} time={h['hasTime']} :: {h['text'][:120]}")

        if ALERT_ON_ANY:
            browser.close()
            return True, f"'{KEYWORD}' now appears on {URL}:\n\n{hits[0]['text']}"

        # 1) Card on the homepage itself shows a booking button / showtimes
        for h in hits:
            if not h["soon"] and (h["hasBook"] or h["hasTime"]):
                browser.close()
                return True, f"Booking appears open on {URL}:\n\n{h['text']}"

        # 2) Follow the film's own page and look for booking there
        tried = set()
        for h in hits:
            for link in h["links"]:
                if link.split("#")[0] == page.url.split("#")[0] or link in tried or not link.startswith("http"):
                    continue
                tried.add(link)
                if len(tried) > 4:
                    break
                try:
                    page.goto(link, wait_until="networkidle", timeout=45_000)
                    page.wait_for_timeout(2000)
                    r = page.evaluate(PAGE_HAS_BOOKING_JS)
                    print(f"  film page {link}: {r}")
                    if (r["book"] or r["times"] >= 1) and not r["soon"]:
                        browser.close()
                        return True, f"Booking appears open on the film page:\n{link}"
                except Exception as e:  # noqa: BLE001
                    print(f"  could not open {link}: {e}")

        browser.close()
        where = "listed as coming soon" if any(h["soon"] for h in hits) else "listed, but no booking yet"
        return False, f"'{KEYWORD}' is {where}"


def main() -> None:
    if os.environ.get("TEST_EMAIL") == "1":
        send_email("Doomsday Watch: test email",
                   f"This is a test. The checker is set up and watching {URL}.")
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
                   f"{why}\n\nGo book: {URL}\n\n(The checker has now switched itself off.)")
    set_output(found)


if __name__ == "__main__":
    sys.exit(main())
