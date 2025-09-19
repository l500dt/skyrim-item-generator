"""
generate_skyrim_items_json.py

Script untuk menghasilkan file JSON berisi daftar item Skyrim Special Edition (vanilla + DLC)
Dengan metode:
  - Mengambil daftar link item dari halaman kategori UESP (mis. Weapons, Armor, Spells, Ingredients, Books, Misc_Items)
  - Mengunjungi setiap halaman item, mengekstrak nama item dan FormID (jika tersedia)
  - Menyimpan hasil per-kategori ke file JSON

Fitur:
  - Opsi --category untuk menyuplai URL kategori tambahan
  - Opsi --delay untuk mengatur jeda antar-request (default 1s)
  - Opsi --cache-dir untuk menyimpan HTML yang diunduh (mempercepat resume)
  - Opsi --resume untuk melanjutkan jika file output sudah ada
  - Save progres otomatis setelah tiap kategori

PERINGATAN ETIKA:
  - Hormati robots.txt dan kebijakan situs UESP. Jangan jalankan dengan delay kecil atau paralel tanpa izin.
  - Script ini dimaksudkan untuk penggunaan pribadi atau penelitian; jika kamu akan mendistribusikan data, cek lisensi/ketentuan.

Contoh:
  python generate_skyrim_items_json.py --out skyrim_items_full.json --delay 1.0
  python generate_skyrim_items_json.py --out skyrim_items_full.json --category "weapons:https://en.uesp.net/wiki/Skyrim:Weapons" --category "armor:https://en.uesp.net/wiki/Skyrim:Armor"

Catatan perbaikan:
  - Memperbaiki bug SyntaxError terkait penggunaan `global REQUEST_DELAY` dengan memindahkan
    deklarasi global ke awal fungsi main() sebelum variabel tersebut direferensikan.
"""

import argparse
import json
import os
import re
import time
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ====== CONFIG ======
USER_AGENT = 'SkyrimItemGenerator/1.0 (+https://github.com/l500dt)'
REQUEST_DELAY = 1.0
TIMEOUT = 30
HEADERS = {'User-Agent': USER_AGENT}

# Regex heuristics to find FormID / IDs in page text
FORMID_PATTERNS = [
    re.compile(r'FormID[:\s]*([0-9A-Fa-f]{6,8})'),
    re.compile(r'ID[:\s]*([0-9A-Fa-f]{6,8})'),
    re.compile(r'0x([0-9A-Fa-f]{6,8})'),
    re.compile(r'\b([0-9A-Fa-f]{6,8})\b')
]

# ====== FUNCTIONS ======

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[ERROR] fetch {url}: {e}")
        return None


def extract_item_links(list_html, base_url):
    """Extract candidate item links from a UESP category page."""
    soup = BeautifulSoup(list_html, 'lxml')
    content = soup.find(id='mw-content-text') or soup
    links = []
    for a in content.find_all('a', href=True):
        href = a['href']
        # accept internal wiki links only
        if not href.startswith('/wiki/'):
            continue
        # skip namespace pages like File:, Category:, Help:
        path = href.split('/wiki/', 1)[1]
        if ':' in path:
            continue
        full = urljoin(base_url, href)
        text = a.get_text(strip=True)
        if text:
            links.append((text, full))
    # deduplicate preserving order
    seen = set(); uniq = []
    for name, url in links:
        if url in seen:
            continue
        seen.add(url); uniq.append((name, url))
    return uniq


def extract_name_and_formid(item_html):
    soup = BeautifulSoup(item_html, 'lxml')
    # name: prefer firstHeading
    name = ''
    h1 = soup.find(id='firstHeading')
    if h1:
        name = h1.get_text(strip=True)
    # get text for pattern matching
    text = soup.get_text(' ', strip=True)
    formid = ''
    # search patterns in order
    for pat in FORMID_PATTERNS:
        m = pat.search(text)
        if m:
            # get first non-empty group
            for g in m.groups():
                if g:
                    formid = g.upper().replace('0X', '')
                    break
        if formid:
            break
    # Try to find infobox/table rows labelled 'Form ID' or 'Item ID'
    if not formid:
        for th in soup.find_all(['th']):
            label = th.get_text(strip=True).lower()
            if 'formid' in label or 'form id' in label or 'item id' in label or label == 'id':
                td = th.find_next_sibling('td')
                if td:
                    txt = td.get_text(' ', strip=True)
                    m = re.search(r'([0-9A-Fa-f]{6,8})', txt)
                    if m:
                        formid = m.group(1).upper()
                        break
    # final fallback: look at first 800 chars
    if not formid:
        m = re.search(r'([0-9A-Fa-f]{6,8})', text[:800])
        if m:
            formid = m.group(1).upper()
    return name or '', formid or ''


