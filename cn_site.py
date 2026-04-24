# 对每个网站的结构定制抓取的标签策略
ARTICLE_SELECTORS = {
    "chinadaily.com.cn": [
        "#Content p",
        ".article p",
        "article p",
    ],
    "xinhuanet.com": [
        "#detail p",
        ".main-article p",
        "article p",
        "main p",
    ],
    "news.cn": [
        "#detail p",
        ".main-article p",
        "article p",
        "main p",
    ],
    "globaltimes.cn": [
        "div.article_right div.article_content p",
        "div.article_content p",
        "article p",
    ],
    "cgtn.com": [
        "div.cg-article-content p",
        "div.news-content p",
        "article p",
        "main p",
    ],
    "people.cn": [
        "div.w860 p",
        "div.rm_txt_con p",
        "article p",
        "main p",
    ],
    "ecns.cn": [
        "div#left_content p",
        ".left_content p",
        "article p",
    ],
    "shine.cn": [
        "div.article-content p",
        "article p",
        "main p",
    ],
}

# 抓取初步筛选（国内可直连）
FEEDS = [
    {
        "name": "China Daily Culture",
        "source": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/china_rss.xml",
        "topic": "society",
    },
    {
        "name": "China Daily World",
        "source": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/world_rss.xml",
        "topic": "society",
    },
    {
        "name": "China Daily Business",
        "source": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/bizchina_rss.xml",
        "topic": "economy",
    },
    {
        "name": "China Daily Culture",
        "source": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/culture_rss.xml",
        "topic": "culture",
    },
    {
        "name": "Xinhua World",
        "source": "Xinhua",
        "url": "http://www.xinhuanet.com/english/rss/worldrss.xml",
        "topic": "society",
    },
    {
        "name": "Xinhua Sci-Tech",
        "source": "Xinhua",
        "url": "http://www.xinhuanet.com/english/rss/sci-techrss.xml",
        "topic": "technology",
    },
    {
        "name": "Global Times Society",
        "source": "Global Times",
        "url": "https://www.globaltimes.cn/rss/china.xml",
        "topic": "society",
    },
    {
        "name": "CGTN World",
        "source": "CGTN",
        "url": "https://www.cgtn.com/subscribe/rss/section/world.xml",
        "topic": "society",
    },
    {
        "name": "CGTN Tech",
        "source": "CGTN",
        "url": "https://www.cgtn.com/subscribe/rss/section/tech.xml",
        "topic": "technology",
    },
    {
        "name": "People's Daily English",
        "source": "People's Daily",
        "url": "http://en.people.cn/rss/90000.xml",
        "topic": "society",
    },
    {
        "name": "ECNS",
        "source": "ECNS",
        "url": "http://www.ecns.cn/rss/rss.xml",
        "topic": "society",
    },
    {
        "name": "SHINE Shanghai",
        "source": "SHINE",
        "url": "https://www.shine.cn/rss/feed.xml",
        "topic": "culture",
    },
]