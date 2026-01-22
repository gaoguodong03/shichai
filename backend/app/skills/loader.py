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
    def __init__(self, name: str, description: str, content: str, metadata: Dict[str, Any] = None):
        self.name = name
        self.description = description
        self.content = content
        self.metadata = metadata or {}
    
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
            
            return Skill(name, description, body, metadata)
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
                    self.skills[skill.name] = skill
        
        return self.skills
    
    def get_active_skills_instructions(self) -> str:
        """获取所有激活技能的指令"""
        instructions = []
        for skill in self.skills.values():
            instructions.append(f"## {skill.name}\n{skill.description}\n\n{skill.get_instruction()}")
        return "\n\n".join(instructions)
    
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