def scrape_category(category_url, delay=REQUEST_DELAY, limit=None, cache_dir=None):
    print(f"Scraping category page: {category_url}")
    html = fetch(category_url)
    if not html:
        return []
    links = extract_item_links(html, category_url)
    print(f"  Found {len(links)} candidate links")

    items = []
    count = 0
    for title, link in links:
        if limit and count >= limit:
            break
        # build simple cache file path
        item_html = None
        cache_path = None
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', urlparse(link).path.strip('/'))
            cache_path = os.path.join(cache_dir, safe_name + '.html')
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    item_html = f.read()
        if not item_html:
            item_html = fetch(link)
            if item_html and cache_path:
                try:
                    with open(cache_path, 'w', encoding='utf-8') as f:
                        f.write(item_html)
                except Exception:
                    pass
        if not item_html:
            print(f"  - failed to fetch {link}")
            time.sleep(delay)
            continue
        name, formid = extract_name_and_formid(item_html)
        items.append({'name': name or title, 'form_id': formid, 'url': link})
        count += 1
        print(f"  + {name} ({formid})")
        time.sleep(delay)
    return items


# ====== MAIN ======

def main():
    # Move the global declaration BEFORE any reference to REQUEST_DELAY in this function
    global REQUEST_DELAY

    parser = argparse.ArgumentParser(description='Generate Skyrim items JSON by scraping UESP pages')
    parser.add_argument('--out', '-o', default='skyrim_items.json', help='Output JSON file')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY, help='Delay between requests (seconds)')
    parser.add_argument('--max-per-cat', type=int, default=0, help='Limit items per category (0 = all)')
    parser.add_argument('--resume', action='store_true', help='Resume from existing output file')
    parser.add_argument('--cache-dir', default='.cache_html', help='Directory to cache downloaded HTML pages')
    parser.add_argument('--category', '-c', action='append', help='Category URL(s). Can be used multiple times')
    args = parser.parse_args()

    # apply requested delay
    REQUEST_DELAY = args.delay

    default_categories = [
        ('weapons', 'https://en.uesp.net/wiki/Skyrim:Weapons'),
        ('armor', 'https://en.uesp.net/wiki/Skyrim:Armor'),
        ('potions', 'https://en.uesp.net/wiki/Skyrim:Alchemy'),
        ('ingredients', 'https://en.uesp.net/wiki/Skyrim:Ingredients'),
        ('books', 'https://en.uesp.net/wiki/Skyrim:Books'),
        ('spells', 'https://en.uesp.net/wiki/Skyrim:Spells'),
        ('misc', 'https://en.uesp.net/wiki/Skyrim:Misc_Items')
    ]

    categories = []
    if args.category:
        for c in args.category:
            # allow format name:url (e.g. weapons:https://...)
            if ':' in c and not c.startswith('http'):
                name, url = c.split(':', 1)
                categories.append((name.strip(), url.strip()))
            else:
                # assume it's a URL; derive a simple name
                try:
                    parsed = urlparse(c)
                    derived = os.path.basename(parsed.path.rstrip('/')) or 'category'
                except Exception:
                    derived = 'category'
                categories.append((derived.lower(), c))
    else:
        categories = default_categories

    out_data = defaultdict(list)
    if args.resume and os.path.exists(args.out):
        try:
            with open(args.out, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                for k, v in loaded.items():
                    out_data[k] = v
            print(f"Resuming from {args.out} (loaded categories: {list(out_data.keys())})")
        except Exception as e:
            print(f"Failed to load resume file: {e}")

    for name, url in categories:
        key = name.lower()
        existing_names = { (i.get('name') or '').lower() for i in out_data.get(key, []) }
        limit = args.max_per_cat or None
        items = scrape_category(url, delay=REQUEST_DELAY, limit=limit, cache_dir=args.cache_dir)
        for it in items:
            if (it.get('name') or '').lower() in existing_names:
                continue
            out_data[key].append(it)
        # save progress
        try:
            with open(args.out, 'w', encoding='utf-8') as f:
                json.dump(out_data, f, ensure_ascii=False, indent=2)
            print(f"Saved progress to {args.out}")
        except Exception as e:
            print(f"Failed to save {args.out}: {e}")

    print('Done. Output file:', args.out)


if __name__ == '__main__':
    main()
