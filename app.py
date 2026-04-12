"""
简历智能筛选系统 - FastAPI Web 服务
启动方式：python app.py
访问地址：http://localhost:8000
"""
import os
import sys
import json
import shutil
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

# Windows 终端 UTF-8 编码支持
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

import config
from resume_parser import parse_resume, parse_all_resumes
from llm_matcher import match_resume, batch_match
from report_generator import generate_excel_report
from models import ResumeData, MatchResult

app = FastAPI(title="简历智能筛选系统", version="1.0")

# 确保目录存在
os.makedirs(config.RESUME_DIR, exist_ok=True)
os.makedirs(config.OUTPUT_DIR, exist_ok=True)


# ============================================================
# 页面路由
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """首页 - 返回 Web UI"""
    html_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ============================================================
# API 路由
# ============================================================

@app.post("/api/upload")
async def upload_resumes(files: list[UploadFile] = File(...)):
    """上传简历文件"""
    supported = set(config.SUPPORTED_FORMATS)
    uploaded = []
    errors = []

    for file in files:
        ext = Path(file.filename).suffix.lower()
        if ext not in supported:
            errors.append(f"{file.filename}: 不支持的格式 ({ext})")
            continue

        # 保存文件
        save_path = os.path.join(config.RESUME_DIR, file.filename)
        try:
            with open(save_path, "wb") as f:
                content = await file.read()
                f.write(content)
            uploaded.append(file.filename)
        except Exception as e:
            errors.append(f"{file.filename}: 保存失败 ({e})")

    return {
        "uploaded": uploaded,
        "errors": errors,
        "message": f"成功上传 {len(uploaded)} 个文件" + (f"，{len(errors)} 个失败" if errors else ""),
    }


@app.get("/api/resumes")
async def list_resumes():
    """获取已上传的简历列表"""
    supported = set(config.SUPPORTED_FORMATS)
    files = []

    if os.path.isdir(config.RESUME_DIR):
        for f in sorted(Path(config.RESUME_DIR).iterdir()):
            if f.suffix.lower() in supported:
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "format": f.suffix.lower(),
                    "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                })

    return {"resumes": files, "total": len(files)}


@app.delete("/api/resumes/{filename}")
async def delete_resume(filename: str):
    """删除简历文件"""
    filepath = os.path.join(config.RESUME_DIR, filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    os.remove(filepath)
    return {"message": f"已删除: {filename}"}


@app.post("/api/analyze")
async def analyze_resumes(jd: Optional[str] = Form(None)):
    """分析所有简历并返回评分结果"""
    job_description = jd if jd else config.JOB_DESCRIPTION

    # 解析简历
    try:
        resumes = parse_all_resumes(config.RESUME_DIR)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not resumes:
        raise HTTPException(status_code=400, detail="没有找到可解析的简历文件")

    # LLM 评分
    results = batch_match(resumes, job_description)

    # 生成 Excel 报告
    report_path = None
    try:
        report_path = generate_excel_report(results, config.OUTPUT_DIR)
    except Exception:
        pass

    # 构建返回数据
    response_data = []
    for r in results:
        response_data.append({
            "name": r.candidate_name,
            "file_name": r.resume.file_name,
            "total_score": r.total_score,
            "recommendation": r.recommendation,
            "education": r.resume.education or "未知",
            "work_years": r.resume.work_years or "未知",
            "phone": r.resume.phone or "",
            "email": r.resume.email or "",
            "dimensions": [
                {"name": d.name, "score": d.score, "comment": d.comment}
                for d in r.dimensions
            ],
            "strengths": r.strengths,
            "weaknesses": r.weaknesses,
            "overall_comment": r.overall_comment,
            "error": r.error,
        })

    return {
        "results": response_data,
        "total": len(response_data),
        "report_file": os.path.basename(report_path) if report_path else None,
    }


@app.get("/api/download/{filename}")
async def download_report(filename: str):
    """下载报告文件"""
    filepath = os.path.join(config.OUTPUT_DIR, filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="报告文件不存在")
    return FileResponse(filepath, filename=filename)


@app.get("/api/config")
async def get_config():
    """获取当前配置"""
    return {
        "jd": config.JOB_DESCRIPTION,
        "model": config.LLM_MODEL_NAME,
        "base_url": config.LLM_BASE_URL,
        "supported_formats": config.SUPPORTED_FORMATS,
        "scoring_dimensions": config.SCORING_DIMENSIONS,
        "recommend_threshold": config.RECOMMEND_THRESHOLD,
        "maybe_threshold": config.MAYBE_THRESHOLD,
    }


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  📋 简历智能筛选系统 v1.0")
    print("  🌐 访问地址: http://localhost:8000")
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
