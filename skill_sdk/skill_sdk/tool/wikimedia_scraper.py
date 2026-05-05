"""
Wikimedia / MediaWiki 站点共用抓取实现（维基百科、维基教科书、维基文库等）。

Wikipedia-API 0.14+ 仅内置 {lang}.wikipedia.org；其它域名通过子类覆盖 _build_url。
"""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional, Type

import requests
import wikipediaapi


# 直连 Wikimedia 时偶发 SSLEOFError / Connection reset，做有限次退避重试
_DEFAULT_HTTP_TIMEOUT = 30.0
_DEFAULT_HTTP_RETRIES = 5
_DEFAULT_HTTP_BACKOFF = 0.75


@lru_cache(maxsize=16)
def _wikipedia_client_class(domain: str) -> Type[wikipediaapi.Wikipedia]:
    """返回指向 https://{lang}.{domain}/w/api.php 的 Wikipedia API 客户端类。"""
    d = domain.strip().lower()
    if d == "wikipedia.org":
        return wikipediaapi.Wikipedia

    class _CustomWikipedia(wikipediaapi.Wikipedia):
        @staticmethod
        def _build_url(language: str) -> str:
            lang = (language or "en").strip().lower()
            return f"https://{lang}.{d}/w/api.php"

    _CustomWikipedia.__name__ = f"_MediaWiki_{d.replace('.', '_')}"
    return _CustomWikipedia


