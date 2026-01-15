#!/usr/bin/env python3
"""
H Translator - 백그라운드 서비스
시스템 트레이에 상주하며 핫키로 번역 실행
"""
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from pathlib import Path

# 스크립트 디렉토리 설정
SCRIPT_DIR = Path(__file__).parent.absolute()
TRANSLATIONS_DIR = SCRIPT_DIR / "translations"
sys.path.insert(0, str(SCRIPT_DIR))

import keyboard
import pyperclip
import pyautogui
from PIL import Image
import pystray

from core.translator import Translator, load_config
from core.dictionary import UserDictionary

# 모델 선호 설정 파일
PREFERENCE_FILE = SCRIPT_DIR / "model_preference.json"
LOCK_FILE = SCRIPT_DIR / ".h_translator.lock"


def check_already_running() -> bool:
    """이미 실행 중인지 확인"""
    import psutil

    if not LOCK_FILE.exists():
        return False

    try:
        with open(LOCK_FILE, 'r') as f:
            old_pid = int(f.read().strip())

        # 해당 PID 프로세스가 존재하고 Python인지 확인
        if psutil.pid_exists(old_pid):
            proc = psutil.Process(old_pid)
            if 'python' in proc.name().lower():
                return True
    except:
        pass

    return False


def create_lock():
    """락 파일 생성"""
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))


def remove_lock():
    """락 파일 제거"""
    try:
        LOCK_FILE.unlink()
    except:
        pass


def save_model_preference(model_name: str):
    """선호 모델 저장"""
    import json
    try:
        with open(PREFERENCE_FILE, 'w', encoding='utf-8') as f:
            json.dump({"preferred_model": model_name}, f)
    except:
        pass


