"""
配置文件 - 所有可配置项集中在这里
"""

import os

# ============================================================
# LLM 配置 (DeepSeek 本地部署，使用 OpenAI 兼容接口)
# ============================================================
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://xiaoai.plus/v1")  # 改成你的 DeepSeek 地址
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-avtdHGF7y5HV3l203LGtlHb0UUeBBAqxgudVRq2UQp8jxF4z")  # 本地部署一般不需要 key
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4o")



# LLM 请求参数
LLM_TEMPERATURE = 0.1  # 低温度 = 更稳定的输出
LLM_MAX_TOKENS = 2000  # 每次评分的最大 token
LLM_TIMEOUT = 120  # 请求超时（秒）

# ============================================================
# 文件路径配置
# ============================================================
RESUME_DIR = os.path.join(os.path.dirname(__file__), "resumes")  # 简历存放目录
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")  # 输出报告目录

# 支持的简历文件格式
SUPPORTED_FORMATS = [".html", ".htm", ".pdf", ".docx", ".doc", ".txt"]

# ============================================================
# 岗位需求 (JD) - 根据实际需求修改
# ============================================================
JOB_DESCRIPTION = """
岗位名称：Python 后端开发工程师

岗位职责：
1. 负责公司后端系统的开发和维护
2. 参与系统架构设计和技术选型
3. 编写高质量、可维护的代码
4. 参与代码审查和技术文档编写

任职要求：
1. 本科及以上学历，计算机相关专业优先
2. 3年以上 Python 后端开发经验
3. 熟悉 Django/Flask/FastAPI 等 Web 框架
4. 熟悉 MySQL/PostgreSQL/Redis 等数据库
5. 了解 Docker、Linux 基本操作
6. 有良好的沟通能力和团队合作精神

加分项：
- 有大模型/AI 相关开发经验
- 有微服务架构经验
- 有开源项目贡献
"""

# ============================================================
# 评分维度配置
# ============================================================
SCORING_DIMENSIONS = [
    {
        "name": "技能匹配",
        "weight": 30,
        "description": "候选人的技术栈与岗位要求的匹配程度",
    },
    {"name": "工作经验", "weight": 25, "description": "相关工作经验的年限和质量"},
    {"name": "教育背景", "weight": 15, "description": "学历和专业的匹配度"},
    {"name": "项目经历", "weight": 20, "description": "过往项目与目标岗位的相关性"},
    {"name": "综合素质", "weight": 10, "description": "沟通能力、学习能力、稳定性等"},
]

# ============================================================
# 匹配阈值
# ============================================================
RECOMMEND_THRESHOLD = 70  # >= 70 分推荐面试
MAYBE_THRESHOLD = 50  # 50-69 分待定
# < 50 分不推荐

# ============================================================
# 前程无忧爬虫配置
# ============================================================
EHIRE_URL = "https://ehire.51job.com"  # 企业版首页
EHIRE_SEARCH_URL = (
    "https://ehire.51job.com/Candidate/SearchResumeNew.aspx"  # 简历搜索页
)
SESSION_FILE = os.path.join(
    os.path.dirname(__file__), "session.json"
)  # 登录状态保存文件
BROWSER_DATA_DIR = os.path.join(
    os.path.dirname(__file__), "browser_data"
)  # 浏览器数据目录

# 爬虫速度控制（防封核心）
SCRAPER_MIN_DELAY = 3  # 最小延迟（秒）
SCRAPER_MAX_DELAY = 8  # 最大延迟（秒）
SCRAPER_PAGE_DELAY = 5  # 翻页等待（秒）
SCRAPER_MAX_PER_BATCH = 50  # 单次最多下载数量
SCRAPER_HEADLESS = False  # 是否无头模式（建议 False，更安全）
