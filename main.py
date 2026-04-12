"""
简历智能筛选系统 - 主入口
用法：python main.py [--dir 简历目录] [--jd JD文件路径]
"""
import argparse
import os
import sys
import time

# Windows 终端 UTF-8 编码支持
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

import config
from resume_parser import parse_all_resumes
from llm_matcher import batch_match
from report_generator import generate_excel_report, generate_console_report

console = Console()


def print_banner():
    """打印启动横幅"""
    console.print("""
[bold blue]╔══════════════════════════════════════════════════╗
║         📋 简历智能筛选系统 v1.0                ║
║         Powered by DeepSeek LLM                 ║
╚══════════════════════════════════════════════════╝[/bold blue]
    """)


def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="简历智能筛选系统")
    parser.add_argument("--dir", type=str, default=config.RESUME_DIR,
                        help=f"简历文件目录 (默认: {config.RESUME_DIR})")
    parser.add_argument("--jd", type=str, default=None,
                        help="岗位要求文件路径 (默认使用 config.py 中的配置)")
    parser.add_argument("--output", type=str, default=config.OUTPUT_DIR,
                        help=f"报告输出目录 (默认: {config.OUTPUT_DIR})")
    args = parser.parse_args()

    print_banner()

    # --------------------------------------------------------
    # Step 1: 读取岗位要求
    # --------------------------------------------------------
    job_description = config.JOB_DESCRIPTION
    if args.jd:
        if os.path.isfile(args.jd):
            with open(args.jd, "r", encoding="utf-8") as f:
                job_description = f.read()
            console.print(f"✅ 已加载岗位要求: {args.jd}")
        else:
            console.print(f"[red]❌ JD 文件不存在: {args.jd}[/red]")
            sys.exit(1)
    else:
        console.print("ℹ️  使用 config.py 中的默认岗位要求")

    console.print(f"📁 简历目录: {args.dir}")
    console.print(f"📂 输出目录: {args.output}\n")

    # --------------------------------------------------------
    # Step 2: 解析简历
    # --------------------------------------------------------
    console.print("[bold]📄 Step 1/3: 解析简历文件...[/bold]")
    try:
        resumes = parse_all_resumes(args.dir)
    except FileNotFoundError as e:
        console.print(f"[red]❌ {e}[/red]")
        sys.exit(1)

    console.print(f"✅ 成功解析 [green]{len(resumes)}[/green] 份简历\n")

    for i, r in enumerate(resumes):
        console.print(f"  {i+1}. {r.summary()}")
    console.print()

    # --------------------------------------------------------
    # Step 3: LLM 智能匹配
    # --------------------------------------------------------
    console.print("[bold]🤖 Step 2/3: AI 智能评分中...[/bold]")
    console.print(f"   模型: {config.LLM_MODEL_NAME} @ {config.LLM_BASE_URL}\n")

    start_time = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("评分进度", total=len(resumes))

        def on_progress(current, total, name):
            progress.update(task, completed=current, description=f"正在评估: {name}")

        results = batch_match(resumes, job_description, progress_callback=on_progress)

    elapsed = time.time() - start_time
    console.print(f"\n✅ 评分完成，耗时 {elapsed:.1f} 秒\n")

    # --------------------------------------------------------
    # Step 4: 生成报告
    # --------------------------------------------------------
    console.print("[bold]📊 Step 3/3: 生成筛选报告...[/bold]\n")

    # 终端展示
    generate_console_report(results)

    # Excel 报告
    try:
        report_path = generate_excel_report(results, args.output)
        console.print(f"\n📋 Excel 报告已生成: [bold green]{report_path}[/bold green]")
    except Exception as e:
        console.print(f"\n[red]⚠️ Excel 报告生成失败: {e}[/red]")

    # 错误汇总
    errors = [r for r in results if r.error]
    if errors:
        console.print(f"\n⚠️  有 {len(errors)} 份简历评分异常:")
        for r in errors:
            console.print(f"  - {r.candidate_name}: {r.error}")

    console.print("\n[dim]完成！如需修改岗位要求，请编辑 config.py 中的 JOB_DESCRIPTION[/dim]")


if __name__ == "__main__":
    main()
