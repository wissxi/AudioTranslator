#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Современный GUI для распознавания речи из MP3 файлов и перевода на русский язык.
Использует CustomTkinter для красивого интерфейса.
"""

import os
import sys
import threading
from pathlib import Path
from typing import List, Optional
import customtkinter as ctk
from tkinter import filedialog, messagebox
import whisper
from googletrans import Translator
import subprocess

# Настройка темы CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class FFmpegManager:
    """Управление поиском и настройкой ffmpeg."""
    
    @staticmethod
    def find_ffmpeg() -> Optional[str]:
        """Ищет ffmpeg в системе."""
        # Проверяем в PATH
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return "ffmpeg"
        except:
            pass
        
        # Стандартные пути
        common_paths = [
            r"D:\ffmpeg\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        ]
        
        # Переменная окружения
        if "FFMPEG_PATH" in os.environ:
            path = os.environ["FFMPEG_PATH"]
            if os.path.exists(path):
                return path
        
        # Проверяем стандартные пути
        for path in common_paths:
            if os.path.exists(path):
                bin_dir = os.path.dirname(path)
                current_path = os.environ.get("PATH", "")
                if bin_dir not in current_path:
                    os.environ["PATH"] = bin_dir + os.pathsep + current_path
                return path
        
        return None


class AudioProcessor:
    """Обработка аудио файлов."""
    
    def __init__(self, log_callback):
        self.log = log_callback
        self.model = None
        self.translator = None
    
    def load_models(self):
        """Загружает модели Whisper и переводчика."""
        self.log("Загрузка модели Whisper...", "info")
        self.model = whisper.load_model("base")
        self.translator = Translator()
        self.log("Модели загружены", "success")
    
    def find_media_files(self, directory: str) -> List[Path]:
        """Находит все MP3 и MP4 файлы в директории."""
        directory_path = Path(directory).resolve()
        if not directory_path.exists():
            raise ValueError(f"Директория '{directory}' не существует!")
        
        media_files = []
        # Ищем MP3 и MP4 файлы
        for pattern in ["*.mp3", "*.MP3", "*.mp4", "*.MP4"]:
            for file_path in directory_path.glob(pattern):
                abs_path = file_path.resolve()
                if abs_path not in media_files:
                    media_files.append(abs_path)
        
        if not media_files:
            raise ValueError(f"В директории '{directory}' не найдено MP3/MP4 файлов!")
        
        return sorted(media_files)
    
    def transcribe_audio(self, file_path: Path) -> str:
        """Распознает речь из аудио или видео файла."""
        try:
            abs_path = file_path.resolve()
            if not abs_path.exists():
                return ""
            
            normalized_path = os.path.abspath(str(abs_path))
            if not os.path.exists(normalized_path):
                return ""
            
            result = self.model.transcribe(normalized_path, language="en")
            return result["text"].strip()
        except Exception as e:
            self.log(f"Ошибка: {file_path.name} - {str(e)[:50]}", "error")
            return ""
    
    def translate_text(self, text: str, dest_lang: str = "ru") -> str:
        """Переводит текст с английского на указанный язык."""
        if not text:
            return ""
        
        try:
            result = self.translator.translate(text, src="en", dest=dest_lang)
            return result.text
        except Exception as e:
            self.log(f"Ошибка перевода: {str(e)[:50]}", "error")
            return ""


class AudioTranslatorApp(ctk.CTk):
    """Главное приложение."""
    
    def __init__(self):
        super().__init__()
        
        self.title("Переводчик речи из MP3")
        
        # Переменные
        self.directory_path = ctk.StringVar()
        self.output_file = ctk.StringVar(value="translations.txt")
        self.translate_lang = ctk.StringVar(value="RU")
        self.include_original = ctk.BooleanVar(value=True)
        self.is_processing = False
        self.processor = AudioProcessor(self.log_message)
        
        # Сначала создаём виджеты
        self.create_widgets()
        # Затем открываем во весь экран и обновляем layout
        self.open_fullscreen()
        self.update_idletasks()
    
    def open_fullscreen(self):
        """Открывает окно во весь экран."""
        self.update_idletasks()
        try:
            # Для Windows используем state("zoomed") - это правильный способ
            self.state("zoomed")
        except:
            # Для других ОС или если не работает - используем размеры экрана
            # Учитываем панель задач (вычитаем ~40 пикселей)
            width = self.winfo_screenwidth()
            height = self.winfo_screenheight() - 40
            self.geometry(f"{width}x{height}+0+0")
    
    def create_widgets(self):
        """Создаёт интерфейс."""
        # Заголовок
        header = ctk.CTkLabel(
            self,
            text="Переводчик речи из MP3",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        header.pack(pady=(15, 3))
        
        subtitle = ctk.CTkLabel(
            self,
            text="Распознавание речи и перевод с английского",
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        subtitle.pack(pady=(0, 15))
        
        # Основной контейнер
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=(5, 10))
        
        # Выбор директории
        dir_frame = ctk.CTkFrame(main_frame)
        dir_frame.pack(fill="x", padx=20, pady=15)
        
        ctk.CTkLabel(
            dir_frame,
            text="📁 Папка с MP3/MP4 файлами:",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))
        
        dir_input_frame = ctk.CTkFrame(dir_frame, fg_color="transparent")
        dir_input_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        self.dir_entry = ctk.CTkEntry(
            dir_input_frame,
            textvariable=self.directory_path,
            font=ctk.CTkFont(size=12),
            height=40
        )
        self.dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ctk.CTkButton(
            dir_input_frame,
            text="Выбрать",
            command=self.browse_directory,
            width=120,
            height=40,
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="right")
        
        # Выбор выходного файла
        output_frame = ctk.CTkFrame(main_frame)
        output_frame.pack(fill="x", padx=20, pady=15)
        
        ctk.CTkLabel(
            output_frame,
            text="💾 Выходной файл:",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))
        
        output_input_frame = ctk.CTkFrame(output_frame, fg_color="transparent")
        output_input_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        self.output_entry = ctk.CTkEntry(
            output_input_frame,
            textvariable=self.output_file,
            font=ctk.CTkFont(size=12),
            height=40
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ctk.CTkButton(
            output_input_frame,
            text="Изменить путь",
            command=self.browse_output_file,
            width=120,
            height=40,
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="right")
        
        # Настройки перевода
        settings_frame = ctk.CTkFrame(main_frame)
        settings_frame.pack(fill="x", padx=20, pady=15)
        
        ctk.CTkLabel(
            settings_frame,
            text="⚙️ Настройки:",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(15, 10))
        
        settings_inner = ctk.CTkFrame(settings_frame, fg_color="transparent")
        settings_inner.pack(fill="x", padx=15, pady=(0, 15))
        
        # Выбор языка перевода
        lang_frame = ctk.CTkFrame(settings_inner, fg_color="transparent")
        lang_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(
            lang_frame,
            text="Язык перевода:",
            font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=(0, 10))
        
        self.lang_combo = ctk.CTkComboBox(
            lang_frame,
            values=["RU", "UK", "DE", "FR", "ES", "IT", "PL", "ZH", "JA", "KO"],
            variable=self.translate_lang,
            width=100,
            height=35,
            font=ctk.CTkFont(size=12)
        )
        self.lang_combo.pack(side="left")
        
        # Подписи языков
        lang_names = {
            "RU": "Русский", "UK": "Украинский", "DE": "Немецкий", 
            "FR": "Французский", "ES": "Испанский", "IT": "Итальянский",
            "PL": "Польский", "ZH": "Китайский", "JA": "Японский", "KO": "Корейский"
        }
        self.lang_label = ctk.CTkLabel(
            lang_frame,
            text=lang_names.get(self.translate_lang.get(), ""),
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.lang_label.pack(side="left", padx=(10, 0))
        
        # Обновление подписи при изменении языка
        def update_lang_label(*args):
            lang = self.translate_lang.get()
            self.lang_label.configure(text=lang_names.get(lang, ""))
        self.translate_lang.trace("w", update_lang_label)
        
        # Чекбокс для оригинального текста
        self.include_original_check = ctk.CTkCheckBox(
            settings_inner,
            text="Включить оригинальный текст (EN) в выходной файл",
            variable=self.include_original,
            font=ctk.CTkFont(size=12)
        )
        self.include_original_check.pack(anchor="w", pady=10)
        
        # Кнопка запуска
        self.start_btn = ctk.CTkButton(
            main_frame,
            text="▶ Начать обработку",
            command=self.start_processing,
            height=50,
            width=300,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=("#3B82F6", "#2563EB"),
            hover_color=("#2563EB", "#1D4ED8")
        )
        self.start_btn.pack(pady=20)
        
        # Прогресс-бар
        self.progress_var = ctk.DoubleVar()
        self.progress_bar = ctk.CTkProgressBar(
            main_frame,
            variable=self.progress_var,
            width=500,
            height=20
        )
        self.progress_bar.pack(pady=(0, 15))
        self.progress_bar.set(0)
        
        # Короткий статус с текущим файлом
        self.status_label = ctk.CTkLabel(
            main_frame,
            text="Готов к работе",
            font=ctk.CTkFont(size=13),
            text_color="gray"
        )
        self.status_label.pack(pady=(0, 20))
    
    def log_message(self, message: str, level: str = "info"):
        """Обновляет статус (заглушка для совместимости)."""
        pass
    
    def browse_directory(self):
        """Выбор директории."""
        directory = filedialog.askdirectory(title="Выберите папку с MP3/MP4 файлами")
        if directory:
            self.directory_path.set(directory)
            default_output = str(Path(directory) / "translations.txt")
            self.output_file.set(default_output)
    
    def browse_output_file(self):
        """Выбор выходного файла.
        
        Кнопка 'Изменить путь' позволяет выбрать другое место для сохранения
        результатов. По умолчанию файл создаётся в той же папке, где находятся MP3.
        """
        filename = filedialog.asksaveasfilename(
            title="Выберите место для сохранения переводов",
            defaultextension=".txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")]
        )
        if filename:
            self.output_file.set(filename)
    
    def start_processing(self):
        """Запускает обработку."""
        if self.is_processing:
            return
        
        directory = self.directory_path.get().strip()
        output_file = self.output_file.get().strip()
        
        if not directory:
            messagebox.showwarning("Предупреждение", "Выберите папку с MP3/MP4 файлами!")
            return
        
        if not output_file:
            output_file = str(Path(directory) / "translations.txt")
            self.output_file.set(output_file)
        
        output_path = Path(output_file)
        if not output_path.is_absolute():
            output_file = str(Path(directory) / output_path.name)
            self.output_file.set(output_file)
        
        try:
            media_files = self.processor.find_media_files(directory)
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
            return
        
        # Запускаем обработку
        self.is_processing = True
        self.start_btn.configure(text="⏸ Обработка...", state="disabled", width=300)
        self.status_label.configure(text="Подготовка...")
        
        thread = threading.Thread(
            target=self.process_files,
            args=(media_files, output_file),
            daemon=True
        )
        thread.start()
    
    def process_files(self, media_files: List[Path], output_file: str):
        """Обрабатывает файлы."""
        try:
            # Проверка ffmpeg
            ffmpeg_path = FFmpegManager.find_ffmpeg()
            
            # Загрузка моделей
            self.status_label.configure(text="Загрузка моделей...")
            self.update()
            self.processor.load_models()
            
            results = []
            total_files = len(media_files)
            
            for idx, file_path in enumerate(media_files, 1):
                if not self.is_processing:
                    break
                
                progress = (idx - 1) / total_files * 100
                self.progress_var.set(progress / 100)
                
                # Обновляем статус с текущим файлом
                self.status_label.configure(
                    text=f"Файл {idx} из {total_files}: {file_path.name}"
                )
                self.update()
                
                # Проверка существования
                abs_path = file_path.resolve()
                if not abs_path.exists():
                    results.append((file_path.name, "", ""))
                    continue
                
                # Распознавание
                english_text = self.processor.transcribe_audio(file_path)
                
                if not english_text:
                    results.append((file_path.name, "", ""))
                    continue
                
                # Перевод
                dest_lang = self.translate_lang.get().lower()  # Преобразуем в нижний регистр для API
                translated_text = self.processor.translate_text(english_text, dest_lang)
                
                if not translated_text:
                    results.append((file_path.name, english_text, ""))
                    continue
                
                results.append((file_path.name, english_text, translated_text))
            
            # Сохранение
            if self.is_processing:
                self.status_label.configure(text="Сохранение результатов...")
                self.update()
                
                dest_lang_upper = self.translate_lang.get()  # Уже в верхнем регистре
                lang_code = dest_lang_upper
                
                with open(output_file, "w", encoding="utf-8") as f:
                    for idx, (filename, english, translated) in enumerate(results):
                        # Разделитель перед каждым файлом
                        f.write(f"{'='*40}\n")
                        f.write(f"Файл: {filename}\n")
                        f.write(f"{'='*40}\n")
                        f.write(f"\n")
                        
                        if self.include_original.get():
                            f.write(f"Original (EN):\n\n{english}\n\n")
                        
                        f.write(f"Translate ({lang_code}):\n\n{translated}\n\n")
                        
                        # Разделитель только в самом конце (после последнего файла)
                        if idx == len(results) - 1:
                            f.write(f"{'='*40}\n")
                
                self.progress_var.set(1.0)
                self.status_label.configure(text=f"Готово! Обработано файлов: {len(results)}")
                
                messagebox.showinfo(
                    "Готово!",
                    f"Обработка завершена!\n\nОбработано файлов: {len(results)}\nРезультаты: {output_file}"
                )
        
        except Exception as e:
            self.status_label.configure(text=f"Ошибка: {str(e)[:50]}")
            messagebox.showerror("Ошибка", f"Произошла ошибка:\n{e}")
        
        finally:
            self.is_processing = False
            self.start_btn.configure(text="▶ Начать обработку", state="normal", width=300)
            self.progress_var.set(0)


def main():
    """Точка входа."""
    app = AudioTranslatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()