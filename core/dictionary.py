"""
사용자 사전 관리 모듈

사전 파일 형식 (탭 구분 MD):
원어	번역어	조건(선택)
漢字	한자
お兄ちゃん	오빠
先輩	선배	honorific
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DictionaryEntry:
    """사전 항목"""
    source: str       # 원어
    target: str       # 번역어
    condition: str    # 적용 조건 (선택적)

    def __str__(self):
        if self.condition:
            return f"{self.source} → {self.target} ({self.condition})"
        return f"{self.source} → {self.target}"


class UserDictionary:
    """사용자 사전 클래스"""

    def __init__(self, dict_path: Optional[str] = None):
        self.entries: list[DictionaryEntry] = []
        self.dict_path = dict_path
        if dict_path and os.path.exists(dict_path):
            self.load(dict_path)

    def load(self, dict_path: str) -> None:
        """사전 파일 로드 (탭 구분 MD 형식)"""
        self.entries = []
        self.dict_path = dict_path

        with open(dict_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line in lines:
            line = line.strip()

            # 빈 줄, 주석, 헤더 무시
            if not line or line.startswith('#') or line.startswith('|'):
                continue

            # 마크다운 테이블 구분선 무시
            if re.match(r'^[\|\-\s:]+$', line):
                continue

            # 탭 구분으로 파싱
            parts = line.split('\t')
            if len(parts) >= 2:
                source = parts[0].strip()
                target = parts[1].strip()
                condition = parts[2].strip() if len(parts) > 2 else ""

                if source and target:
                    self.entries.append(DictionaryEntry(
                        source=source,
                        target=target,
                        condition=condition
                    ))

    def save(self, dict_path: Optional[str] = None) -> None:
        """사전 파일 저장"""
        path = dict_path or self.dict_path
        if not path:
            raise ValueError("저장 경로가 지정되지 않았습니다")

        with open(path, 'w', encoding='utf-8') as f:
            f.write("# 사용자 사전\n")
            f.write("# 형식: 원어<TAB>번역어<TAB>조건(선택)\n\n")
            for entry in self.entries:
                if entry.condition:
                    f.write(f"{entry.source}\t{entry.target}\t{entry.condition}\n")
                else:
                    f.write(f"{entry.source}\t{entry.target}\n")

    def add_entry(self, source: str, target: str, condition: str = "") -> None:
        """항목 추가"""
        self.entries.append(DictionaryEntry(source, target, condition))

    def remove_entry(self, source: str) -> bool:
        """항목 삭제"""
        for i, entry in enumerate(self.entries):
            if entry.source == source:
                del self.entries[i]
                return True
        return False

    def get_context_prompt(self) -> str:
        """
        번역 프롬프트에 포함할 사전 컨텍스트 생성
        LLM에게 사전 내용을 전달하여 번역 시 참조하도록 함
        """
        if not self.entries:
            return ""

        lines = ["[사용자 사전 - 아래 용어들은 반드시 지정된 번역어를 사용하세요]"]
        for entry in self.entries:
            if entry.condition:
                lines.append(f"- {entry.source} → {entry.target} (조건: {entry.condition})")
            else:
                lines.append(f"- {entry.source} → {entry.target}")

        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return len(self.entries) > 0


def get_dictionary_for_pair(source_lang: str, target_lang: str, base_dir: str) -> Optional[UserDictionary]:
    """언어쌍에 맞는 사전 파일 찾기"""
    dict_name = f"{source_lang}-{target_lang}.md"
    dict_path = os.path.join(base_dir, "dictionaries", dict_name)

    if os.path.exists(dict_path):
        return UserDictionary(dict_path)

    return None
