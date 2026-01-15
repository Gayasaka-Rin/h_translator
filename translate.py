#!/usr/bin/env python3
"""
H Translator - 메인 실행 스크립트
탐색기 컨텍스트 메뉴에서 호출되어 파일 번역 수행
"""
import os
import sys
import io

# 콘솔 인코딩 설정 (Windows cp949 문제 해결)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 헤더 먼저 출력 (빠른 반응)
print("=" * 50)
print("  H Translator - 로컬 파일 번역기")
print("=" * 50)
print()
print("[초기화] 라이브러리 로딩 중...")
sys.stdout.flush()

# 무거운 라이브러리 import
import json
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from core.translator import Translator, load_config
from core.dictionary import UserDictionary
from core.file_handler import (
    read_file,
    write_file,
    generate_output_path,
    contains_japanese,
    convert_ruby_to_parentheses,
    split_text_into_chunks,
    is_supported_file,
    detect_source_language,
)


def translate_file(file_path: str, translator: Translator, config: dict) -> bool:
    """
    단일 파일 번역

    Returns:
        성공 여부
    """
    file_path = os.path.abspath(file_path)
    filename = os.path.basename(file_path)

    print(f"\n[파일] {filename}")
    print("-" * 40)

    # 1. 지원 파일 확인
    if not is_supported_file(file_path):
        print(f"  (!) 지원하지 않는 파일 형식입니다.")
        return False

    try:
        # 2. 파일 읽기
        print("  * 파일 읽는 중...")
        content = read_file(file_path)
        print(f"  - 파일 크기: {len(content):,} 글자")

        # 3. 언어 감지 (컨텍스트 메뉴는 외국어→한국어만 지원)
        sample_text = content[:2000]  # 처음 2000자로 판단
        detected_lang = detect_source_language(sample_text)
        lang_names = {"ja": "일본어", "ko": "한국어", "en": "영어", "unknown": "알 수 없음"}
        print(f"  - 감지된 언어: {lang_names.get(detected_lang, detected_lang)}")

        if detected_lang == "ko":
            print("  (!) 한국어 파일입니다. 컨텍스트 메뉴 번역은 외국어→한국어만 지원합니다.")
            print("      한→일 번역은 H Translator 서비스 UI를 사용하세요.")
            return False

        # 번역 방향 설정 (외국어→한국어 고정)
        translator.set_translation_direction(detected_lang if detected_lang != "unknown" else "ja", "ko")

        # 4. 루비 태그 처리
        ruby_config = config.get("ruby", {})
        if ruby_config.get("convert_to_parentheses", True):
            content = convert_ruby_to_parentheses(
                content,
                keep_reading=not ruby_config.get("keep_original_reading", False)
            )

        # 4. 청크 분할
        chunking_config = config.get("chunking", {})
        max_chars = chunking_config.get("max_chars", 3000)
        chunks = split_text_into_chunks(content, max_chars)
        print(f"  - 청크 수: {len(chunks)}개")

        # 5. 번역 실행
        print("  * 번역 중...")
        translated_chunks = []
        total_start = time.time()
        for i, chunk in enumerate(chunks):
            chunk_start = time.time()
            translated = translator.translate_text(chunk)
            chunk_time = time.time() - chunk_start
            translated_chunks.append(translated)
            # 토큰 정보 포함
            token_info = ""
            if translator.last_usage:
                token_info = f", {translator.last_usage['total_tokens']}토큰"
            print(f"  - 청크 {i+1}/{len(chunks)} 완료 ({chunk_time:.1f}초, {len(chunk)}자{token_info})")
        total_time = time.time() - total_start
        print(f"  - 총 번역 시간: {total_time:.1f}초")
        # 총 토큰 사용량 출력
        if translator.total_input_tokens > 0:
            print(f"  - 총 토큰: {translator.total_input_tokens + translator.total_output_tokens} (입력: {translator.total_input_tokens}, 출력: {translator.total_output_tokens})")

        translated_content = "\n\n".join(translated_chunks)

        # 6. 출력 파일명 결정
        trans_config = config.get("translation", {})
        suffix = trans_config.get("suffix", "(k)")
        translate_filename_enabled = trans_config.get("translate_filename", False)

        # 파일명 번역 (옵션)
        if translate_filename_enabled and contains_japanese(filename):
            print("  * 파일명 번역 중...")
            translated_filename = translator.translate_filename(filename)
            output_dir = os.path.dirname(file_path)
            stem, ext = os.path.splitext(translated_filename)
            output_path = os.path.join(output_dir, f"{stem}{suffix}{ext}")
        else:
            output_path = generate_output_path(file_path, suffix)

        # 7. 파일 저장
        write_file(output_path, translated_content)
        output_filename = os.path.basename(output_path)
        print(f"  => 저장 완료: {output_filename}")

        return True

    except Exception as e:
        print(f"  (X) 오류 발생: {e}")
        return False


