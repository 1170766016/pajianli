"""
LLM 匹配模块 - 用大模型对简历进行智能评分
使用 OpenAI 兼容接口，支持 DeepSeek / ChatGPT / 本地模型
"""
import json
import time
import traceback

from openai import OpenAI

import config
from models import ResumeData, MatchResult, DimensionScore


# 初始化 LLM 客户端
_client = None


def _get_client() -> OpenAI:
    """延迟初始化 LLM 客户端"""
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            timeout=config.LLM_TIMEOUT,
        )
    return _client


def _build_prompt(resume_text: str, job_description: str) -> str:
    """
    构造评分 Prompt
    关键：要求 LLM 返回严格的 JSON 格式，方便程序解析
    """
    # 构建评分维度说明
    dimensions_desc = "\n".join(
        f"  - {d['name']}（权重{d['weight']}%）: {d['description']}"
        for d in config.SCORING_DIMENSIONS
    )

    return f"""你是一位专业的 HR 招聘顾问，请根据岗位要求对以下候选人简历进行评估打分。

## 岗位要求 (JD)
{job_description}

## 候选人简历
{resume_text[:6000]}

## 评分要求

请从以下维度进行评分（每个维度 0-100 分）：
{dimensions_desc}

## 输出格式

请严格按以下 JSON 格式输出，不要输出任何其他内容：

```json
{{
  "candidate_name": "候选人姓名（从简历中提取）",
  "dimensions": [
    {{"name": "技能匹配", "score": 80, "comment": "具体评语"}},
    {{"name": "工作经验", "score": 75, "comment": "具体评语"}},
    {{"name": "教育背景", "score": 70, "comment": "具体评语"}},
    {{"name": "项目经历", "score": 85, "comment": "具体评语"}},
    {{"name": "综合素质", "score": 78, "comment": "具体评语"}}
  ],
  "strengths": "候选人的主要优势（1-3点）",
  "weaknesses": "候选人的不足之处（1-3点）",
  "overall_comment": "一句话总体评价和面试建议"
}}
```

注意：
1. 评分要客观，不要都打高分
2. 评语要具体，引用简历中的实际内容
3. 如果简历信息不足，对应维度给较低分并在评语中说明
4. 只输出 JSON，不要有其他文字"""


def match_resume(resume: ResumeData, job_description: str = None) -> MatchResult:
    """
    用 LLM 对单份简历进行评分
    
    Args:
        resume: 解析后的简历数据
        job_description: 岗位要求，默认使用 config 中的配置
        
    Returns:
        MatchResult 评分结果
    """
    if job_description is None:
        job_description = config.JOB_DESCRIPTION

    result = MatchResult(resume=resume)

    try:
        client = _get_client()
        prompt = _build_prompt(resume.raw_text, job_description)

        response = client.chat.completions.create(
            model=config.LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是专业的 HR 招聘评估顾问，擅长人才评估和岗位匹配分析。请严格按要求的 JSON 格式输出。"},
                {"role": "user", "content": prompt},
            ],
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS,
        )

        # 解析 LLM 返回
        content = response.choices[0].message.content.strip()
        result = _parse_llm_response(content, resume)

    except Exception as e:
        result.error = f"LLM 评分失败: {str(e)}"
        result.total_score = 0
        result.recommendation = "评分失败"
        traceback.print_exc()

    return result


def _parse_llm_response(content: str, resume: ResumeData) -> MatchResult:
    """
    解析 LLM 返回的 JSON 评分
    做了容错处理：即使 LLM 返回格式不完美也能尽量解析
    """
    result = MatchResult(resume=resume)

    # 提取 JSON（LLM 有时会在 JSON 前后加文字或 markdown 代码块）
    json_str = content
    if "```json" in content:
        json_str = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        json_str = content.split("```")[1].split("```")[0]

    # 尝试找到 JSON 对象
    start = json_str.find("{")
    end = json_str.rfind("}") + 1
    if start != -1 and end > start:
        json_str = json_str[start:end]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        result.error = f"LLM 返回格式解析失败"
        result.overall_comment = content[:500]  # 保存原始返回用于排查
        return result

    # 提取候选人姓名
    if not resume.name and data.get("candidate_name"):
        resume.name = data["candidate_name"]

    # 解析各维度评分
    dimensions = data.get("dimensions", [])
    for dim in dimensions:
        result.dimensions.append(DimensionScore(
            name=dim.get("name", "未知"),
            score=int(dim.get("score", 0)),
            comment=dim.get("comment", ""),
        ))

    # 计算加权总分
    result.total_score = _calculate_weighted_score(result.dimensions)

    # 推荐等级
    if result.total_score >= config.RECOMMEND_THRESHOLD:
        result.recommendation = "⭐ 推荐面试"
    elif result.total_score >= config.MAYBE_THRESHOLD:
        result.recommendation = "🔶 可以考虑"
    else:
        result.recommendation = "❌ 不推荐"

    # 其他信息
    result.strengths = data.get("strengths", "")
    result.weaknesses = data.get("weaknesses", "")
    result.overall_comment = data.get("overall_comment", "")

    return result


def _calculate_weighted_score(dimensions: list[DimensionScore]) -> int:
    """根据配置的权重计算加权总分"""
    weight_map = {d["name"]: d["weight"] for d in config.SCORING_DIMENSIONS}
    total_weight = sum(weight_map.values())

    weighted_sum = 0
    for dim in dimensions:
        weight = weight_map.get(dim.name, 10)  # 默认权重 10
        weighted_sum += dim.score * weight

    if total_weight > 0:
        return round(weighted_sum / total_weight)
    return 0


def batch_match(
    resumes: list[ResumeData],
    job_description: str = None,
    progress_callback=None,
) -> list[MatchResult]:
    """
    批量评分，带进度回调
    
    Args:
        resumes: 简历列表
        job_description: 岗位要求
        progress_callback: 进度回调 callback(current, total, resume_name)
        
    Returns:
        MatchResult 列表，按总分降序排列
    """
    results = []
    total = len(resumes)

    for i, resume in enumerate(resumes):
        if progress_callback:
            progress_callback(i + 1, total, resume.name or resume.file_name)

        result = match_resume(resume, job_description)
        results.append(result)

        # 简历之间间隔 1 秒，避免对 LLM 服务造成压力
        if i < total - 1:
            time.sleep(1)

    # 按总分降序排列
    results.sort(key=lambda r: r.total_score, reverse=True)
    return results
