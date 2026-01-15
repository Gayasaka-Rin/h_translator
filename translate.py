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

        # 3. 루비 태그 처리
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
            print(f"  - 청크 {i+1}/{len(chunks)} 완료 ({chunk_time:.1f}초, {len(chunk)}자)")
        total_time = time.time() - total_start
        print(f"  - 총 번역 시간: {total_time:.1f}초")

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

    # API 키 확인
    api_key = config.get("api", {}).get("api_key", "")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        print("(X) config.json에 API 키를 설정해주세요.")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    # 모델 전환 콜백
    def on_model_switch(old_model: str, new_model: str):
        print(f"\n  (!) 할당량 초과: {old_model} -> {new_model} 전환")

    # 번역기 초기화
    print("[초기화] 번역기 준비 중...")
    try:
        translator = Translator(config, on_model_switch=on_model_switch)
        print(f"[모델] {translator.current_model}")
    except Exception as e:
        print(f"(X) 번역기 초기화 실패: {e}")
        input("\n엔터를 눌러 종료...")
        sys.exit(1)

    # 사전 로드
    dict_config = config.get("dictionary", {})
    if dict_config.get("enabled", False):
        dict_path = SCRIPT_DIR / dict_config.get("path", "dictionaries/ja-ko.md")
        if dict_path.exists():
            dictionary = UserDictionary(str(dict_path))
            translator.set_dictionary(dictionary)
            print(f"[사전] {len(dictionary)}개 항목 로드")
        else:
            print(f"(!) 사전 파일 없음: {dict_path}")

    # 번역 설정 표시
    trans_config = config.get("translation", {})
    source = trans_config.get("source_lang", "ja")
    target = trans_config.get("target_lang", "ko")
    print(f"[번역] {source} -> {target}")
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
