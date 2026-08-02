"""Skills 加载器（按用户目录缓存，避免多租户下全局单例竞态）"""
import threading
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from functools import lru_cache


class Skill:
    """Skill 类"""

    def __init__(self, name: str, description: str, content: str, metadata: Dict[str, Any] = None, directory_name: str = None, skill_dir: Path = None, references: List[str] = None, assets: List[str] = None, other_files: List[str] = None):
        self.name = name
        self.description = description
        self.content = content
        self.metadata = metadata or {}
        self.directory_name = directory_name or name
        self.skill_dir = skill_dir          # Skill 目录的完整路径
        self.references = references or []   # references/ 下的文件相对路径
        self.assets = assets or []           # assets/ 下的文件相对路径
        self.other_files = other_files or [] # 其他附加文件相对路径（排除 scripts/、SKILL.md）

    def get_instruction(self) -> str:
        """获取技能指令"""
        return self.content


class SkillsLoader:
    """Skills 加载器"""

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, Skill] = {}
        self.diagnostics: List[Dict[str, Any]] = []

    def _record_diagnostic(self, skill_path: Path, code: str, message: str) -> None:
        self.diagnostics.append(
            {
                "directory_name": skill_path.name,
                "path": str(skill_path),
                "code": code,
                "message": message,
            }
        )

    def get_diagnostics(self) -> List[Dict[str, Any]]:
        """返回最近一次加载时发现的 Skill 契约问题。"""
        return [dict(item) for item in self.diagnostics]

    def load_skill(self, skill_path: Path) -> Optional[Skill]:
        """加载单个 Skill"""
        skill_file = skill_path / "SKILL.md"
        if not skill_file.exists():
            self._record_diagnostic(skill_path, "missing_skill_md", "Skill 目录缺少 SKILL.md")
            return None

        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 解析 YAML frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1])
                    if frontmatter is None:
                        frontmatter = {}
                    if not isinstance(frontmatter, dict):
                        raise ValueError("frontmatter must be a mapping")
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
            directory_name = skill_path.name

            # 扫描 Skill 目录下的附加文件（references、assets 等）
            references: List[str] = []
            assets: List[str] = []
            other_files: List[str] = []
            skill_dir_resolved = skill_path.resolve()
            if skill_dir_resolved.is_dir():
                for f in sorted(skill_dir_resolved.rglob("*")):
                    if not f.is_file():
                        continue
                    try:
                        rel = str(f.relative_to(skill_dir_resolved)).replace("\\", "/")
                    except ValueError:
                        continue
                    if rel == "SKILL.md" or rel.startswith("scripts/") or "/__pycache__/" in rel:
                        continue
                    if rel.startswith("references/"):
                        references.append(rel)
                    elif rel.startswith("assets/"):
                        assets.append(rel)
                    else:
                        other_files.append(rel)

            return Skill(name, description, body, metadata, directory_name, skill_dir_resolved, references, assets, other_files)
        except (yaml.YAMLError, ValueError) as e:
            self._record_diagnostic(skill_path, "invalid_frontmatter", f"Invalid SKILL.md frontmatter: {e}")
            return None
        except Exception as e:
            self._record_diagnostic(skill_path, "load_failed", f"Failed to load SKILL.md: {e}")
            print(f"Failed to load skill from {skill_path}: {e}")
            return None

    def load_all_skills(self) -> Dict[str, Skill]:
        """加载所有 Skills"""
        self.diagnostics = []
        if not self.skills_dir.exists():
            return {}

        self.skills = {}
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill = self.load_skill(skill_dir)
                if skill:
                    self.skills[skill.directory_name] = skill  # 用 directory_name（目录名）作为 key

        return self.skills

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
        """通用相关度：directory_name / name / description 关键词与 user_text 的匹配强度，无场景硬编码。"""
        t = (user_text or "").strip()
        if not t:
            return 0.0
        tl = t.lower()
        score = 0.0
        sid = (skill.directory_name or "").strip()
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
            "selected_directory_name": None,
            "strategy": "none",
            "scores": [],
        }
        if not ids:
            return debug
        if len(ids) == 1:
            debug["selected_directory_name"] = ids[0]
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
            ranking_kw.append({"directory_name": sid, "score": float(score)})
        if not ranking_kw:
            debug["strategy"] = "no_candidates"
            return debug
        ranking_kw.sort(key=lambda x: (-x["score"], order.get(str(x["directory_name"]), 999)))
        debug["scores"] = ranking_kw[:5]
        debug["strategy"] = "keyword"
        top = float(ranking_kw[0]["score"])
        if top > 0:
            debug["selected_directory_name"] = ranking_kw[0]["directory_name"]
        return debug

    def pick_best_directory_name_for_message(self, combined_text: str, candidate_ids: List[str]) -> Optional[str]:
        """在 candidate_ids 中按各 SKILL 的元数据与 combined_text 的相关度选出最佳 directory_name。

        不依赖 group_chat 内场景关键词表；新技能只需写好 name/description。无法区分时返回 None，由调用方按列表顺序回退。
        """
        return self.pick_best_skill_with_debug(combined_text, candidate_ids).get("selected_directory_name")

    def get_skill_full_content(self, directory_name: str) -> Optional[str]:
        """获取指定技能的完整内容（含 frontmatter 后的正文）。"""
        skill = self.skills.get(directory_name)
        if not skill:
            return None
        parts = [f"## {skill.name}\n{skill.description or ''}\n\n{skill.get_instruction()}"]
        extra_lines: List[str] = []
        for ref in sorted(skill.references):
            extra_lines.append(f"- {ref}")
        for asset in sorted(skill.assets):
            extra_lines.append(f"- {asset}")
        for other in sorted(skill.other_files):
            extra_lines.append(f"- {other}")
        if extra_lines:
            parts.append("\n---\n**本 Skill 附加文件（只读）：**")
            parts.extend(extra_lines)
        return "\n".join(parts)


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
    """用于缓存失效：目录及所有 skill 目录下全部文件的最新 mtime。

    不只检查 SKILL.md，而是覆盖 references/、assets/、scripts/ 等附加文件，
    避免新增/修改附加文件后 SkillsLoader 缓存仍是旧文件清单。
    """
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
            try:
                for p in child.rglob("*"):
                    if p.is_file() and "__pycache__" not in p.parts:
                        mt = max(mt, p.stat().st_mtime)
            except OSError:
                pass
    except OSError:
        pass
    return mt


_cache_lock = threading.Lock()
_user_skill_cache: Dict[str, Tuple[float, SkillsLoader]] = {}


def get_skills_loader_for_user(user_id: str, skills_dir: Path) -> SkillsLoader:
    """返回指定 user_id 技能目录对应的 SkillsLoader（带 mtime 缓存）。"""
    key = (user_id or "").strip()
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


def invalidate_skills_cache_for_user(user_id: str) -> None:
    """技能文件变更后使该用户的缓存失效。"""
    key = (user_id or "").strip()
    if not key:
        return
    with _cache_lock:
        _user_skill_cache.pop(key, None)
