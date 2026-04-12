"""
前程无忧企业版 (ehire) 简历爬虫模块
使用 Playwright 浏览器自动化，模拟真人操作

用法：
    python scraper.py login                      # 第一步：手动登录并保存 Cookie
    python scraper.py search "Python 开发"       # 第二步：搜索简历
    python scraper.py download --max 20          # 第三步：下载简历到 resumes/
    python scraper.py export                     # 第四步：清洗 HTML → 干净文本
    python scraper.py pipeline "Python" --max 10 # 一键：搜索 → 下载 → 分析
    python scraper.py status                     # 查看当前状态
"""
import argparse
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Windows 终端 UTF-8 编码支持
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config


# ============================================================
# 日志配置
# ============================================================

def _setup_logger():
    """配置日志系统：同时输出到控制台和文件"""
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"scraper_{datetime.now().strftime('%Y%m%d')}.log")

    logger = logging.getLogger("scraper")
    logger.setLevel(logging.DEBUG)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 文件 handler（记录所有级别）
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    ))

    # 控制台 handler（只显示 INFO 以上）
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


log = _setup_logger()


# ============================================================
# 工具函数
# ============================================================

def random_delay(min_sec=None, max_sec=None):
    """随机延迟，模拟真人操作节奏"""
    min_sec = min_sec or config.SCRAPER_MIN_DELAY
    max_sec = max_sec or config.SCRAPER_MAX_DELAY
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)
    return delay


def human_type(page, selector, text, delay_per_char=None):
    """模拟人类打字速度"""
    element = page.locator(selector)
    element.click()
    element.fill("")  # 清空
    for char in text:
        element.type(char, delay=random.randint(50, 200) if delay_per_char is None else delay_per_char)
    random_delay(0.3, 0.8)


def random_scroll(page):
    """随机滚动页面，模拟真人浏览"""
    scroll_y = random.randint(200, 600)
    page.mouse.wheel(0, scroll_y)
    random_delay(0.5, 1.5)


def random_mouse_move(page):
    """随机移动鼠标，模拟真人行为"""
    x = random.randint(100, 1200)
    y = random.randint(100, 600)
    page.mouse.move(x, y)
    random_delay(0.1, 0.3)


def safe_filename(name: str) -> str:
    """将字符串转为安全的文件名"""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name[:100] if len(name) > 100 else name


def print_banner(title: str):
    """打印操作标题"""
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}\n")