class MediaWikiScraper:
    """通用 MediaWiki 抓取器；通过 api_domain 区分站点。"""

    def __init__(
        self,
        language: str = "zh",
        user_agent: Optional[str] = None,
        *,
        api_domain: str,
        default_user_agent: str,
        http_timeout: float = _DEFAULT_HTTP_TIMEOUT,
        http_retries: int = _DEFAULT_HTTP_RETRIES,
        http_backoff: float = _DEFAULT_HTTP_BACKOFF,
    ):
        if user_agent is None:
            user_agent = default_user_agent
        self.language = language
        self.user_agent = user_agent
        self._api_domain = api_domain.strip().lower()
        self._http_timeout = http_timeout
        self._http_retries = max(1, http_retries)
        self._http_backoff = http_backoff
        wiki_cls = _wikipedia_client_class(self._api_domain)
        self.wiki = wiki_cls(language=language, user_agent=user_agent)
        self.request_delay = 0.1

    def _api_url(self) -> str:
        lang = (self.language or "en").strip().lower()
        return f"https://{lang}.{self._api_domain}/w/api.php"

    def _api_request_get(self, params: Dict[str, Any]) -> requests.Response:
        """对 MediaWiki API 发 GET；对 TLS/连接类错误与 5xx 做退避重试。"""
        url = self._api_url()
        headers = {"User-Agent": self.user_agent}
        last_exc: Optional[BaseException] = None

        for attempt in range(self._http_retries):
            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self._http_timeout,
                )
                if resp.status_code >= 500 and attempt + 1 < self._http_retries:
                    time.sleep(self._http_backoff * (2**attempt))
                    continue
                resp.raise_for_status()
                return resp
            except requests.exceptions.HTTPError as e:
                last_exc = e
                code = e.response.status_code if e.response is not None else 0
                if code >= 500 and attempt + 1 < self._http_retries:
                    time.sleep(self._http_backoff * (2**attempt))
                    continue
                raise
            except (
                requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                last_exc = e
                if attempt + 1 < self._http_retries:
                    time.sleep(self._http_backoff * (2**attempt))
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("api request failed without exception")

    def get_page(
        self,
        title: str,
        *,
        full_metadata: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        获取页面内容。默认 full_metadata=False 以减少 API 请求。
        """
        page = self.wiki.page(title)

        if not page.exists():
            print(f"页面 '{title}' 不存在")
            return None

        _rev_id = getattr(page, "lastrevid", None) or getattr(page, "revision_id", None)

        page_data: Dict[str, Any] = {
            "title": page.title,
            "pageid": page.pageid,
            "ns": page.ns,
            "summary": page.summary or "",
            "full_text": page.text,
            "url": page.fullurl,
            "canonical_url": page.canonicalurl,
            "language": page.language,
            "last_modified": str(_rev_id) if _rev_id else None,
        }

        if full_metadata:
            page_data["categories"] = list(page.categories.keys())
            page_data["links"] = list(page.links.keys())
            page_data["backlinks"] = list(page.backlinks.keys())
            page_data["sections"] = self._get_sections(page)
            page_data["images"] = list(page.images.keys()) if hasattr(page, "images") else []
            page_data["references"] = (
                list(page.references.keys()) if hasattr(page, "references") else []
            )
        else:
            page_data["categories"] = []
            page_data["links"] = []
            page_data["backlinks"] = []
            page_data["sections"] = []
            page_data["images"] = []
            page_data["references"] = []

        time.sleep(self.request_delay)
        return page_data

    def _get_sections(self, page) -> List[Dict[str, Any]]:
        sections: List[Dict[str, Any]] = []

        def extract_sections(sections_list, parent_sections):
            for section in sections_list:
                section_info = {
                    "title": section.title,
                    "level": section.level,
                    "text": section.text or "",
                }
                parent_sections.append(section_info)
                if len(section.sections) > 0:
                    section_info["subsections"] = []
                    extract_sections(section.sections, section_info["subsections"])

        extract_sections(page.sections, sections)
        return sections

    def search_pages(self, query: str, limit: int = 10) -> List[Dict[str, str]]:
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": min(limit, 50),
        }

        try:
            response = self._api_request_get(params)
            data = response.json()

            results = []
            for item in data.get("query", {}).get("search", []):
                results.append(
                    {
                        "title": item["title"],
                        "pageid": item["pageid"],
                        "snippet": self._clean_html(item.get("snippet", "")),
                        "timestamp": item.get("timestamp", ""),
                        "size": item.get("size", 0),
                        "word_count": item.get("wordcount", 0),
                    }
                )

            time.sleep(self.request_delay)
            return results

        except requests.exceptions.RequestException as e:
            print(f"搜索请求失败: {e}")
            return []

    def get_page_summaries(self, titles: List[str]) -> Dict[str, Dict[str, Any]]:
        batch_size = 50
        all_results: Dict[str, Dict[str, Any]] = {}

        for i in range(0, len(titles), batch_size):
            batch_titles = titles[i : i + batch_size]
            params = {
                "action": "query",
                "format": "json",
                "prop": "extracts|info|pageimages",
                "exintro": True,
                "explaintext": True,
                "inprop": "url",
                "titles": "|".join(batch_titles),
                "pithumbsize": 200,
            }

            try:
                response = self._api_request_get(params)
                data = response.json()

                pages = data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    title = page_data.get("title", "")
                    all_results[title] = {
                        "pageid": page_data.get("pageid"),
                        "title": title,
                        "extract": page_data.get("extract", ""),
                        "url": page_data.get("fullurl", ""),
                        "thumbnail": page_data.get("thumbnail", {}).get("source", ""),
                    }

                time.sleep(self.request_delay)

            except requests.exceptions.RequestException as e:
                print(f"批量获取摘要失败: {e}")
                continue

        return all_results

    def get_category_members(
        self, category_name: str, limit: int = 100, namespace: int = 0
    ) -> List[Dict[str, Any]]:
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": f"Category:{category_name}",
            "cmlimit": min(limit, 500),
            "cmnamespace": namespace,
        }

        try:
            response = self._api_request_get(params)
            data = response.json()

            members = []
            for member in data.get("query", {}).get("categorymembers", []):
                members.append(
                    {
                        "pageid": member["pageid"],
                        "title": member["title"],
                        "ns": member["ns"],
                        "type": self._get_namespace_name(member["ns"]),
                    }
                )

            time.sleep(self.request_delay)
            return members

        except requests.exceptions.RequestException as e:
            print(f"获取分类成员失败: {e}")
            return []

    def _get_namespace_name(self, namespace_id: int) -> str:
        namespace_map = {
            0: "article",
            1: "talk",
            2: "user",
            3: "user_talk",
            4: "project",
            5: "project_talk",
            6: "file",
            7: "file_talk",
            8: "mediawiki",
            9: "mediawiki_talk",
            10: "template",
            11: "template_talk",
            12: "help",
            13: "help_talk",
            14: "category",
            15: "category_talk",
        }
        return namespace_map.get(namespace_id, "unknown")

    def get_page_history(self, title: str, limit: int = 10) -> List[Dict[str, Any]]:
        params = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "titles": title,
            "rvlimit": min(limit, 50),
            "rvprop": "user|timestamp|comment|size",
        }

        try:
            response = self._api_request_get(params)
            data = response.json()

            pages = data.get("query", {}).get("pages", {})
            history = []

            for page_id, page_data in pages.items():
                for rev in page_data.get("revisions", []):
                    history.append(
                        {
                            "user": rev.get("user", ""),
                            "timestamp": rev.get("timestamp", ""),
                            "comment": rev.get("comment", ""),
                            "size": rev.get("size", 0),
                        }
                    )

            time.sleep(self.request_delay)
            return history

        except requests.exceptions.RequestException as e:
            print(f"获取页面历史失败: {e}")
            return []

    def get_random_pages(self, count: int = 5) -> List[Dict[str, Any]]:
        params = {
            "action": "query",
            "format": "json",
            "list": "random",
            "rnlimit": count,
            "rnnamespace": 0,
        }

        try:
            response = self._api_request_get(params)
            data = response.json()

            random_pages = []
            for page in data.get("query", {}).get("random", []):
                random_pages.append(
                    {"id": page["id"], "title": page["title"], "ns": page["ns"]}
                )

            return random_pages

        except requests.exceptions.RequestException as e:
            print(f"获取随机页面失败: {e}")
            return []

    @staticmethod
    def _clean_html(html_text: str) -> str:
        clean = re.compile("<.*?>")
        return re.sub(clean, "", html_text)

    def save_to_file(self, data: Any, filename: str):
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"数据已保存到 {filename}")
        except Exception as e:
            print(f"保存文件失败: {e}")

    def get_page_infobox(self, title: str) -> Dict[str, str]:
        page = self.wiki.page(title)
        if not page.exists():
            return {}

        text = page.text
        infobox_data: Dict[str, str] = {}
        infobox_pattern = r"\{\{Infobox[^}]*?\n(.*?)\n\}\}"
        matches = re.findall(infobox_pattern, text, re.DOTALL | re.IGNORECASE)

        if matches:
            for match in matches:
                lines = match.split("\n")
                for line in lines:
                    field_match = re.match(r"\|\s*(\w+)\s*=\s*(.+)", line.strip())
                    if field_match:
                        key = field_match.group(1).strip()
                        value = field_match.group(2).strip()
                        value = re.sub(r"\[\[|\]\]", "", value)
                        value = re.sub(r"\{\{.*?\}\}", "", value)
                        infobox_data[key] = value

        return infobox_data


class MediaWikiAdvancedScraper(MediaWikiScraper):
    """在通用抓取器之上提供统计与链接图分析。"""

    def get_page_statistics(self, title: str) -> Dict[str, Any]:
        page_data = self.get_page(title, full_metadata=True)
        if not page_data:
            return {}

        full_text = page_data.get("full_text", "")

        return {
            "title": title,
            "character_count": len(full_text),
            "word_count": len(full_text.split())
            if self.language in ["en"]
            else len(full_text),
            "line_count": full_text.count("\n"),
            "section_count": len(page_data.get("sections", [])),
            "link_count": len(page_data.get("links", [])),
            "category_count": len(page_data.get("categories", [])),
            "image_count": len(page_data.get("images", [])),
            "reading_time_minutes": max(1, round(len(full_text.split()) / 200))
            if self.language in ["en"]
            else max(1, round(len(full_text) / 500)),
        }

    def find_related_pages(
        self, title: str, depth: int = 1, max_pages: int = 20
    ) -> Dict[str, List[str]]:
        related: Dict[str, List[str]] = {"direct_links": [], "second_level_links": []}
        page = self.wiki.page(title)

        if not page.exists():
            return related

        direct_links = list(page.links.keys())[:max_pages]
        related["direct_links"] = direct_links

        if depth > 1:
            second_level = set()
            for link in direct_links[:5]:
                linked_page = self.wiki.page(link)
                if linked_page.exists():
                    second_links = list(linked_page.links.keys())[:5]
                    second_level.update(second_links)
                time.sleep(self.request_delay)

            second_level = second_level - set(direct_links) - {title}
            related["second_level_links"] = list(second_level)[:max_pages]

        return related
