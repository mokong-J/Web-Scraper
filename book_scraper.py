import json
import time
from pathlib import Path

import requests
import pandas as pd
from bs4 import BeautifulSoup as bs
from urllib.parse import urljoin

# ============ 配置 ============
url = "https://books.toscrape.com"
headers = {"User-Agent": "personal-learning-scraper/1.0"}
output_path = Path(__file__).parent / "output" / "books.xlsx"
progress = Path(__file__).parent / "progress" / "done_book_url.json"
data_path = Path(__file__).parent / "output" / "books.jsonl"
failed_path = Path(__file__).parent / "progress" / "failed_book.txt"
report_path = Path(__file__).parent / "docs" / "books_report.txt"

# 评分英文映射成数字
rating_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}

# 字段映射
selectors = {
    "cards": "article.product_pod",
    "score": ".star-rating",
    "title": "h3 a",
    "price": "p.price_color",
    "next": "li.next a",
}

config = {
    "max_pages": 50,
    "page_size": 20,
    "max_retries": 3,
    "pages": 1,
}

stats = {
    "target": config["max_pages"] * config["page_size"],
    "rows": 0,
    "missing": 0,
    "rows_na": 0,
    "dup": 0,
    "rows_after_clean": 0,
    "failed_lines": [],
    "passed": 0,
    "retries": 0,
}


# 列名
columns = ["title", "price", "rating"]

# ============ 初始化与断点恢复 ============
progress.parent.mkdir(exist_ok=True)
# 初始化progress文件，确保存在且内容为空
if not progress.exists() or not progress.read_text(encoding="utf-8").strip():
    progress.write_text("{}", encoding="utf-8")

data_path.parent.mkdir(exist_ok=True)
data_path.touch(exist_ok=True)

# 断点恢复：进度字典最后一项是上次最后完成的页
done_url = json.loads(progress.read_text(encoding="utf-8")) if progress.exists() else {}

url, page = next(reversed(done_url.items()), (url, config["pages"]))
page = int(page)
s = time.time()


