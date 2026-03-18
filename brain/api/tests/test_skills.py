"""Unit tests for the brain skill system."""

import os
import shutil
import tempfile
import yaml
import pytest
from pathlib import Path
from tools.skill import SkillManifest, SkillToolDefinition
from tools.skill_manager import SkillManager


@pytest.fixture
def temp_skills_dir():
    """Create a temporary directory for skills."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


def test_skill_manifest_creation():
    """Test manual creation of a SkillManifest."""
    tool = SkillToolDefinition(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object", "properties": {}}
    )
    manifest = SkillManifest(
        id="test-skill",
        name="Test Skill",
        description="Testing skill manifest",
        tools=[tool]
    )
    assert manifest.id == "test-skill"
    assert len(manifest.tools) == 1
    assert manifest.tools[0].name == "test_tool"


def test_skill_manager_discovery(temp_skills_dir):
    """Test that SkillManager discovers valid skills."""
    # Create a valid skill
    skill_path = temp_skills_dir / "valid_skill"
    skill_path.mkdir()
    
    manifest_data = {
        "id": "valid_skill",
        "name": "Valid Skill",
        "description": "A valid skill for testing",
        "tools": [
            {
                "name": "hello",
                "description": "Says hello",
                "parameters": {"type": "object", "properties": {}}
            }
        ]
    }
    
    with open(skill_path / "skill.yaml", "w") as f:
        yaml.dump(manifest_data, f)
    
    # Create an invalid skill (no skill.yaml)
    (temp_skills_dir / "invalid_skill").mkdir()
    
    manager = SkillManager(str(temp_skills_dir))
    manager.scan_and_load_skills()
    
    assert "valid_skill" in manager.skills
    assert "invalid_skill" not in manager.skills
    assert len(manager.skills) == 1
    
    skill = manager.skills["valid_skill"]
    assert skill.manifest.name == "Valid Skill"
    assert len(skill.manifest.tools) == 1


def test_skill_manager_import_handlers(temp_skills_dir):
    """Test that SkillManager imports handlers from main.py."""
    skill_path = temp_skills_dir / "handler_skill"
    skill_path.mkdir()
    
    manifest_data = {
        "id": "handler_skill",
        "tools": [{"name": "test_handler", "description": "test", "parameters": {}}]
    }
    with open(skill_path / "skill.yaml", "w") as f:
        yaml.dump(manifest_data, f)
        
    implementation = """
def test_handler(args):
    return {"status": "ok", "message": "hello from skill"}
"""
    with open(skill_path / "main.py", "w") as f:
        f.write(implementation)
        
    manager = SkillManager(str(temp_skills_dir))
    manager.scan_and_load_skills()
    
    skill = manager.skills["handler_skill"]
    assert "test_handler" in skill.handlers
    handler = skill.handlers["test_handler"]
    assert handler({"some": "args"}) == {"status": "ok", "message": "hello from skill"}
