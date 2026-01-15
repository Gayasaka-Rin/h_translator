"""
번역 엔진 모듈
LLM API를 사용하여 텍스트 번역 수행
"""
import json
import time
from typing import Optional, Callable
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
import anthropic

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
    """번역 엔진 클래스 - 다중 API 지원"""

    def __init__(self, config: dict, on_model_switch: Optional[Callable[[str, str, str], None]] = None):
        """
        Args:
            config: 설정 딕셔너리
            on_model_switch: 모델/프로바이더 전환 시 호출되는 콜백 (old, new, reason)
        """
        self.config = config
        self.api_config = config.get("api", {})
        self.translation_config = config.get("translation", {})

        self.source_lang = self.translation_config.get("source_lang", "ja")
        self.target_lang = self.translation_config.get("target_lang", "ko")

        self.dictionary: Optional[UserDictionary] = None
        self.on_model_switch = on_model_switch

        # 프로바이더 목록 구성
        self.providers = self._build_provider_list()
        self.current_provider_index = 0
        self.current_model_index = 0

        # 토큰 사용량 추적
        self.last_usage = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0

        # 클라이언트 초기화
        self._clients = {}
        self._init_clients()

    def _build_provider_list(self) -> list:
        """프로바이더 목록 구성"""
        providers = []

        # 새 형식 (providers 배열)
        if "providers" in self.api_config:
            for p in self.api_config["providers"]:
                api_key = p.get("api_key", "")
                if api_key and api_key != "YOUR_OPENAI_API_KEY" and api_key != "YOUR_API_KEY_HERE":
                    models = [p.get("model")] + p.get("fallback_models", [])
                    for model in models:
                        if model:
                            providers.append({
                                "name": p.get("name"),
                                "model": model,
                                "api_key": api_key
                            })
        # 구 형식 (단일 provider)
        else:
            api_key = self.api_config.get("api_key", "")
            if api_key and api_key != "YOUR_API_KEY_HERE":
                models = [self.api_config.get("model")] + self.api_config.get("fallback_models", [])
                for model in models:
                    if model:
                        providers.append({
                            "name": self.api_config.get("provider", "gemini"),
                            "model": model,
                            "api_key": api_key
                        })

        return providers

    def _init_clients(self):
        """API 클라이언트들 초기화"""
        initialized = set()
        for p in self.providers:
            key = (p["name"], p["api_key"])
            if key not in initialized:
                if p["name"] == "gemini":
                    self._clients[key] = genai.Client(api_key=p["api_key"])
                elif p["name"] == "openai":
                    try:
                        import openai
                        self._clients[key] = openai.OpenAI(api_key=p["api_key"])
                    except ImportError:
                        pass
                elif p["name"] == "anthropic":
                    self._clients[key] = anthropic.Anthropic(api_key=p["api_key"])
                initialized.add(key)

    @property
    def current_provider(self) -> dict:
        """현재 프로바이더 정보"""
        if self.current_provider_index < len(self.providers):
            return self.providers[self.current_provider_index]
        return self.providers[-1] if self.providers else {}

    @property
    def current_model(self) -> str:
        """현재 사용 중인 모델"""
        p = self.current_provider
        return f"{p.get('name', '?')}:{p.get('model', '?')}"

    def _switch_to_next(self, reason: str = "할당량 초과") -> bool:
        """다음 모델/프로바이더로 전환"""
        if self.current_provider_index + 1 < len(self.providers):
            old = self.current_model
            self.current_provider_index += 1
            new = self.current_model

            if self.on_model_switch:
                self.on_model_switch(old, new, reason)

            return True
        return False

    def _switch_to_next_provider(self, reason: str = "콘텐츠 차단") -> bool:
        """같은 프로바이더 건너뛰고 다음 프로바이더로 전환"""
        current_name = self.current_provider.get("name")

        # 현재 프로바이더와 다른 첫 번째 프로바이더 찾기
        for i in range(self.current_provider_index + 1, len(self.providers)):
            if self.providers[i].get("name") != current_name:
                old = self.current_model
                self.current_provider_index = i
                new = self.current_model

                if self.on_model_switch:
                    self.on_model_switch(old, new, reason)

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
            if self.dictionary:
                dict_context = self.dictionary.get_context_prompt()
                if dict_context:
                    prompt += f"\n{dict_context}\n"

            prompt += f"\n---\n{text}"

        return prompt

    def _call_gemini(self, prompt: str, provider: dict) -> Optional[str]:
        """Gemini API 호출"""
        key = (provider["name"], provider["api_key"])
        client = self._clients.get(key)
        if not client:
            return None

        safety_settings = [
            genai_types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            genai_types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            genai_types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            genai_types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
        ]

        response = client.models.generate_content(
            model=provider["model"],
            contents=prompt,
            config=genai_types.GenerateContentConfig(safety_settings=safety_settings)
        )

        if response.text is None:
            block_reason = ""
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                pf = response.prompt_feedback
                if hasattr(pf, 'block_reason') and pf.block_reason:
                    block_reason = str(pf.block_reason)
            raise Exception(f"Gemini 차단: {block_reason or 'UNKNOWN'}")

        # 토큰 사용량
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self.last_usage = {
                'input_tokens': response.usage_metadata.prompt_token_count,
                'output_tokens': response.usage_metadata.candidates_token_count,
                'total_tokens': response.usage_metadata.total_token_count
            }
            self.total_input_tokens += self.last_usage['input_tokens']
            self.total_output_tokens += self.last_usage['output_tokens']

        return response.text.strip()

    def _call_openai(self, prompt: str, provider: dict) -> Optional[str]:
        """OpenAI API 호출"""
        key = (provider["name"], provider["api_key"])
        client = self._clients.get(key)
        if not client:
            raise Exception("OpenAI 클라이언트가 초기화되지 않았습니다. openai 패키지를 설치하세요.")

        response = client.chat.completions.create(
            model=provider["model"],
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.choices[0].message.content

        # 토큰 사용량
        if hasattr(response, 'usage') and response.usage:
            self.last_usage = {
                'input_tokens': response.usage.prompt_tokens,
                'output_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            }
            self.total_input_tokens += self.last_usage['input_tokens']
            self.total_output_tokens += self.last_usage['output_tokens']

        return result.strip() if result else None

    def _call_anthropic(self, prompt: str, provider: dict) -> Optional[str]:
        """Anthropic Claude API 호출"""
        key = (provider["name"], provider["api_key"])
        client = self._clients.get(key)
        if not client:
            raise Exception("Anthropic 클라이언트가 초기화되지 않았습니다.")

        response = client.messages.create(
            model=provider["model"],
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text

        # 토큰 사용량
        if hasattr(response, 'usage') and response.usage:
            self.last_usage = {
                'input_tokens': response.usage.input_tokens,
                'output_tokens': response.usage.output_tokens,
                'total_tokens': response.usage.input_tokens + response.usage.output_tokens
            }
            self.total_input_tokens += self.last_usage['input_tokens']
            self.total_output_tokens += self.last_usage['output_tokens']

        return result.strip() if result else None

    def translate_text(self, text: str, is_filename: bool = False) -> str:
        """텍스트 번역 - 실패 시 다음 프로바이더로 폴백"""
        if not text.strip():
            return text

        prompt = self._build_prompt(text, is_filename)
        last_error = None

        while True:
            provider = self.current_provider
            if not provider:
                raise Exception("사용 가능한 API가 없습니다.")

            try:
                if provider["name"] == "gemini":
                    result = self._call_gemini(prompt, provider)
                elif provider["name"] == "openai":
                    result = self._call_openai(prompt, provider)
                elif provider["name"] == "anthropic":
                    result = self._call_anthropic(prompt, provider)
                else:
                    raise Exception(f"지원하지 않는 API: {provider['name']}")

                if result:
                    return result
                raise Exception("빈 응답")

            except Exception as e:
                last_error = e
                error_str = str(e)

                # 콘텐츠 차단 에러 (같은 프로바이더 건너뛰기)
                is_content_block = any(keyword in error_str for keyword in [
                    "PROHIBITED", "차단", "content_policy", "content_filter"
                ])

                if is_content_block:
                    if self._switch_to_next_provider("콘텐츠 차단"):
                        continue
                    else:
                        raise Exception(f"번역 실패 (모든 API 차단): {last_error}")

                # 할당량/속도 제한 에러 (다음 모델로)
                is_rate_limit = any(keyword in error_str for keyword in [
                    "429", "RESOURCE_EXHAUSTED", "rate_limit", "quota"
                ])

                if is_rate_limit:
                    if self._switch_to_next("할당량 초과"):
                        continue
                    else:
                        raise Exception(f"번역 실패 (할당량 소진): {last_error}")

                # 기타 에러 (다음 모델로 시도)
                if self._switch_to_next("오류"):
                    continue
                else:
                    raise Exception(f"번역 실패: {last_error}")

    def translate_chunks(
        self,
        chunks: list[str],
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> list[str]:
        """여러 청크 번역"""
        translated_chunks = []
        total = len(chunks)

        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback(i + 1, total)

            translated = self.translate_text(chunk)
            translated_chunks.append(translated)

        return translated_chunks

    def translate_filename(self, filename: str) -> str:
        """파일명 번역"""
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
