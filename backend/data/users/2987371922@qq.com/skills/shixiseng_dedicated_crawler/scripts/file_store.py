import json
import os
import threading
from datetime import datetime, timezone


class FileStore:
    """File-backed job storage with one directory per job plus a JSONL index."""

    def __init__(self, storage_dir=None):
        if storage_dir is None:
            root = os.path.join("scripts", "job_store")
        else:
            root = storage_dir
            if root.endswith(".db"):
                root = os.path.splitext(root)[0] + "_store"

        self.storage_root = root
        self.jobs_root = os.path.join(self.storage_root, "jobs")
        self.index_path = os.path.join(self.storage_root, "index.jsonl")
        self._lock = threading.Lock()
        self._init_store()

    def _init_store(self):
        os.makedirs(self.jobs_root, exist_ok=True)
        if not os.path.exists(self.index_path):
            with open(self.index_path, "w", encoding="utf-8"):
                pass

    def _utc_now(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _job_dir(self, job_id):
        return os.path.join(self.jobs_root, str(job_id))

    def _meta_path(self, job_id):
        return os.path.join(self._job_dir(job_id), "meta.json")

    def _raw_path(self, job_id):
        return os.path.join(self._job_dir(job_id), "raw.json")

    def _cleaned_path(self, job_id):
        return os.path.join(self._job_dir(job_id), "cleaned.json")

    def _ai_raw_path(self, job_id):
        return os.path.join(self._job_dir(job_id), "ai_raw.json")

    def _write_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

    def _read_json(self, path, default=None):
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _unwrap_job_data(self, job_data):
        if "job_schema" in job_data:
            return job_data["job_schema"]
        if "aligned_data" in job_data:
            return job_data["aligned_data"]
        return job_data

    def _build_meta(self, job_id, job_data, previous_meta, is_cleaned):
        basic = job_data.get("basic_info", {})
        company = job_data.get("company_info", {})
        location = basic.get("location", {})
        compensation = job_data.get("compensation", {})
        salary = compensation.get("salary", {})
        description = job_data.get("description", {})
        metadata = job_data.get("metadata", {})

        created_at = previous_meta.get("created_at") if previous_meta else self._utc_now()
        return {
            "job_id": job_id,
            "platform": metadata.get("platform", "实习僧"),
            "title": basic.get("title", ""),
            "company": company.get("name", ""),
            "city": location.get("city", ""),
            "salary": salary.get("origin_str", ""),
            "raw_description": description.get("origin_str", ""),
            "url": metadata.get("url", ""),
            "cat_name": basic.get("category", ""),
            "conversion_val": (
                job_data.get("requirements", {})
                .get("internship_specific", {})
                .get("conversion_chance", "")
            ),
            "refresh_at_site": metadata.get("refresh_at", ""),
            "is_cleaned": 1 if is_cleaned else 0,
            "created_at": created_at,
            "updated_at": self._utc_now(),
        }

    def _load_index_map(self):
        index_map = {}
        if not os.path.exists(self.index_path):
            return index_map
        with open(self.index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                job_id = str(record.get("job_id", "")).strip()
                if job_id:
                    index_map[job_id] = record
        return index_map

    def _rewrite_index(self, index_map):
        temp_path = f"{self.index_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            for job_id in sorted(index_map.keys()):
                f.write(json.dumps(index_map[job_id], ensure_ascii=False) + "\n")
        os.replace(temp_path, self.index_path)

    def _read_job_for_output(self, job_id):
        cleaned_job = self._read_json(self._cleaned_path(job_id))
        raw_job = self._read_json(self._raw_path(job_id))
        job = cleaned_job if cleaned_job is not None else raw_job
        if job is None:
            return None

        ai_raw_data = self._read_json(self._ai_raw_path(job_id))
        if ai_raw_data is not None:
            job = json.loads(json.dumps(job, ensure_ascii=False))
            job["ai_raw_data"] = ai_raw_data
        return job

    def get_refresh_at_stored(self, job_id):
        meta = self._read_json(self._meta_path(job_id), default={})
        return meta.get("refresh_at_site")

    def save_job_full(self, job_data, is_cleaned=None):
        job_data = self._unwrap_job_data(job_data)
        job_id = str(job_data["basic_info"]["job_id"])
        job_dir = self._job_dir(job_id)
        os.makedirs(job_dir, exist_ok=True)

        raw_snapshot = json.loads(json.dumps(job_data, ensure_ascii=False))
        ai_raw_data = raw_snapshot.pop("ai_raw_data", None)
        final_is_cleaned = bool(is_cleaned is True or ai_raw_data is not None)

        with self._lock:
            previous_meta = self._read_json(self._meta_path(job_id), default={}) or {}
            if not os.path.exists(self._raw_path(job_id)):
                self._write_json(self._raw_path(job_id), raw_snapshot)

            if final_is_cleaned:
                self._write_json(self._cleaned_path(job_id), raw_snapshot)
                if ai_raw_data is not None:
                    self._write_json(self._ai_raw_path(job_id), ai_raw_data)
            else:
                self._write_json(self._raw_path(job_id), raw_snapshot)

            meta = self._build_meta(job_id, raw_snapshot, previous_meta, final_is_cleaned)
            self._write_json(self._meta_path(job_id), meta)

            index_map = self._load_index_map()
            index_map[job_id] = meta
            self._rewrite_index(index_map)

    def list_pending_job_ids(self, limit=10):
        index_map = self._load_index_map()
        pending_records = [
            record for record in index_map.values() if int(record.get("is_cleaned", 0)) == 0
        ]
        pending_records.sort(key=lambda item: item.get("updated_at", ""))
        return [str(record["job_id"]) for record in pending_records[:limit]]

    def load_job(self, job_id, prefer_cleaned=True, include_ai_raw=True):
        job_id = str(job_id)
        primary_path = self._cleaned_path(job_id) if prefer_cleaned else self._raw_path(job_id)
        fallback_path = self._raw_path(job_id) if prefer_cleaned else self._cleaned_path(job_id)
        job = self._read_json(primary_path)
        if job is None:
            job = self._read_json(fallback_path)
        if job is None:
            return None
        if include_ai_raw:
            ai_raw_data = self._read_json(self._ai_raw_path(job_id))
            if ai_raw_data is not None:
                job = json.loads(json.dumps(job, ensure_ascii=False))
                job["ai_raw_data"] = ai_raw_data
        return job

    def get_pending_jobs(self, limit=10):
        jobs = []
        for job_id in self.list_pending_job_ids(limit=limit):
            job = self.load_job(job_id, prefer_cleaned=False, include_ai_raw=False)
            if job is not None:
                jobs.append(job)
        return jobs

    def get_all_jobs(self):
        index_map = self._load_index_map()
        records = sorted(index_map.values(), key=lambda item: item.get("updated_at", ""))
        jobs = []
        for record in records:
            job = self.load_job(record["job_id"])
            if job is not None:
                jobs.append(job)
        return jobs

    def get_jobs_by_ids(self, job_ids):
        jobs = []
        for job_id in job_ids:
            job = self.load_job(job_id)
            if job is not None:
                jobs.append(job)
        return jobs

    def job_exists(self, job_id):
        return os.path.exists(self._meta_path(job_id))
