"""Mô hình cấu hình hệ thống bằng Pydantic, tương thích hoàn toàn với settings.json của bản C#."""

import sys
import json
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict, PrivateAttr
from loguru import logger

class VoiceTemplate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(default="", alias="Name")
    voice_id: str = Field(default="21m00Tcm4TlvDq8ikWAM", alias="VoiceId")
    model_index: int = Field(default=0, alias="ModelIndex")
    lang_index: int = Field(default=0, alias="LangIndex")
    speed: float = Field(default=0.9, alias="Speed")
    style: int = Field(default=34, alias="Style")
    stability: int = Field(default=47, alias="Stability")
    similarity: int = Field(default=38, alias="Similarity")
    speaker_boost: bool = Field(default=False, alias="SpeakerBoost")

class FolderVoiceProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    folder_path: str = Field(default="", alias="FolderPath")
    voice: VoiceTemplate = Field(default_factory=VoiceTemplate, alias="Voice")

class FileVoiceProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    file_path: str = Field(default="", alias="FilePath")
    voice: VoiceTemplate = Field(default_factory=VoiceTemplate, alias="Voice")

class AppSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    eleven_labs_api_key: str = Field(default="", alias="ElevenLabsApiKey")
    voice_id: str = Field(default="21m00Tcm4TlvDq8ikWAM", alias="VoiceId")
    model_index: int = Field(default=0, alias="ModelIndex")
    lang_index: int = Field(default=0, alias="LangIndex")
    speed: float = Field(default=0.9, alias="Speed")
    style: int = Field(default=34, alias="Style")
    stability: int = Field(default=47, alias="Stability")
    similarity: int = Field(default=38, alias="Similarity")
    speaker_boost: bool = Field(default=False, alias="SpeakerBoost")
    
    voice_templates: List[VoiceTemplate] = Field(default_factory=list, alias="VoiceTemplates")
    selected_voice_template_name: str = Field(default="", alias="SelectedVoiceTemplateName")
    folder_voice_profiles: List[FolderVoiceProfile] = Field(default_factory=list, alias="FolderVoiceProfiles")
    file_voice_profiles: List[FileVoiceProfile] = Field(default_factory=list, alias="FileVoiceProfiles")
    
    static_proxies: str = Field(default="", alias="StaticProxies")
    rotating_proxies: str = Field(default="", alias="RotatingProxies")
    
    folder: str = Field(default="", alias="Folder")
    folders: List[str] = Field(default_factory=list, alias="Folders")
    custom_files: List[str] = Field(default_factory=list, alias="CustomFiles")
    excluded_files: List[str] = Field(default_factory=list, alias="ExcludedFiles")
    scan_subfolders: bool = Field(default=False, alias="ScanSubfolders")
    output_file_suffix: str = Field(default="", alias="OutputFileSuffix")
    
    silence_enabled: bool = Field(default=True, alias="SilenceEnabled")
    silence_value: float = Field(default=0.3, alias="SilenceValue")
    chunk_size: int = Field(default=500, alias="ChunkSize")
    thread_count: int = Field(default=1, alias="ThreadCount")
    continue_worker_on_blocking_errors: bool = Field(default=False, alias="ContinueWorkerOnBlockingErrors")
    _config_path: Optional[Path] = PrivateAttr(default=None)

    @classmethod
    def load(cls, file_path: Path | str = "settings.json") -> "AppSettings":
        path = Path(file_path)
        if not path.is_absolute() and getattr(sys, "frozen", False):
            candidate = Path(sys.executable).parent / path
            if candidate.exists() or not path.exists():
                path = candidate

        inst = cls()
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8")
                data = json.loads(content)
                logger.debug(f"Đã tải cấu hình từ {path.resolve()}")
                inst = cls.model_validate(data)
            except Exception as e:
                logger.warning(f"Lỗi đọc file cấu hình {path}: {e}. Dùng cấu hình mặc định.")
        inst._config_path = path.resolve()
        return inst

    def save(self, file_path: Optional[Path | str] = None) -> None:
        if file_path:
            target_path = Path(file_path)
            if not target_path.is_absolute() and getattr(sys, "frozen", False):
                target_path = Path(sys.executable).parent / target_path
        elif self._config_path:
            target_path = self._config_path
        else:
            if getattr(sys, "frozen", False):
                target_path = Path(sys.executable).parent / "settings.json"
            else:
                target_path = Path("settings.json")
        try:
            # Lưu theo alias để trùng khớp với định dạng PascalCase của C#
            data = self.model_dump(by_alias=True)
            target_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.debug(f"Đã lưu cấu hình ra {target_path.resolve()}")
        except Exception as e:
            logger.error(f"Không thể lưu cấu hình ra {target_path}: {e}")
