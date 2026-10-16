"""Local structured profile. Retrieval is deliberately an interface, not a vector DB."""
import hashlib
import json
from pathlib import Path
from typing import Protocol, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from core.config import resolve, ROOT
from core.errors import InsightError


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ordinary: Literal['digest', 'immediate'] = 'digest'
    archive_uninterested: bool = False
    relevant: Literal['immediate', 'digest'] = 'immediate'


class Interest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=80)
    terms: list[str] = Field(min_length=1, max_length=30)
    intents: list[str] = Field(default_factory=list, max_length=30)
    avoid: list[str] = Field(default_factory=list, max_length=30)
    description: str = Field(default='', max_length=500)


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    is_example: bool = False
    grade: str = ''
    major: str = ''
    stage: str = ''
    research_interests: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=30)
    projects: list[str] = Field(default_factory=list, max_length=30)
    competitions: list[str] = Field(default_factory=list, max_length=30)
    goals: list[str] = Field(default_factory=list, max_length=30)
    opportunities: list[str] = Field(default_factory=list, max_length=30)
    uninterested: list[str] = Field(default_factory=list, max_length=30)
    preferences: Preferences = Field(default_factory=Preferences)
    interests: list[Interest] = Field(default_factory=list, max_length=20)

    def fingerprint(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def path(cfg):
    # Default profile is account scoped, just like notices and sessions.
    from core.pipeline import database_path
    configured = cfg.get('ai', {}).get('profile_path')
    return resolve(cfg, configured) if configured else database_path(cfg).parent / 'profile.yaml'


def load(cfg):
    file = path(cfg)
    if not file.exists():
        return Profile()
    try:
        if file.stat().st_size > 64000:
            raise ValueError()
        result = Profile.model_validate(yaml.safe_load(file.read_text(encoding='utf-8')) or {})
        if result.is_example:
            raise ValueError('example is not user data')
        return result
    except Exception:
        raise InsightError('profile_invalid', '个人画像格式无效或仍标记为示例；未输出私人内容') from None


def initialize(cfg):
    file = path(cfg)
    if file.exists():
        raise InsightError('profile_exists', '个人画像已存在，保留原文件')
    file.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: never overwrite a concurrently edited profile.
    with file.open('x', encoding='utf-8') as stream:
        stream.write((ROOT / 'examples' / 'profile.blank.yaml').read_text(encoding='utf-8'))
    return str(file)


class KnowledgeProvider(Protocol):
    def relevant_context(self, query: str) -> list[dict]:
        """Future local Markdown/PDF retrieval; each result must include provenance."""
        ...
