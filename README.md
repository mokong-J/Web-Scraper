# 网页数据采集：1000 条图书 + 200 条电影（含断点续跑与质量报告）

> 三条爬虫完成静态页面与动态接口的完整采集流程：请求重试、断点续跑、失败登记、幂等去重、质量报告自动生成。1200 条数据账目可核，失败页与缺失值有归因。

## 解决什么问题

采集列表页数据时，多数问题出在异常发生之后：

- 请求未设超时：服务端无响应时程序永久阻塞，不报错也不退出
- HTTP 4xx/5xx 默认不抛异常：错误页混入解析流程，产出空值且难以定位原因
- 中断后从头重抓：抓 50 页断在第 49 页，已抓数据无法复用
- 重跑数据叠加：缺少去重时 JSONL 翻倍（本项目实测出现过 200 行）
- 失败页无记录：数据缺失无法解释，也无法定点补抓

**上述每个问题在本项目中都有对应机制**：请求统一带 `timeout=10`，失败自动重试 3 次（退避间隔 2/4/8 秒），`raise_for_status()` 将 4xx/5xx 归位到请求层；进度逐页落盘，中断后重跑自动跳过已完成页；数据落地前按业务列联合去重；失败页登记至独立文件；运行结束自动生成质量报告并保证账目自洽——目标条数 = 实收条数 + 失败/缺失解释。

## 输入 / 输出

**输入**：三个用于练习的沙箱站点（无需登录、无反爬对抗）

| 脚本 | 站点 | 类型 | 目标规模 | 字段 |
|---|---|---|---|---|
| `book_scraper.py` | books.toscrape.com | SSR 静态页 | 50 页 x 20 本 = 1000 | 书名 / 价格（£ 转 float）/ 评分（1-5 整数） |
| `movie_scraper.py` | ssr1.scrape.center | SSR 静态页 | 10 页 x 10 部 = 100 | 片名 / 评分（float）/ 片长 |
| `spa_web_scraper.py` | spa1.scrape.center | SPA 动态接口 | 10 页 x 10 部 = 100 | 片名 / 评分（float）/ 片长 |

**输出**（脚本运行时自动生成）：

- `output/books.xlsx`：1000 行图书数据；`output/books.jsonl`：原始抓取明细（一行一条 JSON，追加写入，中断不丢已抓数据）
- `output/movies.xlsx`：100 行电影数据（ssr1）；`output/movies.jsonl`：原始明细
- `output/spa_movies.xlsx`：100 行电影数据（spa1 接口）；`output/spa_done_movie.jsonl`：原始明细
- `progress/done_book_url.json`、`done_movie_url.json`、`spa_done_url.json`：断点进度（每页 URL + 页号）
- `progress/failed_book.txt`、`failed_movie.txt`、`spa_failed.txt`：失败登记（页号 + URL，各站独立命名，互不污染）
- `docs/books_report.txt`、`movie_report.txt`、`spa_movie_report.txt`：数据质量报告（每次运行覆盖刷新）

## 怎么运行

```powershell
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. 运行（三条爬虫相互独立，可单独执行）
python book_scraper.py
python movie_scraper.py
python spa_web_scraper.py
```

运行环境：**Python 3.9 及以上** / Windows（本机实测：Python 3.9 + pandas 1.5.3，解析器 lxml）

运行过程逐页打印进度、重试明细、重复数与缺失数，结束后打印质量报告全文并写入 `docs/`。中断后重新执行同一命令即可续传；全部完成后重跑只做翻页校验（已完成页不再重复收集），报告随运行刷新。

## 数据质量说明

**（实测数字，详见 docs/ 下三份报告）**

| 项目 | books.toscrape.com | ssr1.scrape.center | spa1.scrape.center |
|---|---|---|---|
| 目标条数 | 1000（50 页 x 20） | 100（10 页 x 10） | 100（10 页 x 10） |
| 实收（清洗后） | 1000 | 100 | 100 |
| 字段缺失 | 0 | 0 | score 缺 4 条（站点脏数据，见下） |
| 失败页 | 0 | 1（第 11 页，站点伪页，见下） | 0 |

**失败归因**：ssr1 站末页（第 10 页）仍渲染指向 `/page/11` 的 Next 链接，该页请求返回 500——浏览器直接访问同样 500，属站点自身问题。该站有效数据为 10 页共 100 部，第 11 页不构成数据缺失；失败记录保留在 `failed_movie.txt` 作为归因凭证。

**缺失归因**：spa1 接口返回的部分电影评分为空，`pd.to_numeric(errors="coerce")` 归为 NaN 后按机制删除（不静默补值）；105 行原始数据经缺失删除 4 条、去重 1 条后恰为 100 条，与目标一致，账目自洽。

**数据保障机制**