def main():
    """메인 함수"""
    # 명령줄 인자 확인
    if len(sys.argv) < 2:
        print("사용법: python translate.py <파일경로> [파일경로2] ...")
        print("\n탐색기에서 파일 선택 후 우클릭 메뉴로 실행하세요.")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    file_paths = sys.argv[1:]

    # 설정 파일 로드
    config_path = SCRIPT_DIR / "config.json"
    if not config_path.exists():
        print(f"(X) 설정 파일을 찾을 수 없습니다: {config_path}")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    print(f"[설정] {config_path}")

    try:
        config = load_config(str(config_path))
    except Exception as e:
        print(f"(X) 설정 파일 로드 실패: {e}")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    # API 키 확인 (providers 배열 형식 지원)
    api_config = config.get("api", {})
    has_valid_key = False
    if "providers" in api_config:
        for p in api_config["providers"]:
            key = p.get("api_key", "")
            if key and key not in ("YOUR_API_KEY_HERE", "YOUR_OPENAI_API_KEY", "YOUR_ANTHROPIC_API_KEY"):
                has_valid_key = True
                break
    else:
        key = api_config.get("api_key", "")
        has_valid_key = key and key != "YOUR_API_KEY_HERE"

    if not has_valid_key:
        print("(X) config.json에 API 키를 설정해주세요.")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    # 모델 전환 콜백
    def on_model_switch(old_model: str, new_model: str, reason: str):
        print(f"\n  (!) {reason}: {old_model} -> {new_model} 전환")

    # 번역기 초기화
    print("[초기화] 번역기 준비 중...")
    try:
        translator = Translator(config, on_model_switch=on_model_switch)

        # 저장된 선호 모델 적용
        preference_file = SCRIPT_DIR / "model_preference.json"
        if preference_file.exists():
            try:
                with open(preference_file, 'r', encoding='utf-8') as f:
                    pref = json.load(f)
                    preferred_model = pref.get("preferred_model", "")
                    if preferred_model:
                        for i, p in enumerate(translator.providers):
                            if f"{p['name']}:{p['model']}" == preferred_model:
                                translator.current_provider_index = i
                                break
            except:
                pass

        print(f"[모델] {translator.current_model}")
    except Exception as e:
        print(f"(X) 번역기 초기화 실패: {e}")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    # 프롬프트/사전 로드
    prompts_config = config.get("prompts", {})

    # 사전 로드
    dict_path_str = prompts_config.get("dictionary", "")
    if dict_path_str:
        dict_path = SCRIPT_DIR / dict_path_str
        if dict_path.exists():
            dictionary = UserDictionary(str(dict_path))
            translator.set_dictionary(dictionary)
            print(f"[사전] {len(dictionary)}개 항목 로드")

    # 시스템 프롬프트 로드
    system_path_str = prompts_config.get("system", "")
    if system_path_str:
        system_path = SCRIPT_DIR / system_path_str
        if system_path.exists():
            translator.load_system_prompt(str(system_path))
            print(f"[프롬프트] {system_path.name}")

    # 번역 설정 표시 (컨텍스트 메뉴는 자동감지→한국어 고정)
    print("[번역] 자동 감지 -> 한국어 (컨텍스트 메뉴 모드)")
    print(f"[대상] {len(file_paths)}개 파일")

    # 파일 번역 실행
    success_count = 0
    fail_count = 0

    for i, file_path in enumerate(file_paths):
        print(f"\n({i + 1}/{len(file_paths)})", end="")

        if os.path.isfile(file_path):
            if translate_file(file_path, translator, config):
                success_count += 1
            else:
                fail_count += 1
        else:
            print(f"\n(!) 파일을 찾을 수 없습니다: {file_path}")
            fail_count += 1

    # 결과 요약
    print("\n" + "=" * 50)
    print("[완료]")
    print(f"  - 성공: {success_count}개")
    if fail_count > 0:
        print(f"  - 실패: {fail_count}개")
    print("=" * 50)

    input("\n엔터를 눌러 종료...")


if __name__ == "__main__":
    main()
