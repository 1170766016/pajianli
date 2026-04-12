# 前程无忧企业版爬虫模块 - 实现计划

## 整体思路

```
手动登录(保存Cookie) → 搜索简历列表 → 逐个打开简历详情 → 保存HTML → 丢给现有筛选流程
```

## 技术选型：Playwright（浏览器自动化）

**为什么不用 requests？**
- 前程无忧有 JS 渲染 + 反爬检测，纯 HTTP 请求搞不定
- Playwright 操控真实浏览器，像真人一样操作，被检测概率低

**为什么不用 Selenium？**
- Playwright 更现代、更快、API 更好用、反检测支持更好

## 反封策略

| 策略 | 实现方式 |
|------|---------|
| 手动登录 | 第一次打开真实浏览器让用户手动登录，保存 Cookie |
| Session 复用 | 保存登录状态到文件，后续自动加载，不用反复登录 |
| 随机延迟 | 每个操作间隔 3-8 秒随机延迟 |
| 模拟真人 | 用有头模式（非 headless），模拟鼠标移动和滚动 |
| 反检测补丁 | 使用 playwright-stealth 隐藏自动化痕迹 |
| 限速保护 | 可配置每批下载数量和间隔，默认保守 |

## 用户使用流程

```
第1步：python scraper.py login          ← 打开浏览器，手动登录，保存 Cookie
第2步：python scraper.py search "Python 开发"  ← 搜索简历，显示列表
第3步：python scraper.py download --max 50    ← 下载简历到 resumes/ 目录
第4步：python app.py                      ← 用现有系统筛选评分
```

## 具体变更

### [NEW] scraper.py — 爬虫主模块

核心功能：
1. `login()` — 打开浏览器让用户手动登录，登录成功后保存 Cookie 到 `session.json`
2. `search(keyword, ...)` — 加载 Cookie → 进入简历搜索页 → 输入搜索条件 → 获取结果列表
3. `download(max_count)` — 遍历搜索结果 → 打开每份简历详情页 → 保存 HTML 到 `resumes/`
4. 反封控制：随机延迟、鼠标模拟、Stealth 补丁

### [MODIFY] requirements.txt
- 新增 `playwright` 依赖

### [MODIFY] config.py
- 新增爬虫相关配置（延迟范围、下载数量限制等）

## 风险提醒

> [!WARNING]
> 前程无忧明确禁止自动化抓取，使用爬虫有账号被封风险。建议：
> 1. 控制速度，不要一次抓太多
> 2. 使用有头模式，必要时人工介入
> 3. 跟甲方沟通好风险

## 验证方式

1. 运行 `python scraper.py login` 测试登录保存
2. 运行 `python scraper.py search "关键词"` 测试搜索
3. 运行 `python scraper.py download --max 5` 小批量测试下载
4. 确认下载的 HTML 文件能被现有 `resume_parser.py` 正确解析
