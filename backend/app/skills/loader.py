"""Skills 加载器（按用户目录缓存，避免多租户下全局单例竞态）"""
import os
import threading
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from functools import lru_cache


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


def _singleton_skills_dir_placeholder() -> Path:
    """无 SKILLS_DIR 且未传入路径时的占位目录（可不创建）；业务请求请用 get_skills_loader_for_user。"""
    return Path(__file__).resolve().parents[2] / "data" / ".skills_singleton_unused"


class SkillsLoader:
    """Skills 加载器"""

    def __init__(self, skills_dir: str = None):
        if skills_dir is not None:
            self.skills_dir = Path(skills_dir)
        else:
            env = os.getenv("SKILLS_DIR")
            self.skills_dir = Path(env) if env else _singleton_skills_dir_placeholder()
        self.skills: Dict[str, Skill] = {}

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
        """获取技能指令（目录存在即启用）。"""
        instructions = []
        for skill in self.skills.values():
            instructions.append(f"## {skill.name}\n{skill.description}\n\n{skill.get_instruction()}")
        return "\n\n".join(instructions)

    def get_active_skills_index(self, skill_ids: Optional[List[str]] = None) -> str:
        """获取技能索引。skill_ids 为空则全部；否则仅包含指定 id 的技能。"""
        items = []
        for skill in self.skills.values():
            if skill_ids and skill.skill_id not in skill_ids:
                continue
            desc = (skill.description or "").strip()
            items.append(f"## {skill.name}\n{desc}")
        return "\n\n".join(items)

    def get_skill_routing_rules(self, skill_ids: Optional[List[str]] = None) -> str:
        """根据各技能的 description 动态生成技能选择规则。skill_ids 为空则全部。"""
        rules = []
        for skill in self.skills.values():
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

    def pick_best_skill_with_debug(
        self,
        combined_text: str,
        candidate_ids: List[str],
    ) -> Dict[str, Any]:
        """按 name/description 关键词为候选 skill 与 combined_text 的匹配度打分并择优。"""
        ids = [str(x).strip() for x in candidate_ids if str(x).strip()]
        debug: Dict[str, Any] = {
            "selected_skill_id": None,
            "strategy": "none",
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

        order = {sid: i for i, sid in enumerate(ids)}
        ranking_kw: List[Dict[str, Any]] = []
        for sid in ids:
            skill = self.skills.get(sid)
            if not skill:
                continue
            score = self.relevance_score_for_message(query, skill)
            ranking_kw.append({"skill_id": sid, "score": float(score)})
        if not ranking_kw:
            debug["strategy"] = "no_candidates"
            return debug
        ranking_kw.sort(key=lambda x: (-x["score"], order.get(str(x["skill_id"]), 999)))
        debug["scores"] = ranking_kw[:5]
        debug["strategy"] = "keyword"
        top = float(ranking_kw[0]["score"])
        if top > 0:
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


def get_builtin_skills_dir() -> Path:
    """内置技能目录：用户 skills 目录无同名 id 时由运行时合并加载。"""
    return Path(__file__).resolve().parent / "builtin_skills"


def merge_builtin_skills(loader: SkillsLoader) -> None:
    """将 builtin_skills 中用户尚未覆盖的 skill 并入 loader.skills。"""
    bid = get_builtin_skills_dir()
    if not bid.is_dir():
        return
    bl = SkillsLoader(str(bid))
    bl.load_all_skills()
    for sid, skill in bl.skills.items():
        if sid not in loader.skills:
            loader.skills[sid] = skill


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
    mtime = max(_skills_tree_mtime(sd), _skills_tree_mtime(get_builtin_skills_dir()))
    with _cache_lock:
        hit = _user_skill_cache.get(key)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        loader = SkillsLoader(str(sd))
        loader.load_all_skills()
        merge_builtin_skills(loader)
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
    """进程级默认 SkillsLoader（可选 SKILLS_DIR；未设置则空目录）。勿在多用户请求路径依赖此单例。"""
    global _skills_loader
    if _skills_loader is None:
        _skills_loader = SkillsLoader()
    return _skills_loader
