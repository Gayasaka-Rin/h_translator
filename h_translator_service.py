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

    api_key = config.get("api", {}).get("api_key", "")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        return False, "config.json에 API 키를 설정해주세요"

    def on_model_switch(old_model: str, new_model: str):
        pass  # GUI 모드에서는 무시

    try:
        translator = Translator(config, on_model_switch=on_model_switch)
    except Exception as e:
        return False, f"번역기 초기화 실패: {e}"

    # 사전 로드
    dict_config = config.get("dictionary", {})
    if dict_config.get("enabled", False):
        dict_path = SCRIPT_DIR / dict_config.get("path", "dictionaries/ja-ko.md")
        if dict_path.exists():
            dictionary = UserDictionary(str(dict_path))
            translator.set_dictionary(dictionary)

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
        width, height = 1400, 600
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
        self.status_label = ttk.Label(main_frame, text="텍스트를 입력하고 번역 버튼을 누르세요", style='Status.TLabel')
        self.status_label.pack(anchor='w')

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
                                      relief='flat', padx=10, pady=10)
        self.original_text.grid(row=1, column=0, sticky='nsew', pady=(5, 0))

        # 중간 번역 버튼
        middle_frame = ttk.Frame(content_frame, style='Dark.TFrame')
        middle_frame.grid(row=1, column=1, padx=15)

        translate_arrow_btn = tk.Button(middle_frame, text="→", command=self.do_translate,
                                        bg='#4a9eff', fg='#ffffff', font=('맑은 고딕', 20, 'bold'),
                                        relief='flat', padx=15, pady=10, cursor='hand2')
        translate_arrow_btn.pack()

        # 번역 결과 섹션 (오른쪽)
        ttk.Label(content_frame, text="번역", style='Title.TLabel').grid(row=0, column=2, sticky='w')

        self.translated_text = tk.Text(content_frame, wrap=tk.WORD,
                                        bg='#3c3c3c', fg='#cccccc', font=('맑은 고딕', 15),
                                        relief='flat', padx=10, pady=10)
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

        # 포커스
        self.original_text.focus_set()

    def do_translate(self):
        """번역 실행"""
        global translator

        text = self.original_text.get('1.0', tk.END).strip()
        if not text:
            self.status_label.config(text="원문을 입력하세요")
            return

        if translator is None:
            self.status_label.config(text="번역기가 초기화되지 않았습니다")
            return

        self.status_label.config(text="번역 중...")
        self.root.update()

        try:
            translated = translator.translate_text(text)
        except Exception as e:
            self.status_label.config(text=f"번역 실패: {e}")
            return

        # 결과 표시
        self.translated_text.config(state='normal')
        self.translated_text.delete('1.0', tk.END)
        self.translated_text.insert('1.0', translated)
        self.translated_text.config(state='disabled')

        # 클립보드 복사
        try:
            pyperclip.copy(translated)
            self.status_label.config(text="[완료] 클립보드에 복사됨")
        except:
            self.status_label.config(text="[완료]")

        # 로그 저장
        try:
            save_translation_log(text, translated)
        except:
            pass

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

    def __init__(self, original: str, translated: str, status: str = "완료"):
        self.root = tk.Tk()
        self.root.title("H Translator")
        self.root.configure(bg='#2b2b2b')

        # 아이콘 설정
        icon_path = SCRIPT_DIR / "icon.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))

        # 창 크기 및 위치
        width, height = 1400, 600
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
        status_label = ttk.Label(main_frame, text=f"[{status}] 클립보드에 복사됨", style='Status.TLabel')
        status_label.pack(anchor='w')

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

        # 중간 화살표
        middle_frame = ttk.Frame(content_frame, style='Dark.TFrame')
        middle_frame.grid(row=1, column=1, padx=15)

        arrow_label = tk.Label(middle_frame, text="→", bg='#2b2b2b', fg='#4a9eff',
                               font=('맑은 고딕', 24, 'bold'))
        arrow_label.pack()

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

        # 결과 팝업
        popup = TranslationPopup(text, translated)
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
    # 번역기 초기화
    success, message = init_translator()
    if not success:
        show_error_popup(message)
        sys.exit(1)

    # 핫키 등록 (Ctrl+Alt+Z)
    keyboard.add_hotkey('ctrl+alt+z', on_hotkey, suppress=True)

    # 시스템 트레이 실행
    icon = create_tray_icon()
    icon.run()


if __name__ == "__main__":
    main()
