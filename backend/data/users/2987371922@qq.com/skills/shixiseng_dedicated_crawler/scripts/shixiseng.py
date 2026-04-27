import json
import time
import os
import re
import random
from urllib.parse import quote
from scrapling.fetchers import StealthySession
from file_store import FileStore

class ShixisengScraper:
    OFFICIAL_MAP = {"不限": "", "提供转正": "entry", "不提供转正": "noentry", "面议": "notsure"}
    CONVERSION_MAP = {"entry": "提供转正", "noentry": "不提供转正", "notsure": "面议"}
    ENTERPRISE_MAP = {"不限": "", "知名企业": "known", "互联网300强": "internet300"}
    MONTHS_MAP = {"不限": "", "一月": "1", "两月": "2", "三月": "3", "三月以上": "3-100"}
    DAYS_MAP = {"不限": "", "一天": "1", "两天": "2", "三天": "3", "四天": "4", "五天": "5", "六天及以上": "6"}

    def __init__(self, storage_dir=os.path.join("scripts", "job_store")):
        self.store = FileStore(storage_dir)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assets_dir = os.path.join(project_root, "assets")
        self._load_configs()
        self.company_cache = {}

    def _load_configs(self):
        task_path = os.path.join(self.assets_dir, "task.json")
        target_path = os.path.join(self.assets_dir, "target.json")
        if os.path.exists(task_path):
            with open(task_path, "r", encoding="utf-8") as f:
                self.task_config = json.load(f)
        else:
            self.task_config = {"categories": ["互联网IT"], "default_filters": {}, "runtime": {"max_pages_per_category": 5}}
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                self.target_config = json.load(f)
        else:
            self.target_config = {"base_url": "https://www.shixiseng.com", "list_endpoint": "/interns"}

    def parse_numbers(self, text):
        if not text: return []
        nums = re.findall(r"\d+", str(text))
        return [int(n) for n in nums]

    def _extract_company_details(self, session, company_url, company_id):
        if company_id in self.company_cache: return self.company_cache[company_id]
        c_fin, c_cert = "null", False
        try:
            company_page = session.fetch(company_url)
            time.sleep(random.uniform(0.5, 1.0))
            if company_page.css("a[title*='认证']"): c_cert = True
            header_p = company_page.css(".com-login-tips p::text").get()
            if header_p:
                for p in [x.strip() for x in header_p.split('·')]:
                    if any(kw in p for kw in ["轮", "上市", "融资", "天使"]):
                        c_fin = p
                        break
            if c_fin == "null":
                for d in company_page.css(".com-msg_detail::text").getall():
                    if any(kw in d for kw in ["轮", "上市", "融资", "天使"]):
                        c_fin = d.strip()
                        break
        except: pass
        details = {"finance": c_fin, "certified": c_cert}
        self.company_cache[company_id] = details
        return details

    def run(self, categories=None, limit_pages=None, custom_filters=None):
        processed_ids = []
        cats = categories or self.task_config.get("categories", [])
        base_url = self.target_config.get("base_url", "https://www.shixiseng.com")
        list_endpoint = self.target_config.get("list_endpoint", "/interns")
        active_filters = self.task_config.get("default_filters", {}).copy()
        if custom_filters: active_filters.update(custom_filters)
        timeout = self.task_config.get("runtime", {}).get("timeout", 30000)
        
        with StealthySession(headless=True, real_chrome=False, timeout=timeout) as session:
            for cat in cats:
                official_options = [active_filters.get("official")]
                if not active_filters.get("official") or active_filters.get("official") == "不限":
                    official_options = ["提供转正", "不提供转正", "面议"]
                for off_option in official_options:
                    encoded_cat = quote(cat)
                    off_code = self.OFFICIAL_MAP.get(off_option, "")
                    ent_code = self.ENTERPRISE_MAP.get(active_filters.get("enterprise"), "")
                    mon_code = self.MONTHS_MAP.get(active_filters.get("months"), "")
                    day_code = self.DAYS_MAP.get(active_filters.get("days"), "")
                    deg_val = "" if active_filters.get("degree") == "不限" else quote(active_filters.get("degree", ""))
                    cit_val = quote(active_filters.get("city", "全国"))
                    page_num = 1
                    runtime_cfg = self.task_config.get("runtime", {})
                    cfg_pages = runtime_cfg.get("max_pages")
                    if cfg_pages is None:
                        cfg_pages = runtime_cfg.get("max_pages_per_category", 5)
                    max_pages = limit_pages if limit_pages is not None else cfg_pages
                    while page_num <= max_pages:
                        list_url = f"{base_url}{list_endpoint}?page={page_num}&type=intern&keyword={encoded_cat}&degree={deg_val}&official={off_code}&enterprise={ent_code}&city={cit_val}&area=&months={mon_code}&days={day_code}"
                        print(f"📂 分类: {cat} | 选项: {off_option} | 📄 第 {page_num} 页")
                        print(f"🔗 Crawling: {list_url}")
                        try:
                            page = session.fetch(list_url)
                            items = page.css(".intern-wrap.intern-item")
                            if not items or len(items) == 0: break
                            if "暂无职位" in page.text: break
                            for item in items:
                                job_href = item.css(".intern-detail__job a::attr(href)").get()
                                if not job_href: continue
                                full_job_url = f"{base_url}{job_href}" if job_href.startswith("/") else job_href
                                job_id = job_href.split("?")[0].split("/")[-1]
                                processed_ids.append(job_id)
                                try:
                                    detail_page = session.fetch(full_job_url)
                                    time.sleep(random.uniform(0.5, 1.0))
                                    current_refresh = (detail_page.css(".job_date span.cutom_font::text").get() or detail_page.css(".job_date span.custom_font::text").get() or "").strip()
                                    stored_refresh = self.store.get_refresh_at_stored(job_id)
                                    if current_refresh and current_refresh == stored_refresh: continue
                                    raw_addr = (detail_page.css(".job_city .com_position::text").get() or "null").strip()
                                    city_ext = (detail_page.css(".job_position::text").get() or "null").strip()
                                    state_val = "null"
                                    if raw_addr != "null":
                                        temp_addr = re.sub(r"^.*?[市]", "", raw_addr).strip().strip("/")
                                        m = re.search(r"([\u4e00-\u9fa5]+?[区县])", temp_addr)
                                        if m: state_val = m.group(1)
                                        else:
                                            m_alt = re.search(r"([^市/]+?[区县])", raw_addr)
                                            if m_alt: state_val = m_alt.group(1).strip()
                                    res_val, dead_val = "null", "null"
                                    for block in detail_page.css(".con-job"):
                                        text = "".join(block.css("*::text").getall())
                                        if "投递要求" in text:
                                            r_m = re.search(r"简历要求\s*[：:]\s*([\u4e00-\u9fa5/]+)", text)
                                            if r_m: res_val = r_m.group(1).strip()
                                            d_m = re.search(r"截止日期\s*[：:]\s*(\d{4}-\d{2}-\d{2})", text)
                                            if d_m: dead_val = d_m.group(1).strip()
                                    salary_raw = (detail_page.css(".job_money::text").get() or "0").strip()
                                    s_nums = self.parse_numbers(salary_raw)
                                    minsal, maxsal = (s_nums[0], s_nums[1]) if len(s_nums) >= 2 else (s_nums[0], s_nums[0]) if s_nums else (0, 0)
                                    comp_id, comp_url = "null", "null"
                                    scripts = "".join(detail_page.css("script::text").getall())
                                    id_m = re.search(r"cuuid\s*[:=]\s*['\"](com_[^'\"]+)['\"]", scripts)
                                    if id_m:
                                        comp_id = id_m.group(1)
                                        comp_url = f"{base_url}/com/{comp_id}"
                                    c_details = {"finance": "null", "certified": False}
                                    if comp_url != "null": c_details = self._extract_company_details(session, comp_url, comp_id)
                                    aligned_data = {
                                        "job_schema": {
                                            "basic_info": {
                                                "job_id": job_id, "title": (detail_page.css(".new_job_name span::text").get() or detail_page.css(".job_name::text").get() or "未知职位").strip(),
                                                "job_type": f"实习_{cat}", "category": (detail_page.css(".baike-box .head h4::text").get() or "null").strip(),
                                                "tags": detail_page.css(".job_good_list span::text").getall(),
                                                "location": {"country": "China", "city": city_ext, "state": state_val, "office_address": raw_addr, "is_remote": "null"}
                                            },
                                            "requirements": {
                                                "experience": "null", "education": (detail_page.css(".job_msg span:nth-child(3)::text").get() or "null").strip(),
                                                "major_requirements": {"target_majors": [], "allow_related": True, "requirement_level": "preferred", "origin_str": "null"},
                                                "skills_required": [], "languages": [],
                                                "internship_specific": {
                                                    "duty_days_per_week": self.parse_numbers(detail_page.css(".job_week::text").get())[0] if self.parse_numbers(detail_page.css(".job_week::text").get()) else 0,
                                                    "duration_months": self.parse_numbers(detail_page.css(".job_time::text").get())[0] if self.parse_numbers(detail_page.css(".job_time::text").get()) else 0,
                                                    "conversion_chance": self.CONVERSION_MAP.get(off_code, "null")
                                                },
                                                "deadline": dead_val, "resume": res_val, "origin_str": "null"
                                            },
                                            "compensation": {
                                                "salary": {"min": minsal, "max": maxsal, "unit": "day", "currency": "CNY", "origin_str": salary_raw},
                                                "benefits": []
                                            },
                                            "company_info": {
                                                "company_id": comp_id, "name": (detail_page.css(".com-name::text").get() or "null").strip(),
                                                "industry": (detail_page.xpath("//i[contains(@class, 'iconhangyelingyu')]/parent::div/text()").get() or "null").strip(),
                                                "size": (detail_page.xpath("//i[contains(@class, 'iconqiyeguimo')]/parent::div/text()").get() or "null").strip(),
                                                "type": (detail_page.xpath("//i[contains(@class, 'iconqiyexingzhi')]/parent::div/text()").get() or "null").strip(),
                                                "finance_stage": c_details["finance"], "description": (detail_page.css(".com-desc::text").get() or "null").strip().replace('"', ''),
                                                "url": comp_url, "is_certified": c_details["certified"]
                                            },
                                            "description": {"team_intro": "null", "position_description": "null", "related_jobs": [], "origin_str": "".join(detail_page.css(".job_part *::text").getall()).strip()},
                                            "metadata": {
                                                "platform": "shixiseng", "url": full_job_url, "posted_at": "null", "is_easy_apply": True,
                                                "refresh_at": current_refresh, "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "active"
                                            }
                                        }
                                    }
                                    self.store.save_job_full(aligned_data)
                                    print(f"✅ Saved: {aligned_data['job_schema']['basic_info']['title']}")
                                except Exception as e:
                                    print(f"❌ Detail Error: {full_job_url} | {e}")
                            page_num += 1
                            time.sleep(random.uniform(1.0, 2.0))
                        except Exception as e:
                            print(f"❌ List Error: {list_url} | {e}")
                            break
        return list(set(processed_ids))

if __name__ == "__main__":
    scraper = ShixisengScraper()
    scraper.run(limit_pages=1)
