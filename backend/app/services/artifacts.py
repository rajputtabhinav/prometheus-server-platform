from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings


@dataclass
class StoredArtifact:
    artifact_id: str
    label: str
    artifact_type: str
    content_type: str
    file_path: str
    size_bytes: int
    metadata: dict[str, Any]


class ArtifactStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def reset_task_directory(self, task_id: str, file_paths: list[str]) -> None:
        for file_path in file_paths:
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError:
                pass
        task_dir = self.root / task_id
        if task_dir.exists():
            for child in task_dir.iterdir():
                if child.is_file():
                    try:
                        child.unlink()
                    except OSError:
                        pass

    def persist_result_artifacts(self, task_id: str, result: dict[str, Any]) -> list[StoredArtifact]:
        task_dir = self.root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        stored: list[StoredArtifact] = []

        raw_artifacts = result.get("artifacts")
        if isinstance(raw_artifacts, dict):
            for key, payload in raw_artifacts.items():
                stored.append(self._write_artifact(task_dir, task_id, key, payload))

        raw_log_excerpt = result.get("raw_log_excerpt")
        if isinstance(raw_log_excerpt, str) and raw_log_excerpt.strip():
            stored.append(self._write_text_artifact(task_dir, task_id, "raw_log_excerpt", raw_log_excerpt))

        return stored

    def _write_artifact(self, task_dir: Path, task_id: str, label: str, payload: Any) -> StoredArtifact:
        if isinstance(payload, str):
            return self._write_text_artifact(task_dir, task_id, label, payload)

        safe_label = self._safe_name(label)
        artifact_id = f"art-{secrets.token_hex(5)}"
        file_path = task_dir / f"{safe_label}.json"
        content = json.dumps(payload, indent=2, sort_keys=True, default=str)
        file_path.write_text(content, encoding="utf-8")
        return StoredArtifact(
            artifact_id=artifact_id,
            label=label,
            artifact_type="json",
            content_type="application/json",
            file_path=str(file_path),
            size_bytes=file_path.stat().st_size,
            metadata={"extension": ".json"},
        )

    def _write_text_artifact(self, task_dir: Path, task_id: str, label: str, payload: str) -> StoredArtifact:
        safe_label = self._safe_name(label)
        artifact_id = f"art-{secrets.token_hex(5)}"
        file_path = task_dir / f"{safe_label}.txt"
        file_path.write_text(payload, encoding="utf-8")
        return StoredArtifact(
            artifact_id=artifact_id,
            label=label,
            artifact_type="text",
            content_type="text/plain",
            file_path=str(file_path),
            size_bytes=file_path.stat().st_size,
            metadata={"extension": ".txt"},
        )

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_") or "artifact"


artifact_storage = ArtifactStorage(settings.artifact_root)