def url_hash(url: str) -> str:
    """生成 URL 的短哈希，用于去重"""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def retry_with_backoff(func, max_retries=3, base_delay=2, description="操作"):
    """
    带指数退避的重试装饰器

    Args:
        func: 要重试的函数 (callable)
        max_retries: 最大重试次数
        base_delay: 基础延迟秒数
        description: 操作描述（用于日志）

    Returns:
        函数执行结果
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                log.warning(f"⚠️ {description} 失败 (第{attempt+1}次), {delay:.1f}秒后重试: {e}")
                time.sleep(delay)
            else:
                log.error(f"❌ {description} 最终失败 (已重试{max_retries}次): {e}")
    raise last_error


# ============================================================
# 下载历史管理（去重核心）
# ============================================================

class DownloadHistory:
    """管理已下载简历的记录，避免重复下载"""

    def __init__(self):
        self.history_file = os.path.join(os.path.dirname(__file__), "download_history.json")
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.isfile(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"downloaded": {}, "failed": {}, "stats": {"total_success": 0, "total_failed": 0}}

    def _save(self):
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def is_downloaded(self, url: str) -> bool:
        """检查是否已下载过"""
        key = url_hash(url)
        return key in self._data["downloaded"]

    def mark_downloaded(self, url: str, name: str, filepath: str):
        """标记为已下载"""
        key = url_hash(url)
        self._data["downloaded"][key] = {
            "name": name,
            "url": url,
            "filepath": filepath,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._data["stats"]["total_success"] = len(self._data["downloaded"])
        self._save()

    def mark_failed(self, url: str, name: str, error: str):
        """标记为下载失败"""
        key = url_hash(url)
        self._data["failed"][key] = {
            "name": name,
            "url": url,
            "error": error,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._data["stats"]["total_failed"] = len(self._data["failed"])
        self._save()

    def get_stats(self) -> dict:
        return self._data["stats"]

    def get_downloaded_count(self) -> int:
        return len(self._data["downloaded"])

    def get_failed_list(self) -> list:
        return list(self._data["failed"].values())

    def clear_failed(self):
        """清除失败记录（用于重试）"""
        self._data["failed"] = {}
        self._data["stats"]["total_failed"] = 0
        self._save()


# ============================================================
# 核心：浏览器管理
# ============================================================

class EhireScraper:
    """前程无忧企业版爬虫"""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._search_results = []  # 缓存搜索结果
        self._history = DownloadHistory()

    def _start_browser(self, use_session=True):
        """
        启动浏览器（使用本地 Edge，无需额外下载）

        Args:
            use_session: 是否加载已保存的登录状态
        """
        from playwright.sync_api import sync_playwright

        self.playwright = sync_playwright().start()

        # 使用持久化上下文（保留浏览器数据，更像真人）
        os.makedirs(config.BROWSER_DATA_DIR, exist_ok=True)

        launch_args = {
            "channel": "msedge",  # 使用本地 Edge 浏览器，无需下载 Chromium
            "headless": config.SCRAPER_HEADLESS,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
                "--disable-extensions",
            ],
            "viewport": {"width": 1366, "height": 768},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
        }

        # 如果有已保存的 session，加载它
        if use_session and os.path.isfile(config.SESSION_FILE):
            launch_args["storage_state"] = config.SESSION_FILE
            log.info(f"✅ 已加载登录状态: {config.SESSION_FILE}")

        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=config.BROWSER_DATA_DIR,
            **launch_args,
        )

        # 应用反检测补丁
        self._apply_stealth()

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # 设置默认超时
        self.page.set_default_timeout(20000)

    def _apply_stealth(self):
        """应用反检测脚本，隐藏自动化痕迹"""
        stealth_js = """
        // 隐藏 webdriver 标志
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        
        // 隐藏自动化相关属性
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        
        // 伪造 chrome 对象
        window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} };
        
        // 伪造 plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        
        // 伪造语言
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en'],
        });
        
        // 伪造 permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // 伪造 Connection
        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 100,
                downlink: 10,
                saveData: false,
            }),
        });
        """
        self.context.add_init_script(stealth_js)

    def _close_browser(self):
        """关闭浏览器"""
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass

    def _save_session(self):
        """保存当前登录状态到文件"""
        if self.context:
            self.context.storage_state(path=config.SESSION_FILE)
            log.info(f"💾 登录状态已保存到: {config.SESSION_FILE}")

    def _check_login(self) -> bool:
        """检查是否已登录"""
        try:
            self.page.goto(config.EHIRE_URL, wait_until="domcontentloaded", timeout=15000)
            random_delay(2, 3)

            # 检查是否在登录页（URL 包含 login 关键词说明未登录）
            current_url = self.page.url.lower()
            if "login" in current_url or "passport" in current_url:
                return False

            # 检查页面上是否有登录后的特征元素
            # 前程无忧企业版登录后通常有"退出"或用户名元素
            try:
                self.page.wait_for_selector(
                    "text=退出, text=注销, .user-name, .username, #logout",
                    timeout=5000
                )
                return True
            except Exception:
                pass

            # 如果 URL 不含 login 且页面正常加载，可能也是已登录
            if "ehire.51job.com" in current_url and "login" not in current_url:
                return True

            return False
        except Exception as e:
            log.warning(f"⚠️ 检查登录状态失败: {e}")
            return False

    def _refresh_session_if_needed(self) -> bool:
        """
        检测当前页面是否因 session 过期被踢回登录页，
        如果是则尝试重新加载 session。

        Returns:
            True 表示 session 仍然有效或已恢复，False 表示无法恢复
        """
        current_url = self.page.url.lower()
        if "login" in current_url or "passport" in current_url:
            log.warning("⚠️ 检测到 session 过期，尝试恢复...")
            # 尝试重新加载 cookie
            if os.path.isfile(config.SESSION_FILE):
                try:
                    with open(config.SESSION_FILE, "r", encoding="utf-8") as f:
                        state = json.load(f)
                    for cookie in state.get("cookies", []):
                        self.context.add_cookies([cookie])
                    self.page.reload()
                    random_delay(2, 3)

                    new_url = self.page.url.lower()
                    if "login" not in new_url and "passport" not in new_url:
                        log.info("✅ Session 恢复成功")
                        return True
                except Exception as e:
                    log.error(f"Session 恢复失败: {e}")

            log.error("❌ 登录状态已过期，请重新执行: python scraper.py login")
            return False
        return True

    def _simulate_human_behavior(self):
        """模拟一些人类浏览行为，降低被检测风险"""
        actions = [
            lambda: random_mouse_move(self.page),
            lambda: random_scroll(self.page),
            lambda: self.page.mouse.move(
                random.randint(200, 1000), random.randint(200, 600)
            ),
        ]
        action = random.choice(actions)
        try:
            action()
        except Exception:
            pass

    # ============================================================
    # 命令1：手动登录
    # ============================================================

    def login(self):
        """
        打开浏览器让用户手动登录
        登录成功后自动保存 Cookie
        """
        print_banner("📋 前程无忧企业版 - 手动登录")
        print("操作步骤：")
        print("  1. 浏览器会自动打开前程无忧登录页面")
        print("  2. 请手动输入甲方的企业账号和密码")
        print("  3. 完成验证码等安全验证")
        print("  4. 登录成功后，回到终端按 Enter 键保存登录状态")
        print("  5. 之后的搜索和下载操作会自动使用保存的登录状态\n")

        try:
            self._start_browser(use_session=False)

            # 打开登录页
            self.page.goto(config.EHIRE_URL, wait_until="domcontentloaded", timeout=30000)
            log.info("🌐 浏览器已打开，请手动登录...\n")

            # 等待用户手动操作
            input("👆 登录完成后，请按 Enter 键保存登录状态...")

            # 检查是否真的登录了
            current_url = self.page.url.lower()
            if "login" in current_url or "passport" in current_url:
                print("⚠️ 看起来还没有登录成功，请确认已登录后重试")
                input("如果已经登录，请再按一次 Enter...")

            # 保存登录状态
            self._save_session()
            log.info("\n✅ 登录状态保存成功！现在可以使用 search 和 download 命令了。")

        except Exception as e:
            log.error(f"❌ 登录过程出错: {e}")
        finally:
            self._close_browser()

    # ============================================================
    # 命令2：搜索简历
    # ============================================================

    def search(self, keyword: str, city: str = "", work_years: str = "",
               education: str = "", max_pages: int = 3):
        """
        搜索简历，返回搜索结果列表

        Args:
            keyword: 搜索关键词（如 "Python 开发"）
            city: 城市筛选（如 "上海"）
            work_years: 工作年限筛选
            education: 学历筛选
            max_pages: 最多翻几页
        """
        print_banner(f"🔍 搜索简历: {keyword}")

        if not os.path.isfile(config.SESSION_FILE):
            log.error("❌ 未找到登录状态，请先执行: python scraper.py login")
            return []

        try:
            self._start_browser(use_session=True)

            # 检查登录状态
            if not self._check_login():
                log.error("❌ 登录状态已过期，请重新执行: python scraper.py login")
                return []

            log.info("✅ 登录状态有效\n")

            # 进入简历搜索页
            log.info("📄 正在打开简历搜索页...")
            self.page.goto(config.EHIRE_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
            random_delay(2, 4)

            # 模拟人类行为
            self._simulate_human_behavior()

            # 输入搜索关键词
            log.info(f"🔑 输入关键词: {keyword}")
            self._input_search_keyword(keyword)

            # 可选：设置筛选条件
            if city:
                self._set_filter("city", city)
            if work_years:
                self._set_filter("work_years", work_years)
            if education:
                self._set_filter("education", education)

            # 点击搜索
            self._click_search()
            random_delay(3, 5)

            # 收集搜索结果
            all_results = []
            for page_num in range(1, max_pages + 1):
                log.info(f"\n📃 正在读取第 {page_num} 页...")

                # 模拟人类浏览
                self._simulate_human_behavior()

                page_results = self._parse_search_results()

                if not page_results:
                    log.info(f"   第 {page_num} 页没有结果，停止翻页")
                    break

                all_results.extend(page_results)
                log.info(f"   找到 {len(page_results)} 条结果 (累计 {len(all_results)})")

                # 翻到下一页
                if page_num < max_pages:
                    has_next = self._goto_next_page()
                    if not has_next:
                        log.info("   已到最后一页")
                        break
                    random_delay(config.SCRAPER_PAGE_DELAY, config.SCRAPER_PAGE_DELAY + 3)

            # 保存搜索结果
            self._search_results = all_results
            result_file = os.path.join(os.path.dirname(__file__), "search_results.json")
            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)

            log.info(f"\n✅ 搜索完成！共找到 {len(all_results)} 份简历")
            log.info(f"💾 结果已保存到: {result_file}")

            # 打印摘要
            self._print_search_summary(all_results)

            return all_results

        except Exception as e:
            log.error(f"❌ 搜索过程出错: {e}")
            log.debug(traceback.format_exc())
            return []
        finally:
            self._close_browser()

    def _input_search_keyword(self, keyword: str):
        """在搜索框输入关键词"""
        # 尝试多种可能的搜索框选择器
        selectors = [
            "#KeywordBox",
            "#txtKeyword",
            "input[name='keyword']",
            "input[name='txtKeyword']",
            "input[placeholder*='关键']",
            "input[placeholder*='搜索']",
            "input[placeholder*='职位']",
            "input[placeholder*='技能']",
            ".search-input input",
            "#searchKeyword",
            ".keyword-input input",
            "input.search-key",
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click()
                    el.fill("")
                    el.type(keyword, delay=random.randint(80, 180))
                    log.debug(f"   ✅ 已输入关键词 (选择器: {sel})")
                    return
            except Exception:
                continue

        # 如果上面都不行，尝试通用方法
        log.warning("   ⚠️ 未找到搜索框，尝试通用方法...")
        try:
            # 找第一个可见的 text input
            inputs = self.page.locator("input[type='text']:visible")
            if inputs.count() > 0:
                inputs.first.click()
                inputs.first.fill(keyword)
                log.info("   ✅ 已通过通用方法输入关键词")
            else:
                log.error("   ❌ 未找到任何可用的搜索输入框")
        except Exception as e:
            log.error(f"   ❌ 输入关键词失败: {e}")

    def _set_filter(self, filter_type: str, value: str):
        """设置筛选条件（尽力而为，不影响主流程）"""
        try:
            log.info(f"   设置筛选: {filter_type} = {value}")
            # 前程无忧的筛选条件通常是下拉框或链接
            # 这里用通用策略：查找包含目标文本的可点击元素
            self.page.locator(f"text={value}").first.click(timeout=3000)
            random_delay(1, 2)
        except Exception:
            log.warning(f"   ⚠️ 筛选条件 {filter_type} 设置失败，跳过")

    def _click_search(self):
        """点击搜索按钮"""
        selectors = [
            "#btn_search",
            "#btnSearch",
            "button:has-text('搜索')",
            "button:has-text('搜 索')",
            "input[type='button'][value*='搜索']",
            "input[type='submit'][value*='搜索']",
            "a:has-text('搜索')",
            "a:has-text('搜 索')",
            ".btn-search",
            ".search-btn",
            "button.search",
            "#search-btn",
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click()
                    log.debug(f"   ✅ 已点击搜索 (选择器: {sel})")
                    return
            except Exception:
                continue
        log.warning("   ⚠️ 未找到搜索按钮，尝试按 Enter")
        self.page.keyboard.press("Enter")

    def _parse_search_results(self) -> list:
        """
        解析当前页面的搜索结果列表
        返回 [{name, url, title, experience, education, location, update_time}, ...]
        """
        results = []
        random_delay(1, 2)

        # 尝试多种可能的结果列表选择器
        row_selectors = [
            ".el_resume",           # 常见的简历行
            ".resume-item",
            ".search-result-item",
            "tr.e_resItem",
            ".list-item",
            "table.search_result tr",
            "#resultList .item",
            ".resume_list .resume",
            ".resume-list-item",
            "div[class*='resume'] div[class*='item']",
            "table.list tr[id]",
            ".table_list tr",
        ]

        rows = None
        used_selector = None
        for sel in row_selectors:
            try:
                candidate = self.page.locator(sel)
                count = candidate.count()
                if count > 0:
                    rows = candidate
                    used_selector = sel
                    break
            except Exception:
                continue

        if not rows or rows.count() == 0:
            # 最后尝试：直接从页面提取所有链接
            log.warning("   ⚠️ 未匹配到标准结果列表，尝试通用提取...")
            return self._parse_results_generic()

        log.debug(f"   使用选择器: {used_selector}, 找到 {rows.count()} 行")

        for i in range(rows.count()):
            try:
                row = rows.nth(i)
                result = {}

                # 提取姓名和链接
                name_link = row.locator("a").first
                if name_link.count() > 0:
                    result["name"] = name_link.inner_text(timeout=2000).strip()
                    href = name_link.get_attribute("href", timeout=2000)
                    if href:
                        if not href.startswith("http"):
                            href = f"https://ehire.51job.com{href}"
                        result["url"] = href

                # 提取其他信息（尽力而为）
                text = row.inner_text(timeout=2000)
                result["raw_text"] = text
                result["index"] = len(results)

                # 尝试从文本中提取结构化信息
                self._extract_result_info(result, text)

                if result.get("name") or result.get("url"):
                    results.append(result)
            except Exception:
                continue

        return results

    def _extract_result_info(self, result: dict, text: str):
        """从搜索结果行文本中提取结构化信息"""
        # 提取工作年限
        years_match = re.search(r'(\d+)\s*年', text)
        if years_match:
            result["work_years"] = f"{years_match.group(1)}年"

        # 提取学历
        for edu in ["博士", "硕士", "本科", "大专", "中专", "高中"]:
            if edu in text:
                result["education"] = edu
                break

        # 提取地区
        cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京",
                  "武汉", "西安", "苏州", "天津", "重庆", "长沙", "郑州"]
        for city in cities:
            if city in text:
                result["location"] = city
                break

        # 提取更新时间
        time_match = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', text)
        if time_match:
            result["update_time"] = time_match.group(1)

    def _parse_results_generic(self) -> list:
        """通用方法提取搜索结果（备选方案）"""
        results = []
        try:
            # 获取页面中所有指向简历详情的链接
            links = self.page.locator(
                "a[href*='Resume'], a[href*='resume'], a[href*='ViewResume'], "
                "a[href*='ResumeView'], a[href*='candidateDetail']"
            )
            for i in range(links.count()):
                try:
                    link = links.nth(i)
                    name = link.inner_text(timeout=2000).strip()
                    href = link.get_attribute("href", timeout=2000)

                    if name and href and len(name) <= 20:
                        if not href.startswith("http"):
                            href = f"https://ehire.51job.com{href}"
                        results.append({
                            "name": name,
                            "url": href,
                            "index": len(results),
                        })
                except Exception:
                    continue
        except Exception:
            pass
        return results

    def _goto_next_page(self) -> bool:
        """翻到下一页，返回是否成功"""
        try:
            next_selectors = [
                "a:has-text('下一页')",
                "a:has-text('>')",
                "a:has-text('»')",
                ".next a",
                "a.next",
                ".pager a:last-child",
                "li.next a",
                "a.page-next",
                "button:has-text('下一页')",
                ".pagination .next",
            ]
            for sel in next_selectors:
                try:
                    el = self.page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        el.click()
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def _print_search_summary(self, results: list):
        """打印搜索结果摘要"""
        if not results:
            return
        print(f"\n{'─'*60}")
        print(f"  序号  姓名           学历     年限   简历链接")
        print(f"{'─'*60}")
        for i, r in enumerate(results[:20]):  # 只显示前 20 条
            name = r.get("name", "未知")[:10].ljust(10)
            edu = r.get("education", "-").ljust(4)
            years = r.get("work_years", "-").ljust(4)
            url_short = "✅ 有链接" if r.get("url") else "❌ 无链接"
            already = " (已下载)" if r.get("url") and self._history.is_downloaded(r["url"]) else ""
            print(f"  {i+1:>3}   {name}     {edu}   {years} {url_short}{already}")
        if len(results) > 20:
            print(f"  ... 还有 {len(results) - 20} 条未显示")
        print(f"{'─'*60}")

    # ============================================================
    # 命令3：下载简历
    # ============================================================

    def download(self, max_count: int = None, skip_downloaded: bool = True,
                 format_preference: str = "html"):
        """
        下载搜索到的简历

        Args:
            max_count: 最多下载数量，默认使用配置
            skip_downloaded: 是否跳过已下载的简历
            format_preference: 优先下载格式 ("html", "pdf", "word")
        """
        max_count = max_count or config.SCRAPER_MAX_PER_BATCH

        print_banner(f"📥 下载简历 (最多 {max_count} 份)")

        # 加载搜索结果
        result_file = os.path.join(os.path.dirname(__file__), "search_results.json")
        if not os.path.isfile(result_file):
            log.error('❌ 未找到搜索结果，请先执行: python scraper.py search "关键词"')
            return

        with open(result_file, "r", encoding="utf-8") as f:
            results = json.load(f)

        if not results:
            log.error("❌ 搜索结果为空")
            return

        # 筛选有链接的结果
        downloadable = [r for r in results if r.get("url")]
        if not downloadable:
            log.error("❌ 没有可下载的简历（缺少简历链接）")
            return

        # 去重：跳过已下载的
        if skip_downloaded:
            original_count = len(downloadable)
            downloadable = [r for r in downloadable if not self._history.is_downloaded(r["url"])]
            skipped = original_count - len(downloadable)
            if skipped > 0:
                log.info(f"⏩ 跳过 {skipped} 份已下载的简历")

        if not downloadable:
            log.info("✅ 所有简历已下载完毕，无需重复下载")
            return

        to_download = downloadable[:max_count]
        log.info(f"📋 共 {len(downloadable)} 份待下载，本次下载 {len(to_download)} 份\n")

        if not os.path.isfile(config.SESSION_FILE):
            log.error("❌ 未找到登录状态，请先执行: python scraper.py login")
            return

        try:
            self._start_browser(use_session=True)

            # 检查登录
            if not self._check_login():
                log.error("❌ 登录状态已过期，请重新执行: python scraper.py login")
                return

            log.info("✅ 登录状态有效\n")
            os.makedirs(config.RESUME_DIR, exist_ok=True)

            success_count = 0
            fail_count = 0
            skip_count = skipped if skip_downloaded and 'skipped' in locals() else 0

            for i, item in enumerate(to_download):
                name = item.get("name", f"未知_{i}")
                url = item["url"]

                log.info(f"[{i+1}/{len(to_download)}] 正在下载: {name} ...")

                try:
                    # 使用重试机制下载
                    filepath = retry_with_backoff(
                        func=lambda u=url, n=name, fmt=format_preference: self._download_single_resume(u, n, fmt),
                        max_retries=2,
                        base_delay=3,
                        description=f"下载 {name}",
                    )

                    if filepath:
                        log.info(f"   ✅ 已保存: {os.path.basename(filepath)}")
                        self._history.mark_downloaded(url, name, filepath)
                        success_count += 1
                    else:
                        log.warning(f"   ⚠️ 下载结果为空")
                        self._history.mark_failed(url, name, "下载结果为空")
                        fail_count += 1

                except Exception as e:
                    log.error(f"   ❌ 失败: {e}")
                    self._history.mark_failed(url, name, str(e))
                    fail_count += 1

                # 随机延迟，防止被封
                if i < len(to_download) - 1:
                    delay = random_delay()
                    # 每 10 份简历额外休息一下
                    if (i + 1) % 10 == 0:
                        extra_delay = random.uniform(10, 20)
                        log.info(f"   ⏸️  已下载 {i+1} 份，休息 {extra_delay:.0f} 秒...")
                        time.sleep(extra_delay)

                    # 偶尔模拟一下人类行为
                    if random.random() < 0.3:
                        self._simulate_human_behavior()

            # 保存 session（可能有更新的 cookie）
            self._save_session()

            print(f"\n{'='*55}")
            print(f"  ✅ 下载完成: 成功 {success_count} 份, 失败 {fail_count} 份")
            if skip_count > 0:
                print(f"  ⏩ 跳过已下载: {skip_count} 份")
            print(f"  📁 简历目录: {config.RESUME_DIR}")
            print(f"  📊 历史累计: {self._history.get_downloaded_count()} 份")
            print(f"{'='*55}")
            print(f"\n💡 下一步:")
            print(f"   运行 python scraper.py export  — 清洗 HTML 为干净文本")
            print(f"   运行 python app.py             — 启动筛选系统进行评分")

        except Exception as e:
            log.error(f"❌ 下载过程出错: {e}")
            log.debug(traceback.format_exc())
        finally:
            self._close_browser()

    def _download_single_resume(self, url: str, name: str, format_pref: str = "html") -> str:
        """
        下载单份简历，返回保存的文件路径

        策略优先级：
        1. 尝试点击页面上的「下载简历」按钮获取 PDF/Word
        2. 如果失败，提取页面中的简历内容保存为 HTML
        3. 兜底：保存完整页面 HTML

        Args:
            url: 简历详情页 URL
            name: 候选人姓名
            format_pref: 偏好格式 ("html", "pdf", "word")

        Returns:
            保存的文件路径
        """
        # 打开简历详情页
        self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
        random_delay(2, 4)

        # 检查 session 是否过期
        if not self._refresh_session_if_needed():
            raise Exception("登录状态已过期")

        # 等待页面加载完成
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            log.debug("   networkidle 超时，继续处理")

        # 策略1：尝试下载 PDF/Word 文件
        if format_pref in ("pdf", "word"):
            downloaded_file = self._try_click_download_button(name)
            if downloaded_file:
                return downloaded_file

        # 策略2：提取简历主体内容保存为 HTML
        resume_html = self._extract_resume_content()

        if not resume_html or len(resume_html) < 200:
            # 兜底：保存完整页面
            log.debug("   主体提取失败，保存完整页面")
            resume_html = self.page.content()

        if len(resume_html) < 500:
            raise Exception("页面内容过少，可能需要重新登录")

        # 保存为 HTML 文件
        filename = safe_filename(f"{name}_简历") + ".html"
        filepath = os.path.join(config.RESUME_DIR, filename)

        # 避免重复文件名
        counter = 1
        while os.path.exists(filepath):
            filename = safe_filename(f"{name}_简历_{counter}") + ".html"
            filepath = os.path.join(config.RESUME_DIR, filename)
            counter += 1

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(resume_html)

        return filepath

    def _try_click_download_button(self, name: str) -> str:
        """
        尝试点击页面上的下载按钮，获取 PDF/Word 格式简历

        Returns:
            下载文件的路径，失败返回 None
        """
        download_selectors = [
            "a:has-text('下载简历')",
            "button:has-text('下载简历')",
            "a:has-text('下载')",
            "button:has-text('下载')",
            "a:has-text('导出简历')",
            "button:has-text('导出')",
            "a.download",
            ".btn-download",
            "#btnDownload",
            "a[href*='download']",
            "a[href*='Download']",
            "a[href*='export']",
            "a.resume-download",
        ]

        for sel in download_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=2000):
                    # 使用 expect_download 来捕获下载
                    with self.page.expect_download(timeout=15000) as download_info:
                        el.click()

                    download = download_info.value
                    # 保存到目标目录
                    ext = Path(download.suggested_filename).suffix or ".pdf"
                    filename = safe_filename(f"{name}_简历") + ext
                    filepath = os.path.join(config.RESUME_DIR, filename)

                    # 避免重复
                    counter = 1
                    while os.path.exists(filepath):
                        filename = safe_filename(f"{name}_简历_{counter}") + ext
                        filepath = os.path.join(config.RESUME_DIR, filename)
                        counter += 1

                    download.save_as(filepath)
                    log.info(f"   📎 成功下载文件: {filename}")
                    return filepath

            except Exception as e:
                log.debug(f"   下载按钮 {sel} 尝试失败: {e}")
                continue

        log.debug("   未找到可用的下载按钮")
        return None

    def _extract_resume_content(self) -> str:
        """
        从简历详情页中智能提取简历主体内容 HTML
        过滤掉导航栏、侧边栏、广告等无关内容
        """
        try:
            # 尝试匹配前程无忧简历详情页的主体内容区域
            content_selectors = [
                ".resume-detail",
                ".resume-content",
                "#resumeDetail",
                "#resume_detail",
                "#divResume",
                ".r_content",
                ".resume-main",
                ".cv-detail",
                ".cv-content",
                "#resume-box",
                "div[class*='resume'][class*='detail']",
                "div[class*='resume'][class*='content']",
                "div[id*='resume']",
                ".main-content",
                "#main_content",
                "div.detail-content",
            ]

            for sel in content_selectors:
                try:
                    el = self.page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        html = el.inner_html(timeout=5000)
                        if len(html) > 200:
                            log.debug(f"   ✅ 提取简历内容 (选择器: {sel}, 长度: {len(html)})")
                            # 包装成完整的 HTML
                            return self._wrap_resume_html(html)
                except Exception:
                    continue

            # 备选方案：移除导航/广告，保留主体
            log.debug("   未匹配到简历内容区域，使用清洗策略")
            return self._clean_full_page_html()

        except Exception as e:
            log.debug(f"   简历内容提取失败: {e}")
            return None

    def _wrap_resume_html(self, body_html: str) -> str:
        """将提取的简历内容包装成完整的 HTML 文档"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>简历</title>
    <style>
        body {{ font-family: "微软雅黑", "Microsoft YaHei", sans-serif; padding: 20px; line-height: 1.6; }}
        table {{ border-collapse: collapse; width: 100%; }}
        td, th {{ padding: 8px; border: 1px solid #ddd; }}
    </style>
</head>
<body>
{body_html}
</body>
</html>"""

    def _clean_full_page_html(self) -> str:
        """
        清洗完整页面 HTML，移除无关元素（导航、广告、脚本等）
        """
        try:
            # 在页面上执行 JS，移除无关元素后获取 HTML
            cleaned_html = self.page.evaluate("""
            () => {
                // 要移除的元素选择器
                const removeSelectors = [
                    'nav', 'header', 'footer',
                    '.nav', '.navbar', '.header', '.footer',
                    '.sidebar', '.side-bar',
                    '.ad', '.ads', '.advertisement',
                    'script', 'style', 'iframe',
                    '.menu', '.top-bar', '.bottom-bar',
                    '.breadcrumb', '.login-bar',
                    '#header', '#footer', '#nav', '#sidebar',
                    '.toolbar', '.tool-bar',
                    '[class*="banner"]',
                    '[class*="popup"]', '[class*="modal"]',
                    '[class*="toast"]', '[class*="alert"]',
                ];
                
                const doc = document.cloneNode(true);
                
                removeSelectors.forEach(sel => {
                    try {
                        doc.querySelectorAll(sel).forEach(el => el.remove());
                    } catch(e) {}
                });
                
                return doc.documentElement.outerHTML;
            }
            """)
            return cleaned_html
        except Exception as e:
            log.debug(f"   页面清洗失败: {e}")
            return self.page.content()

    # ============================================================
    # 命令4：导出/清洗简历
    # ============================================================

    def export(self, source_dir: str = None, output_dir: str = None):
        """
        将下载的 HTML 简历清洗为纯文本格式，
        便于后续的 LLM 分析和解析

        Args:
            source_dir: 源目录（HTML 简历），默认 config.RESUME_DIR
            output_dir: 输出目录，默认在 source_dir 下创建 cleaned/ 子目录
        """
        source_dir = source_dir or config.RESUME_DIR
        output_dir = output_dir or os.path.join(source_dir, "cleaned")

        print_banner("🧹 清洗简历 HTML → 纯文本")

        if not os.path.isdir(source_dir):
            log.error(f"❌ 简历目录不存在: {source_dir}")
            return

        # 查找 HTML 文件
        html_files = list(Path(source_dir).glob("*.html")) + list(Path(source_dir).glob("*.htm"))

        if not html_files:
            log.error(f"❌ 未找到 HTML 简历文件: {source_dir}")
            return

        os.makedirs(output_dir, exist_ok=True)

        log.info(f"📄 找到 {len(html_files)} 个 HTML 文件")
        log.info(f"📂 输出目录: {output_dir}\n")

        success = 0
        for file_path in html_files:
            try:
                text = self._html_to_clean_text(str(file_path))

                if len(text.strip()) < 30:
                    log.warning(f"   ⚠️ {file_path.name}: 提取文本过少，跳过")
                    continue

                # 保存为 txt
                txt_name = file_path.stem + ".txt"
                txt_path = os.path.join(output_dir, txt_name)
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(text)

                log.info(f"   ✅ {file_path.name} → {txt_name} ({len(text)} 字)")
                success += 1

            except Exception as e:
                log.error(f"   ❌ {file_path.name}: {e}")

        log.info(f"\n✅ 清洗完成！成功处理 {success}/{len(html_files)} 个文件")
        log.info(f"📂 输出目录: {output_dir}")

    def _html_to_clean_text(self, file_path: str) -> str:
        """
        将 HTML 简历文件转换为干净的纯文本

        处理逻辑：
        1. 移除 script/style/meta 等无关标签
        2. 保留表格结构（简历常用表格排版）
        3. 合并多余空行
        4. 去除乱码和特殊字符
        """
        from bs4 import BeautifulSoup

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()

        soup = BeautifulSoup(html, "lxml")

        # 移除无用标签
        for tag in soup(["script", "style", "meta", "link", "noscript",
                         "nav", "footer", "header", "iframe"]):
            tag.decompose()

        # 移除隐藏元素
        for tag in soup.find_all(style=re.compile(r'display\s*:\s*none', re.I)):
            tag.decompose()

        # 处理表格：将单元格用 | 分隔
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                cells = [c for c in cells if c]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                table.replace_with(soup.new_string("\n".join(rows) + "\n"))

        # 提取文本
        text = soup.get_text(separator="\n", strip=True)

        # 清理
        text = re.sub(r'\n{3,}', '\n\n', text)           # 合并多余空行
        text = re.sub(r'[ \t]{2,}', ' ', text)           # 合并多余空格
        text = re.sub(r'[^\S\n]+', ' ', text)            # 标准化空白字符
        text = re.sub(r'(?:^[ \t]+|[ \t]+$)', '', text, flags=re.MULTILINE)  # 去除行首行尾空格

        # 移除常见的网站噪音文本
        noise_patterns = [
            r'前程无忧.*?版权所有',
            r'Copyright.*?51job\.com',
            r'请使用.*?浏览器',
            r'该简历来自.*',
            r'刷新时间[：:]\s*\d+.*',
        ]
        for pattern in noise_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        return text.strip()

    # ============================================================
    # 命令5：重试失败的下载
    # ============================================================

    def retry_failed(self, max_count: int = None):
        """
        重试之前下载失败的简历

        Args:
            max_count: 最多重试数量
        """
        failed_list = self._history.get_failed_list()

        if not failed_list:
            log.info("✅ 没有失败的下载需要重试")
            return

        max_count = max_count or len(failed_list)
        to_retry = failed_list[:max_count]

        print_banner(f"🔄 重试失败的下载 ({len(to_retry)} 份)")

        if not os.path.isfile(config.SESSION_FILE):
            log.error("❌ 未找到登录状态，请先执行: python scraper.py login")
            return

        try:
            self._start_browser(use_session=True)

            if not self._check_login():
                log.error("❌ 登录状态已过期，请重新执行: python scraper.py login")
                return

            log.info("✅ 登录状态有效\n")
            os.makedirs(config.RESUME_DIR, exist_ok=True)

            success_count = 0
            for i, item in enumerate(to_retry):
                name = item.get("name", f"未知_{i}")
                url = item["url"]

                log.info(f"[{i+1}/{len(to_retry)}] 重试: {name} ...")

                try:
                    filepath = self._download_single_resume(url, name)
                    if filepath:
                        log.info(f"   ✅ 已保存: {os.path.basename(filepath)}")
                        self._history.mark_downloaded(url, name, filepath)
                        success_count += 1
                    else:
                        log.warning(f"   ⚠️ 重试失败")
                except Exception as e:
                    log.error(f"   ❌ 重试失败: {e}")

                if i < len(to_retry) - 1:
                    random_delay()

            # 清除已成功重试的失败记录
            if success_count > 0:
                self._history.clear_failed()

            log.info(f"\n✅ 重试完成: 成功 {success_count}/{len(to_retry)} 份")

        except Exception as e:
            log.error(f"❌ 重试过程出错: {e}")
            log.debug(traceback.format_exc())
        finally:
            self._close_browser()

    # ============================================================
    # 命令6：一键流水线
    # ============================================================

    def pipeline(self, keyword: str, city: str = "", max_download: int = 10,
                 max_pages: int = 3, auto_analyze: bool = True):
        """
        一键执行完整流水线：搜索 → 下载 → 清洗 → 分析

        Args:
            keyword: 搜索关键词
            city: 城市筛选
            max_download: 最多下载数量
            max_pages: 搜索最多页数
            auto_analyze: 是否自动进行 LLM 分析
        """
        print_banner(f"🚀 一键流水线: {keyword}")
        log.info(f"参数: 关键词={keyword}, 城市={city or '不限'}, "
                 f"最大下载={max_download}, 最大页数={max_pages}\n")

        start_time = time.time()

        # ── Step 1: 搜索 ──
        log.info("━" * 40)
        log.info("📌 Step 1/4: 搜索简历")
        log.info("━" * 40)
        results = self.search(keyword, city=city, max_pages=max_pages)

        if not results:
            log.error("❌ 未搜索到结果，流水线终止")
            return

        # ── Step 2: 下载 ──
        log.info("\n" + "━" * 40)
        log.info("📌 Step 2/4: 下载简历")
        log.info("━" * 40)
        self.download(max_count=max_download)

        # ── Step 3: 清洗 ──
        log.info("\n" + "━" * 40)
        log.info("📌 Step 3/4: 清洗简历")
        log.info("━" * 40)
        self.export()

        # ── Step 4: 分析（可选）──
        if auto_analyze:
            log.info("\n" + "━" * 40)
            log.info("📌 Step 4/4: AI 智能分析")
            log.info("━" * 40)
            try:
                from resume_parser import parse_all_resumes
                from llm_matcher import batch_match
                from report_generator import generate_excel_report, generate_console_report

                resumes = parse_all_resumes(config.RESUME_DIR)
                if resumes:
                    log.info(f"📄 解析到 {len(resumes)} 份简历，开始 AI 评分...\n")
                    match_results = batch_match(resumes, config.JOB_DESCRIPTION)

                    # 终端报告
                    generate_console_report(match_results)

                    # Excel 报告
                    try:
                        report_path = generate_excel_report(match_results)
                        log.info(f"\n📋 Excel 报告: {report_path}")
                    except Exception as e:
                        log.error(f"报告生成失败: {e}")
                else:
                    log.warning("⚠️ 没有可分析的简历")
            except ImportError as e:
                log.warning(f"⚠️ 分析模块未就绪，跳过: {e}")
            except Exception as e:
                log.error(f"❌ 分析失败: {e}")
                log.debug(traceback.format_exc())
        else:
            log.info("\n📌 Step 4/4: 跳过分析 (使用 --analyze 启用)")

        elapsed = time.time() - start_time
        print(f"\n{'='*55}")
        print(f"  🎉 流水线完成！总耗时: {elapsed:.0f} 秒")
        print(f"{'='*55}\n")

    # ============================================================
    # 命令7：状态检查
    # ============================================================

    def status(self):
        """显示当前爬虫状态"""
        print_banner("📊 爬虫状态")

        # 检查登录状态文件
        if os.path.isfile(config.SESSION_FILE):
            mtime = os.path.getmtime(config.SESSION_FILE)
            dt = datetime.fromtimestamp(mtime)
            # 计算过期风险
            age_hours = (time.time() - mtime) / 3600
            if age_hours > 24:
                age_hint = f" ⚠️ 已超过 {age_hours:.0f} 小时，建议重新登录"
            else:
                age_hint = f" ({age_hours:.1f} 小时前)"
            print(f"  🔑 登录状态:  ✅ 已保存 ({dt.strftime('%Y-%m-%d %H:%M')}){age_hint}")
        else:
            print(f"  🔑 登录状态:  ❌ 未登录")

        # 检查搜索结果
        result_file = os.path.join(os.path.dirname(__file__), "search_results.json")
        if os.path.isfile(result_file):
            with open(result_file, "r", encoding="utf-8") as f:
                results = json.load(f)
            mtime = os.path.getmtime(result_file)
            dt = datetime.fromtimestamp(mtime)
            downloadable = sum(1 for r in results if r.get("url"))
            print(f"  🔍 搜索结果:  {len(results)} 条 ({downloadable} 可下载)")
            print(f"                更新时间: {dt.strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"  🔍 搜索结果:  ❌ 无")

        # 检查已下载简历
        if os.path.isdir(config.RESUME_DIR):
            files = list(Path(config.RESUME_DIR).iterdir())
            supported = [f for f in files if f.suffix.lower() in config.SUPPORTED_FORMATS]
            print(f"  📁 简历目录:  {len(supported)} 份简历")
            # 按格式分类统计
            format_counts = {}
            for f in supported:
                ext = f.suffix.lower()
                format_counts[ext] = format_counts.get(ext, 0) + 1
            if format_counts:
                detail = ", ".join(f"{ext}: {cnt}" for ext, cnt in sorted(format_counts.items()))
                print(f"                格式分布: {detail}")
        else:
            print(f"  📁 简历目录:  空")

        # 清洗目录检查
        cleaned_dir = os.path.join(config.RESUME_DIR, "cleaned")
        if os.path.isdir(cleaned_dir):
            cleaned_files = list(Path(cleaned_dir).glob("*.txt"))
            print(f"  🧹 清洗文本:  {len(cleaned_files)} 份")
        else:
            print(f"  🧹 清洗文本:  ❌ 未清洗")

        # 下载历史
        stats = self._history.get_stats()
        failed = self._history.get_failed_list()
        print(f"\n  📈 下载统计:")
        print(f"     累计成功: {stats.get('total_success', 0)} 份")
        print(f"     失败待重试: {len(failed)} 份")

        # 配置信息
        print(f"\n  ⚙️  配置:")
        print(f"     目标网站: {config.EHIRE_URL}")
        print(f"     速度控制: {config.SCRAPER_MIN_DELAY}-{config.SCRAPER_MAX_DELAY} 秒/次")
        print(f"     单批上限: {config.SCRAPER_MAX_PER_BATCH} 份")
        print(f"     无头模式: {'是' if config.SCRAPER_HEADLESS else '否 (推荐)'}")

        # 日志文件
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        if os.path.isdir(log_dir):
            log_files = sorted(Path(log_dir).glob("*.log"), reverse=True)
            if log_files:
                print(f"\n  📝 最近日志: {log_files[0].name}")
        print()


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="前程无忧企业版简历爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python scraper.py login                         # 手动登录
  python scraper.py search "Python 工程师"         # 搜索简历
  python scraper.py search "Java" --city 上海      # 搜索上海的 Java 简历
  python scraper.py download                       # 下载搜索到的简历
  python scraper.py download --max 10              # 只下前 10 份
  python scraper.py download --format pdf          # 优先下载 PDF 格式
  python scraper.py export                         # 清洗 HTML → 纯文本
  python scraper.py retry                          # 重试失败的下载
  python scraper.py pipeline "Python" --max 10     # 一键搜索+下载+分析
  python scraper.py status                         # 查看状态
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="操作命令")

    # login 命令
    subparsers.add_parser("login", help="手动登录前程无忧企业版")

    # search 命令
    search_parser = subparsers.add_parser("search", help="搜索简历")
    search_parser.add_argument("keyword", type=str, help="搜索关键词")
    search_parser.add_argument("--city", type=str, default="", help="城市筛选")
    search_parser.add_argument("--years", type=str, default="", help="工作年限筛选")
    search_parser.add_argument("--education", type=str, default="", help="学历筛选")
    search_parser.add_argument("--pages", type=int, default=3, help="最多搜索页数 (默认3)")

    # download 命令
    download_parser = subparsers.add_parser("download", help="下载搜索到的简历")
    download_parser.add_argument("--max", type=int, default=None,
                                 help=f"最多下载数量 (默认{config.SCRAPER_MAX_PER_BATCH})")
    download_parser.add_argument("--format", type=str, default="html",
                                 choices=["html", "pdf", "word"],
                                 help="优先下载格式 (默认: html)")
    download_parser.add_argument("--no-skip", action="store_true",
                                 help="不跳过已下载的简历")

    # export 命令
    export_parser = subparsers.add_parser("export", help="清洗 HTML 简历为纯文本")
    export_parser.add_argument("--source", type=str, default=None, help="源目录")
    export_parser.add_argument("--output", type=str, default=None, help="输出目录")

    # retry 命令
    retry_parser = subparsers.add_parser("retry", help="重试失败的下载")
    retry_parser.add_argument("--max", type=int, default=None, help="最多重试数量")

    # pipeline 命令
    pipeline_parser = subparsers.add_parser("pipeline", help="一键搜索+下载+分析")
    pipeline_parser.add_argument("keyword", type=str, help="搜索关键词")
    pipeline_parser.add_argument("--city", type=str, default="", help="城市筛选")
    pipeline_parser.add_argument("--max", type=int, default=10, help="最多下载数量 (默认10)")
    pipeline_parser.add_argument("--pages", type=int, default=3, help="最多搜索页数 (默认3)")
    pipeline_parser.add_argument("--no-analyze", action="store_true", help="不执行 AI 分析")

    # status 命令
    subparsers.add_parser("status", help="查看爬虫状态")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    scraper = EhireScraper()

    if args.command == "login":
        scraper.login()
    elif args.command == "search":
        scraper.search(
            keyword=args.keyword,
            city=args.city,
            work_years=args.years,
            education=args.education,
            max_pages=args.pages,
        )
    elif args.command == "download":
        scraper.download(
            max_count=args.max,
            skip_downloaded=not args.no_skip,
            format_preference=args.format,
        )
    elif args.command == "export":
        scraper.export(source_dir=args.source, output_dir=args.output)
    elif args.command == "retry":
        scraper.retry_failed(max_count=args.max)
    elif args.command == "pipeline":
        scraper.pipeline(
            keyword=args.keyword,
            city=args.city,
            max_download=args.max,
            max_pages=args.pages,
            auto_analyze=not args.no_analyze,
        )
    elif args.command == "status":
        scraper.status()


if __name__ == "__main__":
    main()
