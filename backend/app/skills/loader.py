"""Skills 加载器"""
import os
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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
    
    def load_skill(self, skill_path: Path) -> Optional[Skill]:
        """加载单个 Skill"""
        skill_file = skill_path / "SKILL.md"
        if not skill_file.exists():
            return None
        
        try:
            with open(skill_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析 YAML frontmatter
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1])
                    body = parts[2].strip()
                else:
                    frontmatter = {}
                    body = content
            else:
                frontmatter = {}
                body = content
            
            name = frontmatter.get('name', skill_path.name)
            description = frontmatter.get('description', '')
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
            keywords = [k.strip() for k in desc_clean.replace("、", "/").replace("，", "/").split("/") if k.strip() and len(k.strip()) >= 2]
            if any(kw in t for kw in keywords):
                return skill.name
        return None
    
    def get_skills_metadata(self) -> List[Dict[str, Any]]:
        """获取所有技能的元数据"""
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "metadata": skill.metadata
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
