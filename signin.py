"""Sign in to Google once inside the scraper's browser profile.

Signed-out sessions get a "limited view" of Google Maps that hides Updates. Run this, sign in in the
window that opens, then close the window. The persistent profile keeps the session for later scrapes.

    python signin.py

Stop the web app first: Chrome/Edge cannot open the same profile twice.
"""
import time

from gmci.scraper.selenium_maps import MapsScraper

scraper = MapsScraper(headless=False).start()
scraper.driver.get("https://accounts.google.com/ServiceLogin?continue=https://www.google.com/maps?hl=en")
print("Sign in to Google in the browser window, check that Maps opens, then close the window.")
try:
    while True:
        time.sleep(2)
        scraper.driver.window_handles  # raises once the window is closed
except Exception:
    pass
finally:
    scraper.stop()
print("Done. The sign-in is saved in the scraper profile.")
