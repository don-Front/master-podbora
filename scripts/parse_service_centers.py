"""Parse service center pages from turbo-don.ru into JSON structure."""
from __future__ import annotations

import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


class RegionParser(HTMLParser):
    """Parse dilery__group-region list into regions with centers."""

    def __init__(self) -> None:
        super().__init__()
        self.regions: list[dict] = []
        self._in_region_ul = False
        self._in_region_li = False
        self._in_region_span = False
        self._in_centers_ul = False
        self._in_center_li = False
        self._in_center_a = False
        self._current_center_href = ""
        self._current_region: dict | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class") or ""
        if tag == "ul" and "dilery__group-region" in cls:
            self._in_region_ul = True
        elif self._in_region_ul and tag == "li" and not self._in_region_li and not self._in_centers_ul:
            self._in_region_li = True
            self._current_region = {"name": "", "centers": []}
        elif self._in_region_li and tag == "span" and not self._in_centers_ul:
            self._in_region_span = True
            self._text_parts = []
        elif self._in_region_li and tag == "ul":
            self._in_centers_ul = True
        elif self._in_centers_ul and tag == "li":
            self._in_center_li = True
        elif self._in_center_li and tag == "a":
            self._in_center_a = True
            self._current_center_href = attrs_dict.get("href") or ""
            self._text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_center_a:
            name = "".join(self._text_parts).strip()
            if name and self._current_region is not None:
                center = {"name": name}
                href = (self._current_center_href or "").strip()
                if href:
                    center["url"] = href
                self._current_region["centers"].append(center)
            self._in_center_a = False
            self._current_center_href = ""
            self._text_parts = []
        elif tag == "li" and self._in_center_li:
            self._in_center_li = False
        elif tag == "span" and self._in_region_span:
            raw = "".join(self._text_parts).strip()
            raw = re.sub(r"\s+", " ", raw)
            if self._current_region is not None:
                self._current_region["name"] = raw
            self._in_region_span = False
            self._text_parts = []
        elif tag == "ul" and self._in_centers_ul and self._in_region_li:
            self._in_centers_ul = False
        elif tag == "li" and self._in_region_li and not self._in_centers_ul:
            if self._current_region and self._current_region["name"]:
                self.regions.append(self._current_region)
            self._in_region_li = False
            self._current_region = None
        elif tag == "ul" and self._in_region_ul:
            self._in_region_ul = False

    def handle_data(self, data: str) -> None:
        if self._in_region_span or self._in_center_a:
            self._text_parts.append(data)


def _parse_region_block(body: str) -> list[dict]:
    body = re.split(r'<div class="consultation|<form ', body, maxsplit=1)[0]
    parser = RegionParser()
    parser.feed(body)
    return parser.regions


def parse_countries(html: str) -> list[dict]:
    """Extract countries/regions/centers from dilery page HTML."""
    tab_names: list[str] = []
    tab_block = re.search(r'<div class="dilery__group-country">(.*?)</div>', html, re.DOTALL)
    if tab_block:
        tab_names = re.findall(r'<a[^>]*>([^<]+)</a>', tab_block.group(1))
        tab_names = [re.sub(r"\s+", " ", t.strip()) for t in tab_names]

    row_blocks: list[tuple[int, str]] = []
    for tab_num, body in re.findall(
        r'<div class="dilery__group-row[^"]*" id="tab(\d+)">(.*?)'
        r'(?=<div class="dilery__group-row|<div class="dilery__group-row_hei|<section class="forma__consultation|<form )',
        html,
        re.DOTALL,
    ):
        row_blocks.append((int(tab_num), body))

    hei_match = re.search(
        r'<div class="dilery__group-row_hei">(.*?)(?=</section>|<section class="forma__consultation|<form )',
        html,
        re.DOTALL,
    )
    if hei_match:
        row_blocks.append((len(tab_names) or len(row_blocks) + 1, hei_match.group(1)))

    countries: list[dict] = []
    for tab_num, body in sorted(row_blocks, key=lambda item: item[0]):
        idx = tab_num - 1
        country_name = tab_names[idx] if idx < len(tab_names) else f"tab{tab_num}"
        countries.append({"name": country_name, "regions": _parse_region_block(body)})
    return countries


def fetch_all_pages(base_url: str) -> list[dict]:
    """Fetch paginated archive and merge countries/regions/centers."""
    html = fetch_html(base_url)
    merged: dict[str, dict] = {}

    pages = [base_url]
    page_links = re.findall(rf'href="({re.escape(base_url.rstrip("/"))}/page/\d+/)"', html)
    for link in sorted(set(page_links), key=lambda u: int(re.search(r"/page/(\d+)/", u).group(1))):
        if link not in pages:
            pages.append(link)

    for url in pages:
        page_html = fetch_html(url) if url != base_url else html
        for country in parse_countries(page_html):
            cname = country["name"]
            if cname not in merged:
                merged[cname] = {"name": cname, "regions": {}}
            for region in country["regions"]:
                rname = region["name"]
                if rname not in merged[cname]["regions"]:
                    merged[cname]["regions"][rname] = {"name": rname, "centers": []}
                existing = {c["name"] for c in merged[cname]["regions"][rname]["centers"]}
                for center in region["centers"]:
                    if center["name"] not in existing:
                        merged[cname]["regions"][rname]["centers"].append(center)
                        existing.add(center["name"])
                    elif center.get("url"):
                        for stored in merged[cname]["regions"][rname]["centers"]:
                            if stored["name"] == center["name"] and not stored.get("url"):
                                stored["url"] = center["url"]
                                break

    return [{"name": c["name"], "regions": list(c["regions"].values())} for c in merged.values()]


def counts(countries: list[dict]) -> tuple[int, int, int]:
    n_countries = len(countries)
    n_regions = sum(len(c["regions"]) for c in countries)
    n_centers = sum(len(r["centers"]) for c in countries for r in c["regions"])
    return n_countries, n_regions, n_centers


def main() -> None:
    industrial_url = "https://www.turbo-don.ru/dilery/servisnyie-czentryi/"
    grand_url = "https://www.turbo-don.ru/dilery/servisnyie-czentryi-schetchikov-gaza-grand/"

    industrial_countries = fetch_all_pages(industrial_url)
    grand_countries = fetch_all_pages(grand_url)

    data = {
        "categories": {
            "industrial": {
                "id": "industrial",
                "title": "Сервисные центры по промышленной группе",
                "subtitle": "Сервисное обслуживание промышленного оборудования",
                "pageUrl": industrial_url,
                "countries": industrial_countries,
            },
            "grand": {
                "id": "grand",
                "title": "Сервисные центры счетчиков газа «Гранд»",
                "subtitle": "Сервисное обслуживание бытовых счетчиков газа «Гранд»",
                "pageUrl": grand_url,
                "countries": grand_countries,
            },
        }
    }

    out_path = Path(__file__).resolve().parents[1] / "back" / "chatbot" / "api" / "data" / "service_centers.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    for cat_id, cat in data["categories"].items():
        c, r, n = counts(cat["countries"])
        print(f"{cat_id}: countries={c}, regions={r}, centers={n}")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
