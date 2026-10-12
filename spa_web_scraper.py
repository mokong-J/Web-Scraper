import json
import time
from pathlib import Path

import requests
import pandas as pd
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

url = "https://spa1.scrape.center/api/movie/?limit=10&offset=0"
headers = {"User-Agent": "personal-learning-scraper/1.0"}

failed_path = Path(__file__).parent / "progress" / "spa_failed.txt"
done_movie_path = Path(__file__).parent / "output" / "spa_done_movie.jsonl"
done_url_path = Path(__file__).parent / "progress" / "spa_done_url.json"
output_path = Path(__file__).parent / "output" / "spa_movies.xlsx"
report_path = Path(__file__).parent / "docs" / "spa_movie_report.txt"

config = {
    "max_retries": 3,
    "limit": 10,
    "max_page": 10,
    "page": 1,
}

stats = {
    "target": config["limit"] * config["max_page"],
    "offset": 0,
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
columns = ["name", "score", "duration"]

# ============== 初始化断点恢复 ==============
done_url_path.parent.mkdir(exist_ok=True)
# 当done_url_path为空或者不存在时，初始化为空的json字符串
if not done_url_path.exists() or not done_url_path.read_text(encoding="utf-8").strip():
    done_url_path.write_text("{}", encoding="utf-8")

done_movie_path.parent.mkdir(exist_ok=True)
done_movie_path.touch(exist_ok=True)

done_url = (
    json.loads(done_url_path.read_text(encoding="utf-8"))
    if done_url_path.read_text(encoding="utf-8")
    else {}
)

url, page = next(reversed(done_url.items()), (url, config["page"]))
page = int(page)

s = time.time()


def get_res_with_retry(url, max_retries):
    for attempt in range(1, max_retries + 1):
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            stats["retries"] += 1
            print(f"第{attempt}次获取失败：{e.__class__.__name__}")
            if attempt < max_retries:
                time.sleep(2 * attempt)
    return None


def one_page(res):
    results = res["results"]
    result_list = []
    for result in results:
        result_list.append(
            {
                "name": result["name"],
                "score": result["score"],
                "duration": str(result["minute"]) + "分钟",
            }
        )
    return result_list


def next_url(url, res):
    count = res["count"]
    results = res["results"]
    last_id = [result["id"] for result in results][-1]
    if int(count) - int(last_id) > 0:
        p = urlparse(url)
        q = dict(parse_qsl(p.query))
        q["offset"] = str(last_id)
        next_url = urlunparse(p._replace(query=urlencode(q)))
        return next_url
    return None


def register_failed(page, url):
    line = f"{page}: {url}"
    stats["failed_lines"].append(line)
    existing = failed_path.read_text(encoding="utf-8") if failed_path.exists() else ""
    if line not in existing:
        with open(failed_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


while url is not None:
    print(f"开始获取第{page}页数据")

    res = get_res_with_retry(url, config["max_retries"])

    if res is None:
        print(f"第{page}页重试{config['max_retries']}次失败，停止运行")
        register_failed(page, url)
        break

    if url in done_url:
        print(f"第{page}页已存在，跳过此页")
        url = next_url(url, res)
        if url:
            page += 1
        time.sleep(1)
        continue

    cards = one_page(res)
    if not cards:
        print(f"第{page}页未获取到数据, 停止运行")
        register_failed(page, url)
        break

    # 将已获取的数据存入文件中
    with open(done_movie_path, "a", encoding="utf-8") as f:
        for item in cards:
            f.writelines(json.dumps(item, ensure_ascii=False) + "\n")
    time.sleep(1)
    print(f"第{page}页获取完成！")

    # 将获取的url存入文件中
    done_url[url] = page
    with open(done_url_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(done_url, ensure_ascii=False) + "\n")
    url = next_url(url, res)
    if url:
        page += 1


# ============ 数据落地 ============
df = pd.read_json(done_movie_path, lines=True)
stats["rows"] = df.shape[0]
stats["passed"] = len(done_url)

print(f'数据获取完成，成功获取{stats["passed"]}页数据，共{stats["rows"]}条')
print(f'失败获取清单：{",".join(stats["failed_lines"])}')

if not stats["failed_lines"]:
    failed_path.write_text("", encoding="utf-8")


df["score"] = pd.to_numeric(df["score"], errors="coerce")

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
        f'目标页数：{config["max_page"]}，目标数据条数：{stats["target"]}',
        f'完成页数（含历史断点）：{stats["passed"]}，JSONL 原始行数：{stats["rows"]}（重跑叠加时大于清洗后条数）',
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
