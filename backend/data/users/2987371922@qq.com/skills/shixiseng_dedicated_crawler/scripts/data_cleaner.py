import json
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from file_store import FileStore

class DataCleaner:
    def __init__(self, storage_dir=os.path.join("scripts", "job_store")):
        self.store = FileStore(storage_dir)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assets_dir = os.path.join(project_root, "assets")
        self._load_configs()
        # 从配置中读取 API 信息
        cfg = self.clean_config.get("config", {})
        self.client = OpenAI(
            base_url=cfg.get("api_base", "https://ark.cn-beijing.volces.com/api/v3"),
            api_key=cfg.get("api_key", "58dd3f48-ef00-4ad4-b85d-fb2b2b3bf77d")
        )
        self.file_lock = threading.Lock()

    def _load_configs(self):
        with open(os.path.join(self.assets_dir, "datacleanp.json"), "r", encoding="utf-8") as f:
            self.clean_config = json.load(f)
        with open(os.path.join(self.assets_dir, "target.json"), "r", encoding="utf-8") as f:
            self.target_config = json.load(f)

    def clean_json_response(self, raw_response):
        try:
            json_str = re.sub(r'^```json\s*|```\s*$', '', raw_response.strip(), flags=re.MULTILINE)
            match = re.search(r'(\{.*\})', json_str, re.DOTALL)
            return match.group(1) if match else json_str
        except:
            return raw_response

    def map_ai_data_to_struct(self, target, ai_data):
        if not ai_data or not isinstance(ai_data, dict): return
        req = target.setdefault("requirements", {})
        req["experience"] = ai_data.get("experience") or "null"
        req["skills_required"] = ai_data.get("skills_required") or []
        req["languages"] = ai_data.get("languages") or []
        m_ai = ai_data.get("major_requirements") or {}
        m_req = req.setdefault("major_requirements", {})
        m_req.update({
            "target_majors": m_ai.get("target_majors") or [],
            "allow_related": m_ai.get("allow_related") if m_ai.get("allow_related") is not None else True,
            "requirement_level": m_ai.get("requirement_level") or "no_preferred",
            "origin_str": m_ai.get("origin_str") or "null"
        })
        inter = req.setdefault("internship_specific", {})
        target.setdefault("basic_info", {}).setdefault("location", {})["is_remote"] = ai_data.get("is_remote") or False
        desc = target.setdefault("description", {})
        desc["team_intro"] = ai_data.get("team_intro") or "null"
        desc["position_description"] = ai_data.get("position_description") or "null"
        target.setdefault("compensation", {})["benefits"] = ai_data.get("benefits") or []
        # 注意：这里虽然在内存中挂载了 ai_raw_data，但在 file store 落盘时会被剥离后单独存盘
        target["ai_raw_data"] = ai_data

    def _render_prompt(self, job_item):
        data = {
            "platform": self.target_config.get("platform", "实习僧"),
            "job_title": job_item.get("basic_info", {}).get("title", ""),
            "company_type": job_item.get("company_info", {}).get("type", ""),
            "raw_description": job_item.get("description", {}).get("origin_str", "")
        }
        system_content = self.clean_config.get("template", {}).get("system", "").format(**data)
        user_content = self.clean_config.get("template", {}).get("user", "").format(**data)
        return system_content, user_content

    def clean_job(self, job_item):
        job_id = job_item.get("basic_info", {}).get("job_id")
        system_content, user_content = self._render_prompt(job_item)
        cfg = self.clean_config.get("config", {})
        
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(
                    model=cfg.get("model", "doubao-seed-1-6-flash-250828"),
                    messages=[{"role": "system", "content": system_content}, {"role": "user", "content": user_content}],
                    temperature=0.0,
                    response_format={"type": "json_object"}
                )
                raw_content = response.choices[0].message.content
                parsed_json = json.loads(self.clean_json_response(raw_content))
                self.map_ai_data_to_struct(job_item, parsed_json)
                # save_job_full 会检测到 ai_raw_data 并设置 is_cleaned=1，同时剥离它后再存盘
                self.store.save_job_full(job_item)
                return job_id, parsed_json
            except Exception as e:
                if "429" in str(e) or "AccountOverdueError" in str(e):
                    time.sleep((attempt + 1) * 3)
                else: break
        return job_id, None

    def clean_all_pending(self, limit=10):
        cleaned_ids = []
        # 使用文件索引中的 is_cleaned 状态过滤，而不是在内存中检查字段
        to_process = self.store.get_pending_jobs(limit=limit)
        if not to_process:
            print("✅ No pending jobs for cleaning.")
            return []

        # 核心：使用 datacleanp.json 中的 max_workers (宏)
        max_workers = self.clean_config.get("config", {}).get("max_workers", 10)
        print(f"🚀 Starting AI cleaning for {len(to_process)} jobs (Workers: {max_workers})...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {executor.submit(self.clean_job, job): job["basic_info"]["job_id"] for job in to_process}
            for future in as_completed(future_to_id):
                jid, res = future.result()
                if res:
                    cleaned_ids.append(jid)
        print(f"✨ Cleaning completed.")
        return cleaned_ids

if __name__ == "__main__":
    cleaner = DataCleaner()
    cleaner.clean_all_pending(limit=2)
