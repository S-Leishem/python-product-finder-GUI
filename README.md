# GUI Product Finder (USD/INR)

A simple desktop app built with Tkinter that helps you find good-value products (e.g., “gaming phone”) under a chosen budget in INR or USD. It fetches results from Google Shopping via SerpAPI, filters by your price cap, ranks by value-for-money, and shows a brief description with a direct retailer link.

Highlights
- Search anything: “gaming phone”, “mechanical keyboard”, “noise cancelling headphones”.
- Numeric-only budget input (no typos like 20k).
- Currency toggle: INR or USD, with live USD↔INR conversion (exchangerate.host, no API key required).
- Shows title, price, rating, source, description, and a direct “Open Link” button.
- Robust description extraction: JSON-LD Product schema, meta description, Open Graph, and Twitter description.

Note about sources
- The app uses SerpAPI’s Google Shopping API for structured, stable results. Direct scraping of retailers is avoided for reliability and ToS compliance.
- Some retailer pages render content with JavaScript or block scraping; in those cases, descriptions may be missing, but the “Open Link” button will still take you to the correct page.

---

## Quick Start

Prerequisites
- Python 3.10+ installed
- A SerpAPI API key (free tier available): https://serpapi.com/

Install dependencies
```bash
pip install -r requirements.txt
```

Set your SerpAPI key (either via environment variable or paste it into the app field):
- macOS/Linux:
  ```bash
  export SERPAPI_KEY=your_key_here
  ```
- Windows (Powershell):
  ```powershell
  setx SERPAPI_KEY "your_key_here"
  ```
  Restart your terminal after `setx`, or paste the key directly in the app.

Run the app
```bash
python gui_product_finder.py
```

---

## How to Use

1. Product search: Type what you’re looking for (e.g., `gaming phone`).
2. Max price: Enter a number only (e.g., `30000` or `400`).
3. Currency: Choose INR or USD. The app will:
   - Query India (gl=in) if INR.
   - Query United States (gl=us) if USD.
   - Convert prices into your selected currency when needed.
4. SerpAPI Key: If not set in your environment, paste it here (click “Show” to peek).
5. Click “Find Products”.
6. Select a row to view its description. Double-click a row or click “Open Link” to visit the retailer page.

Tips
- Try specific queries like “gaming phone 5g” or “mechanical keyboard hot-swappable”.
- Raise the budget if you see “No products found under your budget.”

---

## Features in Detail

- Google Shopping via SerpAPI:
  - Uses `shopping_results` with fields such as title, price, rating, source, link/product_link.
  - Prefers `product_link` when available (direct retailer URL), falls back to `link`.
- Ranking:
  - A simple score that blends rating (out of 5) and how close the price is to your budget.
- Currency:
  - Live USD↔INR conversion via exchangerate.host (no key). Cached for 12 hours.
- Descriptions:
  - Attempts JSON-LD Product schema first, then meta description, og:description, twitter:description, and finally first paragraph.

---

## Files

- `gui_product_finder.py` — Tkinter GUI application.
- `requirements.txt` — Minimal runtime dependencies.
  - `requests`
  - `beautifulsoup4`
  - `lxml`

---

## Troubleshooting

- “No description available.”:
  - Some retailer pages are rendered client-side or block scraping. Use “Open Link” to view details.
- “Found 0 products…”:
  - Increase your budget or refine the search query.
  - Ensure your currency is correct for your target market.
- “HTTP error: 401” from SerpAPI:
  - Your API key may be missing or invalid. Paste it in the app or set `SERPAPI_KEY`.
- “HTTP error: 429” (rate-limited):
  - You may be hitting SerpAPI free tier limits. Retry later or upgrade your plan.
- Proxy/Corporate network issues:
  - If requests time out, check your network/proxy settings.

---

## Packaging (optional)

Create a single-file executable with PyInstaller:
```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed gui_product_finder.py
```
- The binary will be in `dist/`.
- On Windows, `--windowed` prevents a console window from opening.

---

## Development Notes

- Python version: 3.10+ recommended.
- UI threading: Network calls run in a worker thread; UI updates are queued back to the main thread.
- Recent improvement:
  - Prefer `product_link` for reliable retailer URLs.
  - Added Open Graph and Twitter description fallbacks.
- Extending ideas:
  - Filters for brand/specs (e.g., RAM, battery, release year).
  - CSV export of results.
  - Additional regions/currencies.
  - Saving and reloading previous searches.

---

## Ethics & Compliance

- Always follow the terms of use of the sites you visit.
- This app relies on SerpAPI for search results rather than scraping retailers directly.
- Prices and availability change frequently. Verify details on the retailer’s site before purchasing.

---

## License

Specify a license for your repository (e.g., MIT, Apache-2.0). If you’re unsure, MIT is a common permissive choice.

---

## Acknowledgements

- [SerpAPI](https://serpapi.com/) for Google Shopping API.
- [exchangerate.host](https://exchangerate.host/) for free FX rates.
- Python ecosystem: Tkinter, Requests, BeautifulSoup, lxml.