def load_model_preference() -> str:
    """선호 모델 로드"""
    import json
    try:
        if PREFERENCE_FILE.exists():
            with open(PREFERENCE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("preferred_model", "")
    except:
        pass
    return ""


# 전역 변수
translator = None
config = None
tray_icon = None
is_translating = False  # 중복 실행 방지


def init_translator():
    """번역기 초기화"""
    global translator, config

    config_path = SCRIPT_DIR / "config.json"
    if not config_path.exists():
        return False, "설정 파일을 찾을 수 없습니다"

    try:
        config = load_config(str(config_path))
    except Exception as e:
        return False, f"설정 파일 로드 실패: {e}"

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
        return False, "config.json에 API 키를 설정해주세요"

    def on_model_switch(old_model: str, new_model: str, reason: str):
        pass  # GUI 모드에서는 무시

    try:
        translator = Translator(config, on_model_switch=on_model_switch)
    except Exception as e:
        return False, f"번역기 초기화 실패: {e}"

    # 프롬프트/사전 로드
    prompts_config = config.get("prompts", {})

    # 사전 로드
    dict_path_str = prompts_config.get("dictionary", "")
    if dict_path_str:
        dict_path = SCRIPT_DIR / dict_path_str
        if dict_path.exists():
            dictionary = UserDictionary(str(dict_path))
            translator.set_dictionary(dictionary)

    # 시스템 프롬프트 로드
    system_path_str = prompts_config.get("system", "")
    if system_path_str:
        system_path = SCRIPT_DIR / system_path_str
        if system_path.exists():
            translator.load_system_prompt(str(system_path))

    return True, "OK"


def save_translation_log(original: str, translated: str):
    """번역 로그 저장"""
    TRANSLATIONS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = TRANSLATIONS_DIR / f"{timestamp}.txt"

    content = f"""[원문]
{original}

[번역]
{translated}

[시간] {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write(content)
    return log_file


class ManualTranslationWindow:
    """수동 번역 창"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("H Translator")
        self.root.configure(bg='#2b2b2b')

        # 아이콘 설정
        icon_path = SCRIPT_DIR / "icon.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))

        # 창 크기 및 위치
        width, height = 1400, 650
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(600, 300)

        # 스타일 설정
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Dark.TFrame', background='#2b2b2b')
        style.configure('Dark.TLabel', background='#2b2b2b', foreground='#ffffff', font=('맑은 고딕', 15))
        style.configure('Title.TLabel', background='#2b2b2b', foreground='#4a9eff', font=('맑은 고딕', 16, 'bold'))
        style.configure('Status.TLabel', background='#2b2b2b', foreground='#888888', font=('맑은 고딕', 13))
        style.configure('Model.TCombobox', font=('맑은 고딕', 12))

        # 메인 프레임
        main_frame = ttk.Frame(self.root, style='Dark.TFrame', padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 상단 1줄: 타겟 언어 + 모델 선택
        top_row1 = ttk.Frame(main_frame, style='Dark.TFrame')
        top_row1.pack(fill=tk.X)

        # 타겟 언어 선택 (왼쪽)
        target_frame = ttk.Frame(top_row1, style='Dark.TFrame')
        target_frame.pack(side=tk.LEFT)

        ttk.Label(target_frame, text="타겟:", style='Status.TLabel').pack(side=tk.LEFT, padx=(0, 5))

        self.target_lang_var = tk.StringVar(value='ko')
        for lang_code, lang_name in [('ko', '한국어'), ('ja', '일본어'), ('en', '영어')]:
            rb = tk.Radiobutton(target_frame, text=lang_name, variable=self.target_lang_var,
                               value=lang_code, bg='#2b2b2b', fg='#ffffff',
                               selectcolor='#3c3c3c', activebackground='#2b2b2b',
                               activeforeground='#ffffff', font=('맑은 고딕', 10))
            rb.pack(side=tk.LEFT, padx=2)

        # 모델 선택 (오른쪽)
        model_frame = ttk.Frame(top_row1, style='Dark.TFrame')
        model_frame.pack(side=tk.RIGHT)

        ttk.Label(model_frame, text="모델:", style='Status.TLabel').pack(side=tk.LEFT, padx=(0, 5))

        self.model_var = tk.StringVar()
        self.model_list = self._get_model_list()
        self.model_combo = ttk.Combobox(model_frame, textvariable=self.model_var,
                                         values=self.model_list, state='readonly',
                                         width=25, font=('맑은 고딕', 10))
        self.model_combo.pack(side=tk.LEFT, padx=(0, 5))

        # 저장된 선호 모델 로드
        preferred = load_model_preference()
        default_idx = 0
        if preferred and preferred in self.model_list:
            default_idx = self.model_list.index(preferred)
        if self.model_list:
            self.model_combo.current(default_idx)
            if translator and default_idx < len(translator.providers):
                translator.current_provider_index = default_idx

        self.model_btn = tk.Button(model_frame, text="설정", command=self._on_model_confirm,
                                   bg='#4a9eff', fg='#ffffff', font=('맑은 고딕', 10),
                                   relief='flat', padx=8, cursor='hand2')
        self.model_btn.pack(side=tk.LEFT)

        # 상단 2줄: 번역 결과 상태
        top_row2 = ttk.Frame(main_frame, style='Dark.TFrame')
        top_row2.pack(fill=tk.X, pady=(5, 0))

        self.status_label = ttk.Label(top_row2, text="텍스트를 입력하고 번역 버튼을 누르세요", style='Status.TLabel')
        self.status_label.pack(side=tk.LEFT)

        # 좌우 컨테이너
        content_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        content_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=0)  # 중간 버튼
        content_frame.columnconfigure(2, weight=1)
        content_frame.rowconfigure(1, weight=1)

        # 원문 섹션 (왼쪽)
        ttk.Label(content_frame, text="원문", style='Title.TLabel').grid(row=0, column=0, sticky='w')

        self.original_text = tk.Text(content_frame, wrap=tk.WORD,
                                      bg='#3c3c3c', fg='#ffffff', font=('맑은 고딕', 15),
                                      relief='flat', padx=10, pady=10,
                                      insertbackground='#ffffff')  # 커서 색상
        self.original_text.grid(row=1, column=0, sticky='nsew', pady=(5, 0))

        # 중간 버튼 프레임
        middle_frame = ttk.Frame(content_frame, style='Dark.TFrame')
        middle_frame.grid(row=1, column=1, padx=15)

        self.translate_arrow_btn = tk.Button(middle_frame, text="→", command=self.do_translate,
                                        bg='#4a9eff', fg='#ffffff', font=('맑은 고딕', 20, 'bold'),
                                        relief='flat', padx=15, pady=10, cursor='hand2')
        self.translate_arrow_btn.pack()

        # 리셋 버튼
        reset_btn = tk.Button(middle_frame, text="리셋", command=self.do_reset,
                              bg='#4a4a4a', fg='#ffffff', font=('맑은 고딕', 10),
                              relief='flat', padx=10, pady=5, cursor='hand2')
        reset_btn.pack(pady=(10, 0))

        # 번역 상태 추적 (재번역 지원)
        self.has_translation = False

        # 번역 결과 섹션 (오른쪽)
        ttk.Label(content_frame, text="번역", style='Title.TLabel').grid(row=0, column=2, sticky='w')

        self.translated_text = tk.Text(content_frame, wrap=tk.WORD,
                                        bg='#3c3c3c', fg='#cccccc', font=('맑은 고딕', 15),
                                        relief='flat', padx=10, pady=10,
                                        insertbackground='#ffffff')  # 커서 색상
        self.translated_text.config(state='disabled')
        self.translated_text.grid(row=1, column=2, sticky='nsew', pady=(5, 0))

        # 버튼 프레임
        btn_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        btn_frame.pack(fill=tk.X, pady=(15, 0))

        close_btn = tk.Button(btn_frame, text="닫기 (Esc)", command=self.close,
                              bg='#4a4a4a', fg='#ffffff', font=('맑은 고딕', 15),
                              relief='flat', padx=20, pady=10, cursor='hand2')
        close_btn.pack(side=tk.RIGHT)

        copy_btn = tk.Button(btn_frame, text="복사", command=self.copy_result,
                             bg='#4a4a4a', fg='#ffffff', font=('맑은 고딕', 15),
                             relief='flat', padx=20, pady=10, cursor='hand2')
        copy_btn.pack(side=tk.RIGHT, padx=(0, 10))

        # 단축키
        self.root.bind('<Escape>', lambda e: self.close())
        self.root.bind('<Control-Return>', lambda e: self.do_translate())

        # 원문 변경 시 재번역 상태 리셋
        self.original_text.bind('<Key>', self._on_original_text_change)
        self.original_text.bind('<<Paste>>', self._on_original_text_change)

        # 포커스
        self.original_text.focus_set()

    def _on_original_text_change(self, event=None):
        """원문 텍스트 변경 시 재번역 상태 리셋"""
        if self.has_translation:
            self.has_translation = False
            self.translate_arrow_btn.config(text="→")

    def do_reset(self):
        """양쪽 텍스트 영역 초기화"""
        # 원문 초기화
        self.original_text.delete('1.0', tk.END)
        # 번역문 초기화
        self.translated_text.config(state='normal')
        self.translated_text.delete('1.0', tk.END)
        self.translated_text.config(state='disabled')
        # 상태 리셋
        self.has_translation = False
        self.translate_arrow_btn.config(text="→")
        self.target_lang_var.set('ko')  # 타겟 언어 기본값
        self.status_label.config(text="텍스트를 입력하고 번역 버튼을 누르세요")
        # 포커스
        self.original_text.focus_set()

    def _get_model_list(self) -> list:
        """사용 가능한 모델 목록 가져오기"""
        global translator
        if translator is None:
            return []
        return [f"{p['name']}:{p['model']}" for p in translator.providers]

    def _on_model_change(self, event=None):
        """모델 변경 시 호출 (수동 번역에 즉시 적용)"""
        global translator
        if translator is None:
            return

        selected_idx = self.model_combo.current()
        if selected_idx >= 0 and selected_idx < len(translator.providers):
            translator.current_provider_index = selected_idx

    def _on_model_confirm(self):
        """파일 번역용 모델 설정 저장"""
        global translator
        if translator is None:
            return

        selected_idx = self.model_combo.current()
        if selected_idx >= 0 and selected_idx < len(translator.providers):
            translator.current_provider_index = selected_idx
            model_name = translator.current_model
            save_model_preference(model_name)
            self.status_label.config(text=f"번역 모델 설정됨: {model_name}")

    def do_translate(self):
        """번역 실행 (재번역 지원)"""
        global translator

        # 재번역 모드: 번역문을 원문으로 이동
        if self.has_translation:
            translated_text = self.translated_text.get('1.0', tk.END).strip()
            if translated_text:
                # 번역문을 원문으로 이동
                self.original_text.delete('1.0', tk.END)
                self.original_text.insert('1.0', translated_text)
                # 번역문 영역 초기화
                self.translated_text.config(state='normal')
                self.translated_text.delete('1.0', tk.END)
                self.translated_text.config(state='disabled')
                # 상태 리셋
                self.has_translation = False
                self.translate_arrow_btn.config(text="→")

        text = self.original_text.get('1.0', tk.END).strip()
        if not text:
            self.status_label.config(text="원문을 입력하세요")
            return

        if translator is None:
            self.status_label.config(text="번역기가 초기화되지 않았습니다")
            return

        # 원문 언어 감지
        from core.file_handler import detect_source_language
        source = detect_source_language(text)
        if source == 'unknown':
            source = 'en'  # unknown이면 영어로 가정

        # 원문 언어에 따라 타겟 자동 전환
        # 한국어 원문 → 타겟 일본어 / 외국어 원문 → 타겟 한국어
        if source == 'ko':
            target = 'ja'
            self.target_lang_var.set('ja')
        elif source in ('ja', 'en'):
            target = 'ko'
            self.target_lang_var.set('ko')
        else:
            target = self.target_lang_var.get()

        translator.set_translation_direction(source, target)

        lang_names = {"ja": "일본어", "ko": "한국어", "en": "영어"}
        source_name = lang_names.get(source, source)
        target_name = lang_names.get(target, target)

        self.status_label.config(text=f"번역 중... ({source_name} → {target_name})")
        self.root.update()

        # 번역 시간 측정
        import time as time_module
        start_time = time_module.time()

        try:
            translated = translator.translate_text(text)
        except Exception as e:
            self.status_label.config(text=f"번역 실패: {e}")
            return

        elapsed_time = time_module.time() - start_time

        # 결과 표시
        self.translated_text.config(state='normal')
        self.translated_text.delete('1.0', tk.END)
        self.translated_text.insert('1.0', translated)
        self.translated_text.config(state='disabled')

        # 상세 결과 메시지 구성
        # 번역쌍, 글자수, 토큰수, 번역시간, 사용 모델
        char_count = len(text)
        token_count = translator.last_usage.get('total_tokens', 0) if translator.last_usage else 0
        model_name = translator.current_model.split(':')[-1]  # 모델명만

        status_parts = [
            f"{source_name}→{target_name}",
            f"{char_count}자",
            f"{token_count}토큰",
            f"{elapsed_time:.1f}초",
            model_name
        ]
        status_msg = " | ".join(status_parts)

        # 클립보드 복사
        try:
            pyperclip.copy(translated)
            self.status_label.config(text=f"[완료] {status_msg} (복사됨)")
        except:
            self.status_label.config(text=f"[완료] {status_msg}")

        # 로그 저장
        try:
            save_translation_log(text, translated)
        except:
            pass

        # 번역 완료 후 버튼을 ↔로 변경 (재번역 가능)
        self.has_translation = True
        self.translate_arrow_btn.config(text="↔")

    def copy_result(self):
        """결과 복사"""
        text = self.translated_text.get('1.0', tk.END).strip()
        if text:
            pyperclip.copy(text)
            self.status_label.config(text="클립보드에 복사됨")

    def close(self):
        self.root.destroy()

    def show(self):
        self.root.mainloop()


class TranslationPopup:
    """번역 결과 팝업 창"""

    def __init__(self, original: str, translated: str, status: str = "완료", model: str = "", tokens: int = 0):
        self.root = tk.Tk()
        self.root.title("H Translator")
        self.root.configure(bg='#2b2b2b')

        # 아이콘 설정
        icon_path = SCRIPT_DIR / "icon.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))

        # 창 크기 및 위치
        width, height = 1400, 650
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(600, 300)

        # 스타일 설정
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Dark.TFrame', background='#2b2b2b')
        style.configure('Dark.TLabel', background='#2b2b2b', foreground='#ffffff', font=('맑은 고딕', 15))
        style.configure('Title.TLabel', background='#2b2b2b', foreground='#4a9eff', font=('맑은 고딕', 16, 'bold'))
        style.configure('Status.TLabel', background='#2b2b2b', foreground='#888888', font=('맑은 고딕', 13))

        # 메인 프레임
        main_frame = ttk.Frame(self.root, style='Dark.TFrame', padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 상태 표시
        status_text = f"[{status}]"
        if model:
            status_text += f" {model}"
        if tokens > 0:
            status_text += f", {tokens}토큰"
        status_text += " - 클립보드에 복사됨"
        self.status_label = ttk.Label(main_frame, text=status_text, style='Status.TLabel')
        self.status_label.pack(anchor='w')

        # 좌우 컨테이너
        content_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        content_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=0)  # 중간
        content_frame.columnconfigure(2, weight=1)
        content_frame.rowconfigure(1, weight=1)

        # 원문 섹션 (왼쪽)
        ttk.Label(content_frame, text="원문", style='Title.TLabel').grid(row=0, column=0, sticky='w')

        self.original_text = tk.Text(content_frame, wrap=tk.WORD,
                                      bg='#3c3c3c', fg='#cccccc', font=('맑은 고딕', 15),
                                      relief='flat', padx=10, pady=10)
        self.original_text.insert('1.0', original)
        self.original_text.config(state='disabled')
        self.original_text.grid(row=1, column=0, sticky='nsew', pady=(5, 0))

        # 중간 재번역 버튼
        middle_frame = ttk.Frame(content_frame, style='Dark.TFrame')
        middle_frame.grid(row=1, column=1, padx=15)

        self.arrow_btn = tk.Button(middle_frame, text="↔", command=self.do_retranslate,
                                   bg='#4a9eff', fg='#ffffff', font=('맑은 고딕', 20, 'bold'),
                                   relief='flat', padx=15, pady=10, cursor='hand2')
        self.arrow_btn.pack()

        # 번역 결과 섹션 (오른쪽)
        ttk.Label(content_frame, text="번역", style='Title.TLabel').grid(row=0, column=2, sticky='w')

        self.translated_text = tk.Text(content_frame, wrap=tk.WORD,
                                        bg='#3c3c3c', fg='#ffffff', font=('맑은 고딕', 15),
                                        relief='flat', padx=10, pady=10)
        self.translated_text.insert('1.0', translated)
        self.translated_text.config(state='disabled')
        self.translated_text.grid(row=1, column=2, sticky='nsew', pady=(5, 0))

        # 버튼 프레임
        btn_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        btn_frame.pack(fill=tk.X, pady=(15, 0))

        close_btn = tk.Button(btn_frame, text="닫기 (Esc)", command=self.close,
                              bg='#4a4a4a', fg='#ffffff', font=('맑은 고딕', 15),
                              relief='flat', padx=20, pady=10, cursor='hand2')
        close_btn.pack(side=tk.RIGHT)

        # 단축키
        self.root.bind('<Escape>', lambda e: self.close())
        self.root.bind('<Return>', lambda e: self.close())

        # 포커스
        self.root.focus_force()

    def do_retranslate(self):
        """번역문을 다시 번역 (역번역)"""
        global translator

        if translator is None:
            self.status_label.config(text="번역기가 초기화되지 않았습니다")
            return

        # 현재 번역문 가져오기
        self.translated_text.config(state='normal')
        current_translated = self.translated_text.get('1.0', tk.END).strip()
        self.translated_text.config(state='disabled')

        if not current_translated:
            return

        # 자동 언어 감지 및 방향 설정
        source, target = translator.detect_and_set_direction(current_translated)
        source_name = {"ja": "일본어", "ko": "한국어", "en": "영어"}.get(source, source)
        target_name = {"ja": "일본어", "ko": "한국어", "en": "영어"}.get(target, target)

        self.status_label.config(text=f"재번역 중... ({source_name} → {target_name})")
        self.root.update()

        try:
            new_translated = translator.translate_text(current_translated)
        except Exception as e:
            self.status_label.config(text=f"재번역 실패: {e}")
            return

        # 기존 번역문을 원문으로 이동
        self.original_text.config(state='normal')
        self.original_text.delete('1.0', tk.END)
        self.original_text.insert('1.0', current_translated)
        self.original_text.config(state='disabled')

        # 새 번역문 표시
        self.translated_text.config(state='normal')
        self.translated_text.delete('1.0', tk.END)
        self.translated_text.insert('1.0', new_translated)
        self.translated_text.config(state='disabled')

        # 클립보드 복사
        try:
            pyperclip.copy(new_translated)
        except:
            pass

        # 상태 업데이트
        model_info = translator.current_model
        token_info = ""
        if translator.last_usage:
            token_info = f", {translator.last_usage['total_tokens']}토큰"
        self.status_label.config(text=f"[재번역] {source_name}→{target_name} | {model_info}{token_info} - 클립보드에 복사됨")

    def close(self):
        self.root.destroy()

    def show(self):
        self.root.mainloop()


def show_error_popup(message: str):
    """에러 팝업"""
    root = tk.Tk()
    root.title("H Translator - 오류")
    root.attributes('-topmost', True)
    root.configure(bg='#2b2b2b')

    width, height = 350, 150
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")

    frame = tk.Frame(root, bg='#2b2b2b', padx=20, pady=20)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(frame, text="오류", bg='#2b2b2b', fg='#ff6b6b',
             font=('맑은 고딕', 12, 'bold')).pack(anchor='w')
    tk.Label(frame, text=message, bg='#2b2b2b', fg='#ffffff',
             font=('맑은 고딕', 10), wraplength=300, justify='left').pack(anchor='w', pady=(10, 20))

    close_btn = tk.Button(frame, text="닫기", command=root.destroy,
                          bg='#4a4a4a', fg='#ffffff', font=('맑은 고딕', 10),
                          relief='flat', padx=20, pady=5)
    close_btn.pack(side=tk.RIGHT)

    root.bind('<Escape>', lambda e: root.destroy())
    root.bind('<Return>', lambda e: root.destroy())
    root.focus_force()
    root.mainloop()


def do_translate():
    """번역 실행"""
    global translator, is_translating

    # 중복 실행 방지
    if is_translating:
        return
    is_translating = True

    try:
        if translator is None:
            show_error_popup("번역기가 초기화되지 않았습니다.")
            return

        # 핫키 릴리즈 대기
        time.sleep(0.3)

        # 선택된 텍스트 복사 (keyboard 라이브러리 사용)
        keyboard.send('ctrl+c')
        time.sleep(0.2)

        try:
            text = pyperclip.paste()
        except Exception as e:
            show_error_popup(f"클립보드 읽기 실패: {e}")
            return

        if not text or not text.strip():
            show_error_popup("선택된 텍스트가 없습니다.\n텍스트를 선택한 후 다시 시도하세요.")
            return

        text = text.strip()

        # 자동 언어 감지 및 방향 설정
        source, target = translator.detect_and_set_direction(text)

        # 번역 실행
        try:
            translated = translator.translate_text(text)
        except Exception as e:
            show_error_popup(f"번역 실패: {e}")
            return

        # 클립보드에 복사
        try:
            pyperclip.copy(translated)
        except:
            pass

        # 로그 저장
        try:
            save_translation_log(text, translated)
        except:
            pass

        # 모델/토큰 정보
        model_info = translator.current_model if translator else ""
        token_count = translator.last_usage.get('total_tokens', 0) if translator and translator.last_usage else 0

        # 결과 팝업
        popup = TranslationPopup(text, translated, model=model_info, tokens=token_count)
        popup.show()
    finally:
        is_translating = False


def on_hotkey():
    """핫키 콜백"""
    threading.Thread(target=do_translate, daemon=True).start()


def open_manual_window():
    """수동 번역 창 열기"""
    def run():
        window = ManualTranslationWindow()
        window.show()
    threading.Thread(target=run, daemon=True).start()


def on_quit(icon, item):
    """종료"""
    remove_lock()
    icon.stop()
    keyboard.unhook_all()
    os._exit(0)


def create_tray_icon():
    """시스템 트레이 아이콘 생성"""
    global tray_icon

    icon_path = SCRIPT_DIR / "icon.ico"
    if icon_path.exists():
        image = Image.open(icon_path)
    else:
        image = Image.new('RGB', (64, 64), color='blue')

    menu = pystray.Menu(
        pystray.MenuItem("H Translator", None, enabled=False),
        pystray.MenuItem("번역 창 열기", lambda: open_manual_window()),
        pystray.MenuItem("선택 번역 (Ctrl+Alt+Z)", lambda: on_hotkey()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("종료", on_quit)
    )

    tray_icon = pystray.Icon("H Translator", image, "H Translator", menu)
    return tray_icon


def main():
    """메인 함수"""
    # 중복 실행 확인
    if check_already_running():
        # 이미 실행 중이면 번역 창만 열기 요청 (간단히 새 창 열기)
        show_error_popup("H Translator가 이미 실행 중입니다.\n트레이 아이콘을 확인하세요.")
        sys.exit(0)

    # 락 파일 생성
    create_lock()

    # 번역기 초기화
    success, message = init_translator()
    if not success:
        show_error_popup(message)
        sys.exit(1)

    # 핫키 등록 (Ctrl+Alt+Z)
    # suppress=False: 원격 데스크톱 키 입력 충돌 방지
    keyboard.add_hotkey('ctrl+alt+z', on_hotkey, suppress=False)

    # 시스템 트레이 생성
    icon = create_tray_icon()

    # 시작 시 번역 창 열기 (별도 스레드)
    def open_initial_window():
        time.sleep(0.3)  # 트레이 초기화 대기
        window = ManualTranslationWindow()
        window.show()

    threading.Thread(target=open_initial_window, daemon=True).start()

    # 시스템 트레이 실행 (메인 스레드)
    icon.run()


if __name__ == "__main__":
    main()
