import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from skill_sdk.tool.wikisource import WikisourceScraper

# 每条搜索结果拉取页面后，正文仅保留前 N 个字符（Python str 下标，Unicode 码位）
PAGE_FULL_TEXT_MAX_CHARS = 1000


def test_search_pages():
    """简单测试搜索功能"""

    print("初始化 Wikisource 抓取器...")
    scraper = WikisourceScraper(language="zh")

    print("\n" + "=" * 50)
    print("测试1: 搜索 '論語'")
    print("=" * 50)

    results = scraper.search_pages("論語", limit=10)

    if results:
        print(f"找到 {len(results)} 个结果:\n")
        for i, result in enumerate(results, 1):
            print(f"{i}. 标题: {result['title']}")
            print(f"   页面ID: {result['pageid']}")
            print(f"   摘要: {result['snippet'][:100]}...")
            print(f"   字数: {result['word_count']}")
            print(f"   大小: {result['size']} 字节")
            print()
    else:
        print("未找到结果")


def test_get_page():
    """
    先 search_pages，再对每条命中 get_page；正文仅保留前 PAGE_FULL_TEXT_MAX_CHARS 字。
    """
    print("\n" + "=" * 50)
    print(
        "测试: search_pages → 对全部结果 get_page "
        f"（正文最多保留前 {PAGE_FULL_TEXT_MAX_CHARS} 字）"
    )
    print("=" * 50)

    scraper = WikisourceScraper(language="zh")
    query = "論語"
    results = scraper.search_pages(query, limit=5)

    if not results:
        print("search_pages 无结果，跳过 get_page")
        return

    print(f"搜索词: {query!r} → 共 {len(results)} 条，将依次拉取页面\n")

    for idx, hit in enumerate(results, 1):
        title = hit["title"]
        print("\n" + "=" * 50)
        print(f"[{idx}/{len(results)}] 标题: {title!r}")
        print("=" * 50)

        try:
            page = scraper.get_page(title)
        except Exception as e:
            print(f"get_page 失败: {e}")
            continue

        if not page:
            print("页面不存在或获取失败")
            continue

        full = page["full_text"] or ""
        clipped = full[:PAGE_FULL_TEXT_MAX_CHARS]
        omitted = len(full) - len(clipped)

        print(f"页面ID: {page['pageid']}（默认不拉链接/分类/章节等元数据）")
        print("\n" + "-" * 50)
        print("摘要（维基 API 简介）")
        print("-" * 50)
        print(page["summary"])
        print("\n" + "-" * 50)
        print(
            f"正文（前 {PAGE_FULL_TEXT_MAX_CHARS} 字；全文共 {len(full)} 字，已省略 {max(0, omitted)} 字）"
        )
        print("-" * 50)
        print(clipped)


def test_save_results():
    """测试保存搜索结果到文件"""

    print("\n" + "=" * 50)
    print("额外测试: 保存搜索结果到JSON文件")
    print("=" * 50)

    scraper = WikisourceScraper(language="zh")

    results = scraper.search_pages("史記", limit=10)

    if results:
        filename = "wikisource_search_results.json"
        scraper.save_to_file(results, filename)
        print(f"已保存 {len(results)} 个搜索结果到 {filename}")

        import os

        if os.path.exists(filename):
            file_size = os.path.getsize(filename)
            print(f"文件大小: {file_size} 字节")
            print("保存成功 ✓")
        else:
            print("保存失败 ✗")


if __name__ == "__main__":
    print("Wikisource API 简单测试脚本")
    print("=" * 50)

    # test_search_pages()
    test_get_page()
    # test_save_results()

    print("\n测试完成!")
