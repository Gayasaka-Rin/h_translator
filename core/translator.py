"""
번역 엔진 모듈
LLM API를 사용하여 텍스트 번역 수행
"""
import json
import time
from typing import Optional, Callable
from google import genai
from google.genai import errors as genai_errors

from .dictionary import UserDictionary


# 언어 코드 → 언어 이름 매핑
LANGUAGE_NAMES = {
    "ja": "일본어",
    "ko": "한국어",
    "en": "영어",
    "zh": "중국어",
    "es": "스페인어",
    "fr": "프랑스어",
    "de": "독일어",
}


class Translator:
    """번역 엔진 클래스"""

    def __init__(self, config: dict, on_model_switch: Optional[Callable[[str, str], None]] = None):
        """
        Args:
            config: 설정 딕셔너리
            on_model_switch: 모델 전환 시 호출되는 콜백 (old_model, new_model)
        """
        self.config = config
        self.api_config = config.get("api", {})
        self.translation_config = config.get("translation", {})

        self.provider = self.api_config.get("provider", "gemini")
        self.model = self.api_config.get("model", "gemini-2.5-flash")
        self.fallback_models = self.api_config.get("fallback_models", [])
        self.api_key = self.api_config.get("api_key", "")

        self.source_lang = self.translation_config.get("source_lang", "ja")
        self.target_lang = self.translation_config.get("target_lang", "ko")

        self.dictionary: Optional[UserDictionary] = None
        self.on_model_switch = on_model_switch

        # 사용할 모델 목록 (기본 + 폴백)
        self.available_models = [self.model] + self.fallback_models
        self.current_model_index = 0

        self._init_client()

    def _init_client(self):
        """API 클라이언트 초기화"""
        if self.provider == "gemini":
            self.client = genai.Client(api_key=self.api_key)
        else:
            raise ValueError(f"지원하지 않는 API 제공자: {self.provider}")

    @property
    def current_model(self) -> str:
        """현재 사용 중인 모델"""
        return self.available_models[self.current_model_index]

    def _switch_to_next_model(self) -> bool:
        """다음 폴백 모델로 전환. 성공 시 True, 더 이상 모델 없으면 False"""
        if self.current_model_index + 1 < len(self.available_models):
            old_model = self.current_model
            self.current_model_index += 1
            new_model = self.current_model

            if self.on_model_switch:
                self.on_model_switch(old_model, new_model)

            return True
        return False

    def set_dictionary(self, dictionary: UserDictionary):
        """사용자 사전 설정"""
        self.dictionary = dictionary

    def _build_prompt(self, text: str, is_filename: bool = False) -> str:
        """번역 프롬프트 생성"""
        source_name = LANGUAGE_NAMES.get(self.source_lang, self.source_lang)
        target_name = LANGUAGE_NAMES.get(self.target_lang, self.target_lang)

        if is_filename:
            prompt = f"""다음 파일명을 {source_name}에서 {target_name}로 번역해주세요.
파일명만 번역하고, 확장자는 그대로 유지하세요.
번역 결과만 출력하세요. 다른 설명은 필요 없습니다.

파일명: {text}"""
        else:
            prompt = f"""다음 텍스트를 {source_name}에서 {target_name}로 번역해주세요.

번역 지침:
1. 자연스럽고 읽기 쉬운 {target_name}로 번역하세요.
2. 원문의 문체와 뉘앙스를 최대한 유지하세요.
3. HTML 태그가 있다면 태그 구조는 유지하고 텍스트만 번역하세요.
4. 루비 태그 <ruby>본문<rt>읽기</rt></ruby>는 "본문(읽기)" 형식의 괄호 표기로 변환하세요.
5. 번역 결과만 출력하세요. 설명이나 주석은 필요 없습니다.
"""
            # 사전 컨텍스트 추가
            if self.dictionary:
                dict_context = self.dictionary.get_context_prompt()
                if dict_context:
                    prompt += f"\n{dict_context}\n"

            prompt += f"\n---\n{text}"

        return prompt

    def translate_text(self, text: str, is_filename: bool = False) -> str:
        """텍스트 번역 (할당량 초과 시 자동 폴백)"""
        if not text.strip():
            return text

        prompt = self._build_prompt(text, is_filename)

        if self.provider == "gemini":
            while True:
                try:
                    response = self.client.models.generate_content(
                        model=self.current_model,
                        contents=prompt
                    )
                    if response.text is None:
                        raise Exception("API 응답이 비어있습니다. 다시 시도하세요.")
                    return response.text.strip()

                except genai_errors.ClientError as e:
                    error_str = str(e)
                    # 429 할당량 초과 에러
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                        if self._switch_to_next_model():
                            # 다음 모델로 재시도
                            continue
                        else:
                            # 모든 모델 소진
                            raise Exception("모든 모델의 할당량이 초과되었습니다. 잠시 후 다시 시도하세요.")
                    else:
                        raise
        else:
            raise ValueError(f"지원하지 않는 API 제공자: {self.provider}")

    def translate_chunks(
        self,
        chunks: list[str],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> list[str]:
        """
        여러 청크 번역 (진행상황 콜백 지원)

        Args:
            chunks: 번역할 텍스트 청크 목록
            progress_callback: 진행상황 콜백 함수 (current, total)
        """
        translated_chunks = []
        total = len(chunks)

        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback(i + 1, total)

            translated = self.translate_text(chunk)
            translated_chunks.append(translated)

        return translated_chunks

    def translate_filename(self, filename: str) -> str:
        """파일명 번역 (확장자 제외)"""
        # 확장자 분리
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            translated_name = self.translate_text(name, is_filename=True)
            return f"{translated_name}.{ext}"
        else:
            return self.translate_text(filename, is_filename=True)


def load_config(config_path: str) -> dict:
    """설정 파일 로드"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)