# ============ 函数 ============
def get_res_with_retry(url, max_retries):
    """带重试与退避的页面请求。

    暂时性故障（超时、连接中断）值得重试，间隔逐次拉长给对方喘息；
    4xx/5xx 经 raise_for_status 抛异常后同样进入重试通道。

    Args:
        url: 目标页地址。
        max_retries: 最大重试次数。

    Returns:
        成功返回响应字节内容；全部尝试失败返回 None，由调用方登记并停止。
    """
    for attempt in range(1, max_retries + 1):
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()

            return res.content
        except Exception as e:
            stats["retries"] += 1
            print(f"第{attempt}次获取失败：{e.__class__.__name__}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
    return None


def get_next_url(current_url, res):
    """解析"下一页"链接并拼成绝对地址。

    只读页面结构、不发请求、不做解析数据；urljoin 按相对链接标准
    处理同目录、上级目录、根路径等各种 href 形态，换站无需改动。

    Args:
        current_url: 当前页完整地址，作为相对链接的解析基准。
        res: 当前页响应字节内容。

    Returns:
        下一页绝对 URL；没有"下一页"元素时返回 None（链条的自然终点）。
    """
    soup = bs(res, "lxml")
    a = soup.select_one(selectors["next"])
    if a is None:
        return None

    return urljoin(current_url, a.get("href"))


def one_page(res):
    """解析单页，返回本页全部记录。

    职责边界：只负责"给数据"——每张卡片产出一个字典，字段与配置区
    selectors 一一对应；不打印进度、不写文件。返回空列表通常意味着
    页面无数据，是否算失败由调用方判断。

    Args:
        res: 页面响应字节内容。

    Returns:
        字典列表，每个字典对应一条记录；无数据时为空列表。
    """
    soup = bs(res, "lxml")
    articles = soup.select(selectors["cards"])

    result_list = []
    for article in articles:
        star = article.select_one(selectors["score"]).get("class")[1].lower()
        rating = rating_map[star]
        result_list.append(
            {
                "title": article.select_one(selectors["title"]).get("title"),
                "price": article.select_one(selectors["price"]).get_text(strip=True),
                "rating": rating,
            }
        )
    return result_list


def register_failed(page, url):
    """失败登记（去重）：同一页同一URL只登记一次。

    失败信息落盘作为质量报告素材与人工排查入口；登记是追加式账本，
    与断点进度相互独立，登记失败不影响已抓数据。
    """
    line = f"{page}: {url}"
    stats["failed_lines"].append(line)
    existing = failed_path.read_text(encoding="utf-8") if failed_path.exists() else ""
    if line not in existing:
        with open(failed_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ============ 抓取主循环 ============
while url:

    print(f"开始获取第{page}页数据")
    res = get_res_with_retry(url, config["max_retries"])
    if res is None:

        register_failed(page, url)
        print(f"第{page}页重试{config['max_retries']}次失败，停止运行")
        break

    # 如果当前页数据已存在，跳过收集，仅翻页
    if url in done_url:
        print(f"第{page}页数据已存在，跳过")
        url = get_next_url(url, res)
        if url:
            page += 1
        time.sleep(1)
        continue

    cards = one_page(res)
    if not cards:
        print(f"第{page}页未获取到数据")
        register_failed(page, url)
        break

    # 写入数据到文件，以便后续继续获取
    with open(data_path, "a", encoding="utf-8") as f:
        for item in cards:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"第{page}页数据获取完成！")

    # 将已获取的URL记录到文件中，以便后续继续获取
    done_url[url] = page
    with open(progress, "w", encoding="utf-8") as f:
        f.write(json.dumps(done_url, ensure_ascii=False) + "\n")
    time.sleep(1)

    url = get_next_url(url, res)
    if url:
        page += 1


# ============ 数据落地 ============
df = pd.read_json(data_path, lines=True)
stats["rows"] = df.shape[0]
stats["passed"] = len(done_url)

print(f'数据获取完成，成功获取{stats["passed"]}页数据，共{stats["rows"]}条')
print(f'失败获取清单：{",".join(stats["failed_lines"])}')

if not stats["failed_lines"]:
    failed_path.write_text("", encoding="utf-8")

df["price"] = pd.to_numeric(
    df["price"].astype(str).str.strip().str.replace("£", "", regex=False),
    errors="coerce",
).astype("float64")
df["rating"] = df["rating"].astype("Int64")

# 缺失数据处理，删除包含缺失值的行
stats["missing"] = df.isna().sum()
df = df.dropna(subset=columns, how="any", inplace=False)
rows_after_na = df.shape[0]
stats["rows_na"] = stats["rows"] - rows_after_na
print(f'缺失数据数量：\n{stats["missing"]}')

# 重复数据处理，删除重复记录
stats["dup"] = df.duplicated(subset=columns).sum()
print(f'重复数据数量：{stats["dup"]}')
df = df.drop_duplicates(subset=columns, keep="first")

stats["rows_after_clean"] = df.shape[0]


if stats["rows_after_clean"] == stats["target"]:
    print_info = (
        f'清洗后数据{stats["rows_after_clean"]}条，与目标数据{stats["target"]}条数一致'
    )
else:
    print_info = f'清洗后数据{stats["rows_after_clean"]}条，与目标数据{stats["target"]}条数不一致，请检查数据是否完整'

print(print_info)

with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
    df.to_excel(writer, index=False)

report = "\n".join(
    [
        "==================== 数据质量报告 ====================",
        f'目标页数：{config["max_pages"]}，目标数据条数：{stats["target"]}',
        f'完成页数（含历史断点）： {stats[ "passed" ]} ，JSONL 原始行数： {stats[ "rows" ]} （重跑叠加时大于清洗后条数）',
        f'缺失数据条数：{stats["rows_na"]}',
        f'缺失数据数量：\n{stats["missing"]}',
        f'重复记录：{stats["dup"]}',
        f'获取失败页数：{len(stats["failed_lines"])}',
        f'失败获取清单：\n{",".join(stats["failed_lines"])}',
        f'请求失败次数（含重试）：{stats["retries"]}',
        f"{print_info}",
        "=====================================================",
    ]
)
print(report)
with open(report_path, "w", encoding="utf-8") as f:
    f.write(report)

print(f"任务共耗时{time.time() - s:.2f}s")
