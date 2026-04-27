import argparse
import json
import copy
import os
import csv
from datetime import datetime
from shixiseng import ShixisengScraper
from data_cleaner import DataCleaner
from file_store import FileStore


def _flatten_job(job):
    basic = job.get("basic_info", {})
    company = job.get("company_info", {})
    location = basic.get("location", {})
    compensation = job.get("compensation", {})
    salary = compensation.get("salary", {})
    requirements = job.get("requirements", {})
    internship = requirements.get("internship_specific", {})
    metadata = job.get("metadata", {})
    return {
        "job_id": basic.get("job_id", ""),
        "title": basic.get("title", ""),
        "category": basic.get("category", ""),
        "city": location.get("city", ""),
        "state": location.get("state", ""),
        "company": company.get("name", ""),
        "company_type": company.get("type", ""),
        "salary_origin": salary.get("origin_str", ""),
        "salary_min": salary.get("min", ""),
        "salary_max": salary.get("max", ""),
        "education": requirements.get("education", ""),
        "duty_days_per_week": internship.get("duty_days_per_week", ""),
        "duration_months": internship.get("duration_months", ""),
        "conversion_chance": internship.get("conversion_chance", ""),
        "url": metadata.get("url", ""),
        "refresh_at": metadata.get("refresh_at", ""),
        "scraped_at": metadata.get("scraped_at", ""),
    }


