"""Skills 加载器（按用户目录缓存，避免多租户下全局单例竞态）"""
import os
import threading
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from functools import lru_cache

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except Exception:  # pragma: no cover - import 失败时自动回退到旧逻辑
    TfidfVectorizer = None
    cosine_similarity = None


class Skill:
    """Skill 类"""

    def __init__(self, name: str, description: str, content: str, metadata: Dict[str, Any] = None, skill_id: str = None):
        self.name = name
        self.description = description
        self.content = content
        self.metadata = metadata or {}
        self.skill_id = skill_id or name  # 目录名，用于筛选

    def get_instruction(self) -> str:
        """获取技能指令"""
        return self.content


class SkillsLoader:
    """Skills 加载器"""

    def __init__(self, skills_dir: str = None):
        self.skills_dir = Path(skills_dir or os.getenv("SKILLS_DIR", "./skills"))
        self.skills: Dict[str, Skill] = {}
        self._tfidf_bundle_cache: Dict[Tuple[str, ...], Tuple[List[str], Any, Any]] = {}

    def load_skill(self, skill_path: Path) -> Optional[Skill]:
        """加载单个 Skill"""
        skill_file = skill_path / "SKILL.md"
        if not skill_file.exists():
            return None

        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 解析 YAML frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1])
                    body = parts[2].strip()
                else:
                    frontmatter = {}
                    body = content
            else:
                frontmatter = {}
                body = content

            name = frontmatter.get("name", skill_path.name)
            description = frontmatter.get("description", "")
            metadata = frontmatter
            skill_id = skill_path.name  # 目录名
            return Skill(name, description, body, metadata, skill_id)
        except Exception as e:
            print(f"Failed to load skill from {skill_path}: {e}")
            return None

    def load_all_skills(self) -> Dict[str, Skill]:
        """加载所有 Skills"""
        if not self.skills_dir.exists():
            return {}

        self.skills = {}
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill = self.load_skill(skill_dir)
                if skill:
                    self.skills[skill.skill_id] = skill  # 用 skill_id（目录名）作为 key

        return self.skills

    def get_active_skills_instructions(self) -> str:
        """获取所有启用（enabled）技能的指令"""
        instructions = []
        for skill in self.skills.values():
            if not skill.metadata.get("enabled", True):
                continue
            instructions.append(f"## {skill.name}\n{skill.description}\n\n{skill.get_instruction()}")
        return "\n\n".join(instructions)

    def get_active_skills_index(self, skill_ids: Optional[List[str]] = None) -> str:
        """获取启用技能的索引。skill_ids 为空则全部；否则仅包含指定 id 的技能"""
        items = []
        for skill in self.skills.values():
            if not skill.metadata.get("enabled", True):
                continue
            if skill_ids and skill.skill_id not in skill_ids:
                continue
            desc = (skill.description or "").strip()
            items.append(f"## {skill.name}\n{desc}")
        return "\n\n".join(items)

    def get_skill_routing_rules(self, skill_ids: Optional[List[str]] = None) -> str:
        """根据各技能的 description 动态生成技能选择规则。skill_ids 为空则全部"""
        rules = []
        for skill in self.skills.values():
            if not skill.metadata.get("enabled", True):
                continue
            if skill_ids and skill.skill_id not in skill_ids:
                continue
            desc = skill.description
            if desc:
                if len(desc) > 120:
                    desc = desc[:117] + "..."
                rules.append(f"- **{desc}** → 使用 **{skill.name}**，按该技能说明执行。")
        return "\n".join(rules) if rules else ""

    def infer_skill_from_message(self, message: str) -> Optional[str]:
        """根据用户消息与各技能的 description 推断应使用的 skill（用于 meta 展示）"""
        if not message or not message.strip():
            return None
        t = message.strip()
        for skill in self.skills.values():
            if not skill.metadata.get("enabled", True):
                continue
            desc = skill.description
            if not desc:
                continue
            # 从 description 提取关键词（按 /、。（） 等分割）
            desc_clean = str(desc).split("。")[0].split("（")[0].split("(")[0]
            keywords = [
                k.strip()
                for k in desc_clean.replace("、", "/").replace("，", "/").split("/")
                if k.strip() and len(k.strip()) >= 2
            ]
            if any(kw in t for kw in keywords):
                return skill.name
        return None

    @staticmethod
    def _keywords_from_description_line(desc: str) -> List[str]:
        """从 description 首句切出短语，供与用户文本做子串匹配（与 infer_skill_from_message 一致思路）。"""
        if not (desc or "").strip():
            return []
        desc_clean = str(desc).split("。")[0].split("（")[0].split("(")[0]
        return [
            k.strip()
            for k in desc_clean.replace("、", "/").replace("，", "/").split("/")
            if k.strip() and len(k.strip()) >= 2
        ]

    def relevance_score_for_message(self, user_text: str, skill: Skill) -> float:
        """通用相关度：skill_id / name / description 关键词与 user_text 的匹配强度，无场景硬编码。"""
        t = (user_text or "").strip()
        if not t:
            return 0.0
        tl = t.lower()
        score = 0.0
        sid = (skill.skill_id or "").strip()
        # 用户显式写出目录名或常见变体
        if sid:
            if sid in t or sid in tl:
                score += 12.0
            for part in sid.replace("_", "-").split("-"):
                pl = part.lower()
                if len(pl) >= 3 and (pl in tl or part in t):
                    score += 2.5
        name = (skill.name or "").strip()
        if len(name) >= 2 and name in t:
            score += 5.0
        for kw in self._keywords_from_description_line(skill.description or ""):
            if kw in t:
                score += min(float(len(kw)), 16.0) * 0.45
        return score

    @staticmethod
    @lru_cache(maxsize=1)
    def _tfidf_min_score() -> float:
        """最低命中阈值：低于该分数则视为不确定，交由上层回退。"""
        raw = os.getenv("SKILL_ROUTER_TFIDF_MIN_SCORE", "0.12").strip()
        try:
            return max(0.0, min(1.0, float(raw)))
        except Exception:
            return 0.12

    def _build_skill_route_text(self, skill: Skill) -> str:
        """构造用于 TF-IDF 向量化的 skill 文本（仅名称 + 描述）。"""
        name = (skill.name or "").strip()
        desc = (skill.description or "").strip()
        return "\n".join([x for x in [name, desc] if x]).strip()

    def _get_tfidf_bundle(self, candidate_ids: List[str]) -> Optional[Tuple[List[str], Any, Any]]:
        """按候选技能构建（或复用）TF-IDF 向量化结果。"""
        if TfidfVectorizer is None:
            return None
        key = tuple(candidate_ids)
        cached = self._tfidf_bundle_cache.get(key)
        if cached is not None:
            return cached

        active_ids: List[str] = []
        docs: List[str] = []
        for sid in candidate_ids:
            skill = self.skills.get(sid)
            if not skill or not skill.metadata.get("enabled", True):
                continue
            route_text = self._build_skill_route_text(skill)
            if not route_text:
                continue
            active_ids.append(sid)
            docs.append(route_text)

        if len(active_ids) < 2:
            return None

        vectorizer = TfidfVectorizer(
            analyzer="char_wb",  # 对中文短句更稳，不依赖分词器
            ngram_range=(2, 4),
            lowercase=True,
            sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform(docs)
        bundle = (active_ids, vectorizer, matrix)
        self._tfidf_bundle_cache[key] = bundle
        return bundle

    def pick_best_skill_with_debug(self, combined_text: str, candidate_ids: List[str]) -> Dict[str, Any]:
        """返回路由决策详情，供日志/调试使用。"""
        ids = [str(x).strip() for x in candidate_ids if str(x).strip()]
        debug: Dict[str, Any] = {
            "selected_skill_id": None,
            "strategy": "none",
            "min_score": self._tfidf_min_score(),
            "tfidf_available": bool(TfidfVectorizer is not None and cosine_similarity is not None),
            "scores": [],
        }
        if not ids:
            return debug
        if len(ids) == 1:
            debug["selected_skill_id"] = ids[0]
            debug["strategy"] = "single_candidate"
            return debug

        query = (combined_text or "").strip()
        if not query:
            debug["strategy"] = "empty_query"
            return debug

        # 首选本地 TF-IDF 语义匹配
        bundle = self._get_tfidf_bundle(ids)
        if bundle and cosine_similarity is not None:
            active_ids, vectorizer, matrix = bundle
            try:
                q_vec = vectorizer.transform([query])
                sims = cosine_similarity(q_vec, matrix)
                if sims is not None and len(sims) > 0 and len(sims[0]) > 0:
                    row = sims[0]
                    ranking = sorted(
                        [{"skill_id": active_ids[i], "score": float(row[i])} for i in range(len(row))],
                        key=lambda x: x["score"],
                        reverse=True,
                    )
                    debug["scores"] = ranking[:5]
                    best = ranking[0]
                    debug["strategy"] = "tfidf"
                    if float(best["score"]) >= float(debug["min_score"]):
                        debug["selected_skill_id"] = best["skill_id"]
                        return debug
                    debug["strategy"] = "tfidf_below_threshold"
            except Exception:
                debug["strategy"] = "tfidf_error"

        # 兜底：关键词打分
        order = {sid: i for i, sid in enumerate(ids)}
        ranking_kw: List[Dict[str, Any]] = []
        for sid in ids:
            skill = self.skills.get(sid)
            if not skill or not skill.metadata.get("enabled", True):
                continue
            score = self.relevance_score_for_message(query, skill)
            ranking_kw.append({"skill_id": sid, "score": float(score)})
        if not ranking_kw:
            debug["strategy"] = "no_enabled_candidates"
            return debug
        ranking_kw.sort(key=lambda x: (-x["score"], order.get(str(x["skill_id"]), 999)))
        debug["scores"] = ranking_kw[:5]
        debug["strategy"] = "keyword_fallback"
        if float(ranking_kw[0]["score"]) > 0:
            debug["selected_skill_id"] = ranking_kw[0]["skill_id"]
        return debug

    def pick_best_skill_id_for_message(self, combined_text: str, candidate_ids: List[str]) -> Optional[str]:
        """在 candidate_ids 中按各 SKILL 的元数据与 combined_text 的相关度选出最佳 skill_id。

        不依赖 group_chat 内场景关键词表；新技能只需写好 name/description。无法区分时返回 None，由调用方按列表顺序回退。
        """
        return self.pick_best_skill_with_debug(combined_text, candidate_ids).get("selected_skill_id")

    def get_skills_metadata(self) -> List[Dict[str, Any]]:
        """获取所有技能的元数据"""
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "metadata": skill.metadata,
            }
            for skill in self.skills.values()
        ]

    def get_skills_for_selection(self, skill_ids: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """获取用于技能选择的精简列表，仅含 name、description（若有）。
        skill_ids 为空则全部；否则仅包含指定 id 的技能。
        default 技能始终放在最后，作为无法确定时的备用选项。"""
        items = []
        default_item = None
        for skill in self.skills.values():
            if not skill.metadata.get("enabled", True):
                continue
            if skill_ids and skill.skill_id not in skill_ids:
                continue
            d: Dict[str, str] = {"skill_id": skill.skill_id, "name": skill.name}
            if skill.description and str(skill.description).strip():
                d["description"] = str(skill.description).strip()
            if skill.skill_id == "default":
                default_item = d
            else:
                items.append(d)
        if default_item:
            items.append(default_item)
        return items

    def get_skill_full_content(self, skill_id: str) -> Optional[str]:
        """获取指定技能的完整内容（含 frontmatter 后的正文）。"""
        skill = self.skills.get(skill_id)
        if not skill:
            return None
        return f"## {skill.name}\n{skill.description or ''}\n\n{skill.get_instruction()}"


def _skills_tree_mtime(skills_dir: Path) -> float:
    """用于缓存失效：目录及下一层各 skill 的 SKILL.md 的最新 mtime。"""
    if not skills_dir.exists():
        return 0.0
    try:
        mt = skills_dir.stat().st_mtime
    except OSError:
        return 0.0
    try:
        for child in skills_dir.iterdir():
            if not child.is_dir():
                continue
            sf = child / "SKILL.md"
            if sf.is_file():
                try:
                    mt = max(mt, sf.stat().st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return mt


_cache_lock = threading.Lock()
_user_skill_cache: Dict[str, Tuple[float, SkillsLoader]] = {}


def get_skills_loader_for_user(username: str, skills_dir: Path) -> SkillsLoader:
    """返回指定用户技能目录对应的 SkillsLoader（带 mtime 缓存）。"""
    key = (username or "").strip()
    if not key:
        key = "_anonymous"
    sd = skills_dir.resolve()
    mtime = _skills_tree_mtime(sd)
    with _cache_lock:
        hit = _user_skill_cache.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        loader = SkillsLoader(str(sd))
        loader.load_all_skills()
        _user_skill_cache[key] = (mtime, loader)
        return loader


def invalidate_skills_cache_for_user(username: str) -> None:
    """技能文件变更后使该用户的缓存失效。"""
    key = (username or "").strip()
    if not key:
        return
    with _cache_lock:
        _user_skill_cache.pop(key, None)


def invalidate_all_skills_cache() -> None:
    with _cache_lock:
        _user_skill_cache.clear()


# 仅用于无用户上下文场景（例如旧测试）；业务路径请用 get_skills_loader_for_user。
_skills_loader: Optional[SkillsLoader] = None


def get_skills_loader() -> SkillsLoader:
    """进程级默认 SkillsLoader（./skills 或 SKILLS_DIR），勿在多用户请求路径依赖此单例。"""
    global _skills_loader
    if _skills_loader is None:
        _skills_loader = SkillsLoader()
    return _skills_loader
