"""
파일 읽기/쓰기 및 인코딩 처리 모듈
"""
import os
import re
from pathlib import Path
from typing import Optional
import chardet


def detect_encoding(file_path: str) -> str:
    """파일 인코딩 자동 감지"""
    with open(file_path, 'rb') as f:
        raw_data = f.read()
    result = chardet.detect(raw_data)
    encoding = result['encoding']

    # 일본어 인코딩 보정
    if encoding and encoding.lower() in ['iso-8859-1', 'ascii']:
        # 일본어 파일이 잘못 감지되는 경우가 있음
        for try_encoding in ['utf-8', 'shift_jis', 'euc-jp', 'cp932']:
            try:
                raw_data.decode(try_encoding)
                return try_encoding
            except:
                continue

    return encoding or 'utf-8'


def read_file(file_path: str, encoding: Optional[str] = None) -> str:
    """파일 읽기 (인코딩 자동 감지)"""
    if encoding is None:
        encoding = detect_encoding(file_path)

    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
        return f.read()


def write_file(file_path: str, content: str, encoding: str = 'utf-8') -> None:
    """파일 쓰기 (기본 UTF-8)"""
    with open(file_path, 'w', encoding=encoding) as f:
        f.write(content)


def generate_output_path(input_path: str, suffix: str = "(k)") -> str:
    """출력 파일 경로 생성 (원본경로에 suffix 추가)"""
    path = Path(input_path)
    stem = path.stem
    ext = path.suffix
    parent = path.parent

    new_name = f"{stem}{suffix}{ext}"
    return str(parent / new_name)


def contains_japanese(text: str) -> bool:
    """텍스트에 일본어가 포함되어 있는지 확인"""
    # 히라가나, 가타카나, 일본어 한자 범위
    japanese_pattern = re.compile(
        r'[\u3040-\u309F]|'  # 히라가나
        r'[\u30A0-\u30FF]|'  # 가타카나
        r'[\u4E00-\u9FAF]'   # CJK 한자 (일본어에서도 사용)
    )
    return bool(japanese_pattern.search(text))


def contains_korean(text: str) -> bool:
    """텍스트에 한국어가 포함되어 있는지 확인"""
    korean_pattern = re.compile(
        r'[\uAC00-\uD7AF]|'  # 완성형 한글
        r'[\u1100-\u11FF]|'  # 한글 자모
        r'[\u3130-\u318F]'   # 호환용 한글 자모
    )
    return bool(korean_pattern.search(text))


def detect_source_language(text: str) -> str:
    """
    텍스트의 주 언어 감지 (일본어/한국어/영어)

    Returns:
        'ja': 일본어 (히라가나/가타카나가 있음)
        'ko': 한국어 (한글이 있음)
        'en': 영어 (알파벳만 있음)
        'unknown': 판단 불가
    """
    # 한글 고유 문자 카운트 (완성형 + 자모)
    korean_chars = len(re.findall(r'[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]', text))

    # 일본어 고유 문자 카운트 (히라가나 + 가타카나)
    # 한자는 양쪽에서 사용하므로 제외
    japanese_chars = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF]', text))

    # 영어 알파벳 카운트
    english_chars = len(re.findall(r'[a-zA-Z]', text))

    # 우선순위: 일본어 > 한국어 > 영어
    # (일본어/한국어 고유 문자가 있으면 그 언어로 판단)
    if japanese_chars > korean_chars:
        return 'ja'
    elif korean_chars > japanese_chars:
        return 'ko'
    elif japanese_chars > 0:
        return 'ja'  # 히라가나/가타카나가 있으면 일본어
    elif korean_chars > 0:
        return 'ko'
    elif english_chars > 0:
        return 'en'  # 알파벳만 있으면 영어
    else:
        return 'unknown'


def convert_ruby_to_parentheses(html_content: str, keep_reading: bool = True) -> str:
    """
    HTML 루비 태그를 괄호 형식으로 변환

    예시:
    <ruby>漢字<rt>かんじ</rt></ruby> → 漢字(かんじ)

    Args:
        html_content: HTML 텍스트
        keep_reading: True면 읽기를 유지, False면 루비 제거
    """
    if keep_reading:
        # <ruby>base<rt>reading</rt></ruby> → base(reading)
        pattern = r'<ruby>([^<]+)<rt>([^<]+)</rt></ruby>'
        replacement = r'\1(\2)'
    else:
        # 루비 제거, 본문만 유지
        pattern = r'<ruby>([^<]+)<rt>[^<]+</rt></ruby>'
        replacement = r'\1'

    return re.sub(pattern, replacement, html_content)


def split_text_into_chunks(text: str, max_chars: int = 3000) -> list[str]:
    """
    텍스트를 적절한 크기의 청크로 분할
    문단 → 문장 순서로 분할 시도
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []

    # 1. 문단 단위로 분할 시도
    paragraphs = re.split(r'\n\s*\n', text)

    current_chunk = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # 현재 청크 + 새 문단이 한도 초과
        if len(current_chunk) + len(para) + 2 > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())

            # 문단 자체가 너무 긴 경우 문장 단위로 분할
            if len(para) > max_chars:
                sentence_chunks = split_by_sentences(para, max_chars)
                chunks.extend(sentence_chunks[:-1])
                current_chunk = sentence_chunks[-1] if sentence_chunks else ""
            else:
                current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def split_by_sentences(text: str, max_chars: int) -> list[str]:
    """문장 단위로 분할"""
    # 일본어/한국어 문장 끝 패턴
    sentence_endings = re.compile(r'([。！？!?\n])')

    parts = sentence_endings.split(text)

    chunks = []
    current_chunk = ""

    i = 0
    while i < len(parts):
        part = parts[i]
        # 문장 끝 기호인 경우 이전 문장에 붙임
        if i + 1 < len(parts) and sentence_endings.match(parts[i + 1]):
            part += parts[i + 1]
            i += 1

        if len(current_chunk) + len(part) > max_chars:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = part
        else:
            current_chunk += part

        i += 1

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text]


def get_file_extension(file_path: str) -> str:
    """파일 확장자 반환 (소문자)"""
    return Path(file_path).suffix.lower()


def is_supported_file(file_path: str) -> bool:
    """지원하는 파일 형식인지 확인"""
    supported_extensions = {
        '.txt', '.md', '.html', '.htm',
        '.xml', '.json', '.csv',
        '.srt', '.vtt', '.ass',  # 자막 파일
        '.tex', '.rst',  # 문서 포맷
    }
    return get_file_extension(file_path) in supported_extensions