- [x] 请求带 `timeout=10`，失败重试 3 次、退避 2/4/8 秒
- [x] `raise_for_status()` 纳入 4xx/5xx，错误页不入数据
- [x] 重试耗尽登记失败文件后体面停止，已抓数据不丢失
- [x] 断点续跑跳过已完成页，不重复抓取
- [x] 落地前联合去重（keep=first）+ `isna()` 逐列缺失检查，不静默补值
- [x] 质量报告账目自洽校验（目标 = 实收 + 失败/缺失解释）

## SSR 与 SPA 采集方式对比

同一批电影数据，ssr1 与 spa1 给了两种形态，对应两种采集思路：

| 维度 | ssr1（SSR 服务端渲染） | spa1（SPA 前端渲染） |
|---|---|---|
| 数据位置 | 直接写在 HTML 源码里 | HTML 是空壳，页面 JS 调接口异步加载 |
| 请求目标 | 页面 URL（`/page/1.html`） | 数据接口（`/api/movie/?limit=10&offset=0`） |
| 解析方式 | BeautifulSoup + CSS 选择器抠 DOM 节点 | `res.json()` 后按 key 取值 |
| 翻页方式 | 解析页面里的 Next 链接（URL 路径递增） | 重写查询参数 `offset`（urlunparse） |
| 翻页依据 | 页面结构信号：Next 元素消失即末页 | 数据总量信号：`count - last_id <= 0` 即末页 |
| 解析依赖 | bs4 + lxml | 无需解析库，标准库 json 即可 |
| 典型报错 | NoneType（选择器未命中节点） | KeyError（接口字段缺失或改名） |

**如何找到数据接口**（SPA 站通用方法论）：Chrome 打开目标站 → F12 → Network 标签 → 刷新页面 → 筛选 XHR/Fetch → 找到返回 JSON 的请求 → 观察其 URL 与参数规律（`limit` 为每页条数，`offset` 为起始位置）。之后直接请求该接口，比解析渲染后的 HTML 更稳定。

**结论**：SPA 站点的采集核心从"解析 HTML"变为"找对接口、组织参数"；而主循环骨架——重试、断点、失败登记、去重、报告——在两种站点上完全同构复用。

## 合规说明

1. 只采集练习沙箱站（books.toscrape.com 标注 "We love being scraped!"，scrape.center 为爬虫练习靶场），不采集真实业务站点
2. 采集前查看目标站 `robots.txt`，遵守其爬取范围约定
3. User-Agent 诚实标识为 `personal-learning-scraper/1.0`，不伪装成浏览器
4. 不破解验证码、不绕过反爬、不采集需登录的数据；每页请求间隔 1 秒以上，控制请求频率

## 目录结构

```
03_web_scraper/
├── README.md
├── requirements.txt      # 依赖清单（xlsxwriter 需手动维护，见文件内注释）
├── LICENSE               # MIT
├── book_scraper.py       # 图书爬虫（SSR 静态页）
├── movie_scraper.py      # 电影爬虫（SSR 静态页）
├── spa_web_scraper.py    # 电影爬虫（SPA 动态接口）
├── output/               # 抓取产物：xlsx + jsonl（不进仓库）
├── progress/             # 断点进度、失败登记（不进仓库）
└── docs/                 # 数据质量报告（脚本自动生成）
```

## 已知限制

- ssr1 第 11 页伪链接是站点特性，每次重跑都会重试 3 次（含约 6 秒退避等待）后体面停止，属预期行为
- 断点续跑时已完成页会重新请求但跳过收集——下一页地址藏在本页 HTML 中，必须重抓才能翻页
- JSONL 为追加写入：若清空进度但保留 JSONL 重跑，数据会叠加；落地去重可兜底清除（实测 200 行去重回 100），如需完全干净可同时清空 `output/` 与 `progress/`
- spa1 的翻页依据是接口返回的总条数与末条 id 的差值，隐含"数据 id 连续"的前提；若站点数据出现删除导致 id 有空洞，按差值翻页可能漏抓，需改用 offset 步进累加的写法
- spa1 实测 JSONL 为 105 行，含调试期的实验叠加，已由落地去重与缺失删除兜底清洗至 100 条
- 目标规模写在各脚本 `config`（`max_pages` / `page_size` / `max_page` / `limit`），按站点当前结构实测得出；站点扩容后需同步修改
- `output/*.jsonl` 为空时直接运行脚本会报错终止（`read_json` 不接受空文件），属显式失败设计：重新执行一次抓取即可

## 联系方式

有类似的数据分析需求，或想让我按你的数据定制分析报告，欢迎联系：

- 📮 邮箱：1182618567@qq.com
- 💬 微信：wx_mokong-J

**我还能帮你做**
- 📊 多份 Excel 合并 / 清洗 / 透视分析
- 📈 数据可视化与趋势分析报告
- 🤖 报表自动化：每周手动做的表，一键生成
- 🕷️ 公开数据采集（合规范围内）

**交付标准**：含数据质量报告 + 非技术人员能看懂的使用说明 + 1 个月免费 bug 修复

## 许可证

MIT License — 可自由使用和修改，保留署名即可。
