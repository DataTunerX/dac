"""
Wikisource API 数据抓取模块（中文维基文库等）
页面正文通过 wikipediaapi 访问 MediaWiki；API 主机为 *.wikisource.org。

实现见 skill_sdk.tool.wikimedia_scraper。
"""

from skill_sdk.tool.wikimedia_scraper import MediaWikiAdvancedScraper, MediaWikiScraper


class WikisourceScraper(MediaWikiScraper):
    """维基文库数据抓取器"""

    def __init__(self, language: str = "zh", user_agent: str = None):
        super().__init__(
            language,
            user_agent,
            api_domain="wikisource.org",
            default_user_agent="WikisourceScraper/1.0 (Educational Project; contact@example.com)",
        )


class WikisourceAdvancedScraper(WikisourceScraper, MediaWikiAdvancedScraper):
    """高级维基文库抓取器，提供额外的分析功能"""

    def __init__(self, language: str = "zh", user_agent: str = None):
        super().__init__(language, user_agent)


if __name__ == "__main__":
    scraper = WikisourceScraper(language="zh")

    print("=== 获取页面内容 ===")
    page = scraper.get_page("論語", full_metadata=True)
    if page:
        print(f"标题: {page['title']}")
        print(f"摘要: {page['summary'][:100]}...")
        print(f"章节数: {len(page['sections'])}")

    print("\n=== 搜索页面 ===")
    results = scraper.search_pages("論語", limit=5)
    for result in results:
        print(f"- {result['title']}: {result['snippet'][:50]}...")

    print("\n=== 批量获取摘要 ===")
    summaries = scraper.get_page_summaries(["論語", "史記", "詩經"])
    for title, data in summaries.items():
        print(f"- {title}: {data['extract'][:50]}...")

    print("\n=== 获取分类成员 ===")
    members = scraper.get_category_members("四書", limit=10)
    for member in members[:5]:
        print(f"- {member['title']}")

    print("\n=== 获取页面历史 ===")
    history = scraper.get_page_history("論語", limit=5)
    for edit in history:
        print(f"- {edit['user']} at {edit['timestamp']}")

    print("\n=== 随机页面 ===")
    random_pages = scraper.get_random_pages(3)
    for page in random_pages:
        print(f"- {page['title']}")

    print("\n=== 高级功能 ===")
    adv_scraper = WikisourceAdvancedScraper(language="zh")
    stats = adv_scraper.get_page_statistics("論語")
    print("页面统计:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    related = adv_scraper.find_related_pages("論語", depth=1, max_pages=5)
    print(f"直接相关页面: {len(related['direct_links'])}")
