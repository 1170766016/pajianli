"""
数据模型 - 定义简历数据和匹配结果的结构
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ResumeData:
    """解析后的简历数据"""
    file_path: str                          # 原始文件路径
    file_name: str                          # 文件名
    raw_text: str                           # 简历原始文本（全文）
    name: Optional[str] = None              # 姓名
    phone: Optional[str] = None             # 电话
    email: Optional[str] = None             # 邮箱
    education: Optional[str] = None         # 学历
    work_years: Optional[str] = None        # 工作年限
    current_company: Optional[str] = None   # 当前公司
    skills: list[str] = field(default_factory=list)  # 技能列表

    def summary(self) -> str:
        """生成简历摘要"""
        parts = []
        if self.name:
            parts.append(f"姓名: {self.name}")
        if self.work_years:
            parts.append(f"工作年限: {self.work_years}")
        if self.education:
            parts.append(f"学历: {self.education}")
        if self.skills:
            parts.append(f"技能: {', '.join(self.skills[:10])}")
        return " | ".join(parts) if parts else self.file_name


@dataclass
class DimensionScore:
    """单个维度的评分"""
    name: str           # 维度名称
    score: int          # 分数 (0-100)
    comment: str        # 评语


@dataclass
class MatchResult:
    """LLM 匹配评分结果"""
    resume: ResumeData                                  # 对应的简历
    total_score: int = 0                                # 总分 (0-100)
    recommendation: str = "不推荐"                       # 推荐/待定/不推荐
    dimensions: list[DimensionScore] = field(default_factory=list)  # 各维度评分
    strengths: str = ""                                 # 优势
    weaknesses: str = ""                                # 不足
    overall_comment: str = ""                           # 总体评价
    error: Optional[str] = None                         # 如果评分失败，记录错误信息

    @property
    def candidate_name(self) -> str:
        return self.resume.name or self.resume.file_name