def _write_jsonl(path, wrapped_jobs):
    with open(path, "w", encoding="utf-8") as f:
        for row in wrapped_jobs:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_csv(path, jobs):
    fieldnames = list(_flatten_job(jobs[0]).keys()) if jobs else [
        "job_id", "title", "category", "city", "state", "company", "company_type",
        "salary_origin", "salary_min", "salary_max", "education",
        "duty_days_per_week", "duration_months", "conversion_chance",
        "url", "refresh_at", "scraped_at",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs:
            writer.writerow(_flatten_job(job))

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    
    # 1. 加载 task.json (基础配置)
    task_json_path = os.path.join(project_root, "assets", "task.json")
    task_config = {}
    if os.path.exists(task_json_path):
        with open(task_json_path, "r", encoding="utf-8") as f:
            task_config = json.load(f)
    
    defaults = task_config.get("default_filters", {})
    runtime_defaults = task_config.get("runtime", {})

    parser = argparse.ArgumentParser(description="AI-powered Crawler CLI (Priority: CLI > task.json)")
    
    # 模式参数
    parser.add_argument("--mode", type=str, choices=["crawl", "clean", "all"], default="all")
    
    # 高级筛选参数 (默认值全部取自 task.json)
    parser.add_argument("--category", type=str, default=None, help="覆盖 task.json 中的 categories")
    parser.add_argument("--degree", type=str, default=defaults.get("degree", "不限"))
    parser.add_argument("--official", type=str, default=defaults.get("official", "不限"))
    parser.add_argument("--enterprise", type=str, default=defaults.get("enterprise", "不限"))
    parser.add_argument("--city", type=str, default=defaults.get("city", "全国"))
    parser.add_argument("--months", type=str, default=defaults.get("months", "不限"))
    parser.add_argument("--days", type=str, default=defaults.get("days", "不限"))
    
    # 运行控制参数
    parser.add_argument(
        "--limit-pages",
        type=int,
        default=None,
        help="覆盖 task.json 中的 runtime.max_pages（兼容 max_pages_per_category）",
    )
    parser.add_argument("--limit-clean", type=int, default=10)
    parser.add_argument(
        "--storage-dir",
        type=str,
        default=os.path.join("scripts", "job_store"),
        help="文件存储目录，职位会按 job_id 写入独立子目录",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="兼容旧参数；建议改用 --storage-dir。传入 .db 路径时会自动映射到同名 _store 目录",
    )
    parser.add_argument(
        "--export-dir",
        type=str,
        default=None,
        help="导出目录；默认使用 task.json 的 base_output_dir",
    )
    
    args = parser.parse_args()

    # 2. 优先级合并逻辑
    # 如果命令行传了 --category，则只爬那一个；否则爬 task.json 里的全量列表
    final_categories = [args.category] if args.category else task_config.get("categories", ["互联网IT"])
    
    # 如果命令行传了 --limit-pages，优先级最高；否则看 task.json 的 runtime.max_pages（新）/max_pages_per_category（兼容）；最后保底 5 页
    config_pages = runtime_defaults.get("max_pages")
    if config_pages is None:
        config_pages = runtime_defaults.get("max_pages_per_category")
    final_limit_pages = args.limit_pages if args.limit_pages is not None else (config_pages if config_pages is not None else 5)

    # 确定输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_base_dir = task_config.get("base_output_dir", os.path.join("scripts", "rebuild"))
    if args.export_dir:
        result_base_dir = args.export_dir
    current_result_dir = os.path.join(result_base_dir, f"result_{timestamp}")
    if not os.path.exists(current_result_dir):
        os.makedirs(current_result_dir)
    storage_dir = args.db if args.db else args.storage_dir

    print(f"🚀 Environment: CLI Priority Mode")
    print(f"📍 Target categories: {final_categories}")
    print(f"📄 Max pages: {final_limit_pages}")
    print(f"🗂️ File storage: {storage_dir}")
    print(f"📂 Export output: {current_result_dir}\n")

    session_ids = set()

    if args.mode in ["crawl", "all"]:
        scraper = ShixisengScraper(storage_dir=storage_dir)
        custom_filters = {
            "degree": args.degree, "official": args.official, 
            "enterprise": args.enterprise, "city": args.city, 
            "months": args.months, "days": args.days
        }
        crawled_ids = scraper.run(categories=final_categories, limit_pages=final_limit_pages, custom_filters=custom_filters)
        session_ids.update(crawled_ids)

    if args.mode in ["clean", "all"]:
        cleaner = DataCleaner(storage_dir=storage_dir)
        limit = max(args.limit_clean, len(session_ids)) if args.mode == "all" else args.limit_clean
        cleaned_ids = cleaner.clean_all_pending(limit=limit)
        session_ids.update(cleaned_ids)

    # --- 统一导出逻辑 ---
    store = FileStore(storage_dir=storage_dir)
    if not session_ids:
        print("⚠️ No jobs found or processed in this session. Export files will be empty.")
        all_relevant_jobs = []
    else:
        all_relevant_jobs = store.get_jobs_by_ids(list(session_ids))

    wrapped_jobs = [{"job_schema": j} for j in all_relevant_jobs]

    with open(os.path.join(current_result_dir, "ex_with_raw.json"), "w", encoding="utf-8") as f:
        json.dump({"jobs": wrapped_jobs, "total_count": len(wrapped_jobs)}, f, ensure_ascii=False, indent=2)
    
    clean_jobs = []
    for job_w in wrapped_jobs:
        job_copy = copy.deepcopy(job_w)
        job_copy["job_schema"].pop("ai_raw_data", None)
        clean_jobs.append(job_copy)
    with open(os.path.join(current_result_dir, "ex_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"jobs": clean_jobs, "total_count": len(clean_jobs)}, f, ensure_ascii=False, indent=2)
    
    with open(os.path.join(current_result_dir, "shixiseng_results.json"), "w", encoding="utf-8") as f:
        json.dump({"jobs": wrapped_jobs, "total_count": len(wrapped_jobs)}, f, ensure_ascii=False, indent=2)

    _write_jsonl(os.path.join(current_result_dir, "jobs_with_raw.jsonl"), wrapped_jobs)
    _write_jsonl(os.path.join(current_result_dir, "jobs_summary.jsonl"), clean_jobs)
    _write_csv(
        os.path.join(current_result_dir, "jobs_summary.csv"),
        [job_w["job_schema"] for job_w in clean_jobs],
    )

    session_manifest = {
        "mode": args.mode,
        "session_at": timestamp,
        "storage_dir": store.storage_root,
        "job_ids": sorted(session_ids),
        "total_count": len(session_ids),
    }
    with open(os.path.join(current_result_dir, "session.json"), "w", encoding="utf-8") as f:
        json.dump(session_manifest, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ All tasks finished. Check results in: {current_result_dir}")

if __name__ == "__main__":
    main()
