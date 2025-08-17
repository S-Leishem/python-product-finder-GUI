import os
import re
import sys
import json
import time
import queue
import threading
import webbrowser
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

import requests
from bs4 import BeautifulSoup

import tkinter as tk
from tkinter import ttk, messagebox

# ---------------------------
# Config / Constants
# ---------------------------
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
DEFAULT_MAX_RESULTS = 40
HTTP_TIMEOUT = 20
DESC_TIMEOUT = 10

CURRENCY_INR = "INR"
CURRENCY_USD = "USD"

# ---------------------------
# Data models
# ---------------------------
@dataclass
class Product:
    title: str
    link: str                    # direct retailer link when available
    source: Optional[str]
    price_value: Optional[float]
    currency: Optional[str]      # "INR" or "USD"
    rating: Optional[float]
    reviews: Optional[int]
    thumbnail: Optional[str]
    description: Optional[str] = None
    score: Optional[float] = None  # computed value-for-money score


# ---------------------------
# Helpers
# ---------------------------
def parse_price_text(price: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    """
    Attempt to parse a price string and determine currency.
    Returns (value, currency) where currency is "INR"/"USD"/None.
    """
    if not price:
        return None, None
    s = price.strip()

    # Currency detection
    currency = None
    if "₹" in s or "Rs" in s or "rupee" in s.lower():
        currency = CURRENCY_INR
    elif "$" in s:
        currency = CURRENCY_USD

    # Normalize numeric part
    cleaned = (
        s.replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("$", "")
        .strip()
    )

    # Extract first number
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", cleaned)
    if not m:
        return None, currency
    try:
        val = float(m.group(1))
    except Exception:
        val = None
    return val, currency


def compute_score(price: Optional[float], rating: Optional[float], max_price: float) -> float:
    """
    Simple value-for-money score combining rating and price proximity to budget.
    """
    rating_norm = (rating / 5.0) if (rating is not None and rating > 0) else 0.5
    if price is None or price <= 0:
        price_part = 0.2
    else:
        price_part = max(0.0, min(1.0, 1.0 - (price / max_price)))
    return 0.65 * rating_norm + 0.35 * price_part


def dedupe_by_title(products: List[Product]) -> List[Product]:
    seen = set()
    out: List[Product] = []
    for p in products:
        key = re.sub(r"\s+", " ", p.title.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ---------------------------
# Currency conversion (no API key)
# ---------------------------
class FxCache:
    def __init__(self):
        self.rate_usd_inr: Optional[float] = None
        self.updated_at: float = 0.0

    def get_rate(self) -> Optional[float]:
        # Refresh every 12 hours
        if self.rate_usd_inr and (time.time() - self.updated_at) < 12 * 3600:
            return self.rate_usd_inr
        try:
            # Using exchangerate.host (free, no key)
            resp = requests.get(
                "https://api.exchangerate.host/latest",
                params={"base": "USD", "symbols": "INR"},
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
            rate = data.get("rates", {}).get("INR")
            if isinstance(rate, (int, float)) and rate > 0:
                self.rate_usd_inr = float(rate)
                self.updated_at = time.time()
                return self.rate_usd_inr
        except Exception:
            return self.rate_usd_inr  # return stale if available
        return None

    def convert(self, amount: float, from_ccy: str, to_ccy: str) -> Optional[float]:
        if amount is None:
            return None
        if from_ccy == to_ccy:
            return amount
        rate = self.get_rate()
        if not rate:
            return None
        if from_ccy == CURRENCY_USD and to_ccy == CURRENCY_INR:
            return amount * rate
        if from_ccy == CURRENCY_INR and to_ccy == CURRENCY_USD:
            return amount / rate
        return None


fx_cache = FxCache()


# ---------------------------
# SerpAPI Client
# ---------------------------
def fetch_serpapi_results(query: str, serpapi_key: str, gl: str, hl: str = "en") -> List[Dict[str, Any]]:
    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": serpapi_key,
        "gl": gl,
        "hl": hl,
    }
    r = requests.get(SERPAPI_ENDPOINT, params=params, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data.get("shopping_results", []) or []


def transform_results(items: List[Dict[str, Any]], preferred_ccy: str, gl: str) -> List[Product]:
    """
    Build Product list. Prefer product_link (retailer URL) and fall back to link.
    """
    prods: List[Product] = []
    for it in items:
        title = it.get("title") or ""
        # Prefer direct retailer product link
        link = it.get("product_link") or it.get("link") or ""
        source = it.get("source") or it.get("store")
        price_str = it.get("price")
        extracted_price = it.get("extracted_price")
        rating = None
        if "rating" in it:
            try:
                rating = float(it["rating"])
            except Exception:
                rating = None
        reviews = None
        if "reviews" in it:
            try:
                reviews = int(str(it["reviews"]).replace(",", "").strip())
            except Exception:
                reviews = None
        thumb = it.get("thumbnail")

        # Determine currency and numeric price
        value, currency = parse_price_text(price_str)
        # Prefer SerpAPI numeric price when present
        if isinstance(extracted_price, (int, float)):
            value = float(extracted_price)
        # If currency not recognized, infer from region
        if not currency:
            if gl.lower() == "in":
                currency = CURRENCY_INR
            elif gl.lower() == "us":
                currency = CURRENCY_USD

        prods.append(
            Product(
                title=title,
                link=link,
                source=source,
                price_value=value,
                currency=currency,
                rating=rating,
                reviews=reviews,
                thumbnail=thumb,
            )
        )
    return prods


def fetch_description(url: str) -> Optional[str]:
    """
    Fetch a short description from the retailer page using common metadata.
    """
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=DESC_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200 or not resp.text:
            return None
        soup = BeautifulSoup(resp.text, "lxml")

        # JSON-LD Product schema
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "{}")
            except Exception:
                continue
            blocks = data if isinstance(data, list) else [data]
            for block in blocks:
                t = block.get("@type")
                is_prod = False
                if isinstance(t, list):
                    is_prod = any(isinstance(tt, str) and tt.lower() == "product" for tt in t)
                elif isinstance(t, str):
                    is_prod = t.lower() == "product"
                if is_prod:
                    desc = block.get("description")
                    if isinstance(desc, str) and desc.strip():
                        return desc.strip()

        # Meta description
        md = soup.find("meta", attrs={"name": "description"})
        if md and md.get("content"):
            return md["content"].strip()

        # Open Graph description
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            return og["content"].strip()

        # Twitter description
        tw = soup.find("meta", attrs={"name": "twitter:description"})
        if tw and tw.get("content"):
            return tw["content"].strip()

        # Fallback: first paragraph
        p = soup.find("p")
        if p and p.get_text(strip=True):
            return p.get_text(strip=True).strip()
    except Exception:
        return None
    return None


# ---------------------------
# Tkinter GUI
# ---------------------------
class ProductFinderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Best Products Finder (USD/INR)")
        self.geometry("1000x650")
        self.minsize(900, 600)

        # State
        self.products: List[Product] = []
        self.search_thread: Optional[threading.Thread] = None
        self.abort_flag = threading.Event()
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.serpapi_key_var = tk.StringVar(value=os.getenv("SERPAPI_KEY", ""))

        # Top frame: query, amount, currency, API key, search button
        self._build_top_controls()

        # Middle: results table
        self._build_results_table()

        # Bottom: description + open link
        self._build_bottom_pane()

        # Periodic UI updates from worker
        self.after(100, self._process_ui_queue)

    def _build_top_controls(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="x")

        # Query
        ttk.Label(frm, text="Product search:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.query_var = tk.StringVar()
        self.query_entry = ttk.Entry(frm, textvariable=self.query_var, width=40)
        self.query_entry.grid(row=0, column=1, sticky="we")
        self.query_entry.focus()

        # Amount (numbers only)
        ttk.Label(frm, text="Max price:").grid(row=0, column=2, sticky="w", padx=(12, 6))
        self.amount_var = tk.StringVar()
        vc = (self.register(self._validate_amount), "%P")
        self.amount_entry = ttk.Entry(frm, textvariable=self.amount_var, validate="key", validatecommand=vc, width=12)
        self.amount_entry.grid(row=0, column=3, sticky="w")

        # Currency
        ttk.Label(frm, text="Currency:").grid(row=0, column=4, sticky="w", padx=(12, 6))
        self.currency_var = tk.StringVar(value=CURRENCY_INR)
        self.currency_combo = ttk.Combobox(frm, textvariable=self.currency_var, values=[CURRENCY_INR, CURRENCY_USD], width=8, state="readonly")
        self.currency_combo.grid(row=0, column=5, sticky="w")

        # API key (optional, read from env by default)
        ttk.Label(frm, text="SerpAPI Key:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.api_entry = ttk.Entry(frm, textvariable=self.serpapi_key_var, show="*", width=40)
        self.api_entry.grid(row=1, column=1, sticky="we", pady=(8, 0))
        show_btn = ttk.Button(frm, text="Show", width=6, command=self._toggle_show_key)
        show_btn.grid(row=1, column=2, sticky="w", pady=(8, 0))

        # Search button
        self.search_btn = ttk.Button(frm, text="Find Products", command=self.on_search)
        self.search_btn.grid(row=0, column=6, rowspan=2, sticky="e", padx=(12, 0))

        # Status label
        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = ttk.Label(frm, textvariable=self.status_var, foreground="#555")
        self.status_lbl.grid(row=2, column=0, columnspan=7, sticky="w", pady=(8, 0))

        frm.columnconfigure(1, weight=1)

    def _build_results_table(self):
        frm = ttk.Frame(self, padding=(10, 0, 10, 0))
        frm.pack(fill="both", expand=True)

        columns = ("title", "price", "rating", "source")
        self.tree = ttk.Treeview(frm, columns=columns, show="headings", height=12)
        self.tree.heading("title", text="Title")
        self.tree.heading("price", text="Price")
        self.tree.heading("rating", text="Rating")
        self.tree.heading("source", text="Source")

        self.tree.column("title", width=540, anchor="w")
        self.tree.column("price", width=120, anchor="e")
        self.tree.column("rating", width=80, anchor="center")
        self.tree.column("source", width=120, anchor="w")

        vsb = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(frm, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self.on_select_row)
        self.tree.bind("<Double-1>", self.on_open_link)

    def _build_bottom_pane(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=False)

        # Link + open button
        self.link_var = tk.StringVar(value="")
        ttk.Label(frm, text="Link:").grid(row=0, column=0, sticky="nw")
        self.link_entry = ttk.Entry(frm, textvariable=self.link_var)
        self.link_entry.grid(row=0, column=1, sticky="we")
        open_btn = ttk.Button(frm, text="Open Link", command=self.on_open_link)
        open_btn.grid(row=0, column=2, sticky="e", padx=(8, 0))

        # Description
        ttk.Label(frm, text="Description:").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.desc_txt = tk.Text(frm, height=8, wrap="word")
        self.desc_txt.grid(row=1, column=1, columnspan=2, sticky="nsew", pady=(8, 0))
        desc_vsb = ttk.Scrollbar(frm, orient="vertical", command=self.desc_txt.yview)
        self.desc_txt.configure(yscrollcommand=desc_vsb.set)
        desc_vsb.grid(row=1, column=3, sticky="ns", pady=(8, 0))

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(1, weight=1)

    def _toggle_show_key(self):
        if self.api_entry.cget("show") == "*":
            self.api_entry.config(show="")
        else:
            self.api_entry.config(show="*")

    def _validate_amount(self, proposed: str) -> bool:
        # Allow empty (for editing) or digits only
        if proposed == "":
            return True
        return proposed.isdigit()

    def set_status(self, text: str):
        self.status_var.set(text)
        self.update_idletasks()

    def on_search(self):
        query = (self.query_var.get() or "").strip()
        amount_str = (self.amount_var.get() or "").strip()
        currency = self.currency_var.get()
        api_key = (self.serpapi_key_var.get() or "").strip()

        if not query:
            messagebox.showwarning("Input required", "Please enter a product search term (e.g., 'gaming phone').")
            return
        if not amount_str or not amount_str.isdigit():
            messagebox.showwarning("Input required", "Please enter a numeric max price (numbers only).")
            return
        if currency not in (CURRENCY_INR, CURRENCY_USD):
            messagebox.showwarning("Invalid currency", "Currency must be INR or USD.")
            return
        if not api_key:
            messagebox.showwarning("SerpAPI key required", "Please enter your SerpAPI API key.")
            return

        max_price = float(amount_str)

        # Disable UI during search
        self.search_btn.config(state="disabled")
        self.set_status("Searching…")
        self.products = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.desc_txt.delete("1.0", "end")
        self.link_var.set("")

        # Start background worker
        self.abort_flag.clear()
        args = (query, max_price, currency, api_key)
        self.search_thread = threading.Thread(target=self._worker_search, args=args, daemon=True)
        self.search_thread.start()

    def _worker_search(self, query: str, max_price: float, currency: str, api_key: str):
        try:
            gl = "in" if currency == CURRENCY_INR else "us"

            self.ui_queue.put(("status", f"Searching Google Shopping ({currency})…"))
            raw = fetch_serpapi_results(query, api_key, gl=gl)
            items = transform_results(raw, currency, gl)

            # Filter by price (convert when needed)
            filtered: List[Product] = []
            for p in items:
                if p.price_value is None or not p.currency:
                    continue
                price_in_selected = p.price_value
                if p.currency != currency:
                    conv = fx_cache.convert(p.price_value, p.currency, currency)
                    if conv is None:
                        continue
                    price_in_selected = conv
                if price_in_selected <= max_price:
                    # Normalize for display
                    p.price_value = price_in_selected
                    p.currency = currency
                    filtered.append(p)

            if not filtered:
                self.ui_queue.put(("done", "No products found under your budget. Try a different query or higher price."))
                return

            filtered = dedupe_by_title(filtered)
            for p in filtered:
                p.score = compute_score(p.price_value, p.rating, max_price)

            # Sort by score desc, then rating desc, then price asc
            filtered.sort(key=lambda x: (-(x.score or 0.0), -(x.rating or 0.0), (x.price_value or float("inf"))))

            # Fetch descriptions for top N
            top_n = min(20, len(filtered))
            for i in range(top_n):
                if self.abort_flag.is_set():
                    break
                self.ui_queue.put(("status", f"Fetching descriptions… {i+1}/{top_n}"))
                if filtered[i].link:
                    desc = fetch_description(filtered[i].link)
                else:
                    desc = None
                filtered[i].description = desc

            # Finalize
            self.products = filtered
            self.ui_queue.put(("populate", None))
            self.ui_queue.put(("done", f"Found {len(filtered)} products."))
        except requests.HTTPError as e:
            self.ui_queue.put(("done", f"HTTP error: {e}"))
        except Exception as e:
            self.ui_queue.put(("done", f"Error: {e}"))

    def _process_ui_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "status":
                    self.set_status(str(payload))
                elif kind == "populate":
                    self._populate_table()
                elif kind == "done":
                    self.set_status(str(payload))
                    self.search_btn.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._process_ui_queue)

    def _populate_table(self):
        # Clear
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Fill
        for idx, p in enumerate(self.products, start=1):
            price_disp = "-"
            if p.price_value is not None:
                price_disp = f"{'₹' if self.currency_var.get()==CURRENCY_INR else '$'}{int(p.price_value):,}"
            rating_disp = f"{p.rating:.1f}/5" if p.rating is not None else "-"
            source_disp = p.source or "-"
            self.tree.insert("", "end", iid=str(idx - 1), values=(p.title, price_disp, rating_disp, source_disp))

        # Select first
        if self.products:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self.on_select_row()

    def on_select_row(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.products):
            return
        p = self.products[idx]
        self.link_var.set(p.link or "")
        self.desc_txt.delete("1.0", "end")
        desc = p.description or "No description available."
        if len(desc) > 2000:
            desc = desc[:2000] + "…"
        self.desc_txt.insert("1.0", desc)

    def on_open_link(self, event=None):
        link = self.link_var.get().strip()
        if link:
            webbrowser.open(link)

    def on_close(self):
        self.abort_flag.set()
        self.destroy()


def main():
    app = ProductFinderApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()