 # tools/image_webp_optimizer_gui.py

from __future__ import annotations

import csv
import queue
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps


APP_TITLE = "Image WebP Optimizer"
OUTPUT_ROOT_NAME = "otimizacao-imgs-webp"

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".avif",
    ".heic",
    ".heif",
}

PRESETS = {
    "thumbnail": {"width": 200, "quality": 78},
    "card": {"width": 400, "quality": 82},
    "detail": {"width": 800, "quality": 85},
    "hero": {"width": 1200, "quality": 86},
}

COLORS = {
    "bg": "#fffafc",
    "panel": "#fff4f8",
    "panel_alt": "#fff8fb",
    "surface": "#ffffff",
    "border": "#e9c9d7",
    "border_strong": "#d8a8bd",
    "text": "#4b2f3a",
    "muted": "#8b6676",
    "primary": "#d88aac",
    "primary_hover": "#c96f97",
    "primary_active": "#b95f87",
    "secondary": "#f6dfe8",
    "success": "#dff3e6",
    "success_text": "#245b36",
    "warning": "#fff1d6",
    "warning_text": "#8c5a00",
    "danger": "#ffe0e0",
    "danger_text": "#8d2f2f",
    "stripe": "#fff7fa",
}


@dataclass
class ConversionResult:
    status: str
    source_file: str
    output_file: str
    preset: str
    original_size: int
    converted_size: int
    message: str


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def iter_image_files(folder: Path) -> Iterable[Path]:
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def sanitize_folder_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip()
    return cleaned or "folder"


def sanitize_file_stem(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch not in '<>:"/\\|?*').strip()
    return cleaned or "image"


def fix_orientation(image: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(image)


def resize_keep_ratio(image: Image.Image, max_width: int) -> Image.Image:
    if image.width <= max_width:
        return image

    new_height = int(image.height * (max_width / image.width))
    return image.resize((max_width, new_height), Image.Resampling.LANCZOS)


def convert_mode_for_webp(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA"):
        return image

    if image.mode == "P":
        return image.convert("RGBA")

    if image.mode not in ("RGB", "RGBA"):
        return image.convert("RGB")

    return image


def build_output_path_for_folder(
    source_root: Path,
    source_file: Path,
    output_root: Path,
    source_folder_name: str,
    preset_name: str,
) -> Path:
    relative_path = source_file.relative_to(source_root)
    safe_stem = sanitize_file_stem(relative_path.stem)
    new_filename = f"{safe_stem}_{preset_name}.webp"
    return output_root / source_folder_name / preset_name / relative_path.parent / new_filename


def build_output_path_for_single_image(
    source_file: Path,
    output_root: Path,
    preset_name: str,
) -> Path:
    safe_parent = sanitize_folder_name(source_file.parent.name or "single-image")
    safe_stem = sanitize_file_stem(source_file.stem)
    new_filename = f"{safe_stem}_{preset_name}.webp"
    return output_root / "_single_images" / safe_parent / preset_name / new_filename


def save_report_csv(output_root: Path, rows: list[ConversionResult]) -> Path:
    report_path = output_root / "conversion_report.csv"
    ensure_parent_dir(report_path)

    with report_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "status",
                "source_file",
                "output_file",
                "preset",
                "original_size_bytes",
                "converted_size_bytes",
                "message",
            ]
        )

        for row in rows:
            writer.writerow(
                [
                    row.status,
                    row.source_file,
                    row.output_file,
                    row.preset,
                    row.original_size,
                    row.converted_size,
                    row.message,
                ]
            )

    return report_path


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, *args, **kwargs) -> None:
        super().__init__(parent, *args, **kwargs)

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            bg=COLORS["bg"],
            bd=0,
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)

        self.inner = ttk.Frame(self.canvas, style="App.TFrame")
        self.inner.bind("<Configure>", self._on_inner_configure)

        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel(self.canvas)
        self._bind_mousewheel(self.inner)

    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if getattr(event, "delta", 0):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        elif getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(1, "units")

    def _bind_mousewheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>", self._on_mousewheel)
        widget.bind("<Button-5>", self._on_mousewheel)


class ImageConverterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1440x900")
        self.root.minsize(1180, 760)
        self.root.configure(bg=COLORS["bg"])

        self.selected_folders: list[Path] = []
        self.selected_single_images: list[Path] = []

        self.worker_thread: threading.Thread | None = None
        self.ui_queue: queue.Queue = queue.Queue()
        self.results: list[ConversionResult] = []

        self.generate_all_presets_var = tk.BooleanVar(value=True)
        self.selected_preset_var = tk.StringVar(value="card")
        self.skip_if_larger_var = tk.BooleanVar(value=True)
        self.keep_existing_var = tk.BooleanVar(value=False)
        self.method_var = tk.IntVar(value=6)

        self.success_count_var = tk.StringVar(value="0")
        self.failed_count_var = tk.StringVar(value="0")
        self.skipped_count_var = tk.StringVar(value="0")
        self.processed_count_var = tk.StringVar(value="0")
        self.total_before_var = tk.StringVar(value="0 B")
        self.total_after_var = tk.StringVar(value="0 B")
        self.output_path_var = tk.StringVar(value=str(self.get_output_root()))

        self._configure_styles()
        self._build_ui()
        self._poll_queue()

    def get_output_root(self) -> Path:
        return Path.cwd() / OUTPUT_ROOT_NAME

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)

        try:
            if "clam" in style.theme_names():
                style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            ".",
            background=COLORS["bg"],
            foreground=COLORS["text"],
            font=("Segoe UI", 10),
        )

        style.configure("App.TFrame", background=COLORS["bg"])
        style.configure("Card.TFrame", background=COLORS["panel"], relief="flat")
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure(
            "Card.TLabelframe",
            background=COLORS["panel"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=("Segoe UI", 10, "bold"),
        )

        style.configure(
            "Title.TLabel",
            background=COLORS["bg"],
            foreground=COLORS["text"],
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=COLORS["bg"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Section.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "SummaryKey.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "SummaryValue.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["text"],
            font=("Segoe UI", 14, "bold"),
        )

        style.configure(
            "Primary.TButton",
            background=COLORS["primary"],
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=0,
            padding=(12, 10),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[
                ("pressed", COLORS["primary_active"]),
                ("active", COLORS["primary_hover"]),
            ],
            foreground=[("disabled", "#f5e9ef")],
        )

        style.configure(
            "Soft.TButton",
            background=COLORS["secondary"],
            foreground=COLORS["text"],
            borderwidth=0,
            focusthickness=0,
            padding=(12, 9),
        )
        style.map(
            "Soft.TButton",
            background=[
                ("pressed", "#efcfdb"),
                ("active", "#efd3dd"),
            ],
        )

        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            padding=7,
        )
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            padding=6,
        )
        style.configure(
            "TSpinbox",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            padding=5,
        )
        style.configure(
            "TCheckbutton",
            background=COLORS["panel"],
            foreground=COLORS["text"],
        )

        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor="#f2d7e3",
            background=COLORS["primary"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["primary"],
            darkcolor=COLORS["primary"],
        )

        style.configure(
            "TNotebook",
            background=COLORS["panel"],
            borderwidth=0,
            tabmargins=[0, 0, 0, 0],
        )
        style.configure(
            "TNotebook.Tab",
            background="#f5dbe6",
            foreground=COLORS["text"],
            padding=(16, 10),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", COLORS["surface"]),
                ("active", "#f1d3df"),
            ],
        )

        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            rowheight=28,
        )
        style.configure(
            "Treeview.Heading",
            background="#f7dce7",
            foreground=COLORS["text"],
            relief="flat",
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", "#f0d5e1")],
            foreground=[("selected", COLORS["text"])],
        )

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding=14, style="App.TFrame")
        main_frame.pack(fill="both", expand=True)

        header_frame = ttk.Frame(main_frame, style="App.TFrame")
        header_frame.pack(fill="x", pady=(0, 12))

        ttk.Label(
            header_frame,
            text="Conversor de imagens para WebP",
            style="Title.TLabel",
        ).pack(anchor="w")

        ttk.Label(
            header_frame,
            text=(
                "Converta pastas inteiras ou apenas imagens individuais. "
                "Saída organizada por preset dentro de otimizacao-imgs-webp."
            ),
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        content_frame = ttk.Frame(main_frame, style="App.TFrame")
        content_frame.pack(fill="both", expand=True)

        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=0)
        content_frame.grid_columnconfigure(1, weight=1)

        left_wrapper = ttk.Frame(content_frame, width=390, style="App.TFrame")
        left_wrapper.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        left_wrapper.grid_propagate(False)
        left_wrapper.grid_rowconfigure(0, weight=1)
        left_wrapper.grid_columnconfigure(0, weight=1)

        self.left_scrollable = ScrollableFrame(left_wrapper)
        self.left_scrollable.grid(row=0, column=0, sticky="nsew")

        left_frame = self.left_scrollable.inner

        right_frame = ttk.Frame(content_frame, style="App.TFrame")
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.grid_rowconfigure(0, weight=0)
        right_frame.grid_rowconfigure(1, weight=1)
        right_frame.grid_rowconfigure(2, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        selection_box = ttk.LabelFrame(left_frame, text="Seleção de origem", padding=12, style="Card.TLabelframe")
        selection_box.pack(fill="both", expand=False)

        self.selection_notebook = ttk.Notebook(selection_box)
        self.selection_notebook.pack(fill="both", expand=True)

        folder_tab = ttk.Frame(self.selection_notebook, style="App.TFrame")
        single_tab = ttk.Frame(self.selection_notebook, style="App.TFrame")
        self.selection_notebook.add(folder_tab, text="Pastas")
        self.selection_notebook.add(single_tab, text="1 imagem")

        self._build_folder_tab(folder_tab)
        self._build_single_image_tab(single_tab)

        options_box = ttk.LabelFrame(left_frame, text="Configurações", padding=12, style="Card.TLabelframe")
        options_box.pack(fill="x", pady=(12, 0))

        ttk.Checkbutton(
            options_box,
            text="Gerar todos os presets (thumbnail, card, detail, hero)",
            variable=self.generate_all_presets_var,
            command=self.toggle_preset_mode,
        ).pack(anchor="w", pady=3)

        preset_row = ttk.Frame(options_box, style="Card.TFrame")
        preset_row.pack(fill="x", pady=(8, 6))

        ttk.Label(preset_row, text="Preset único:", style="Section.TLabel").pack(side="left")
        self.preset_combo = ttk.Combobox(
            preset_row,
            textvariable=self.selected_preset_var,
            state="readonly",
            values=list(PRESETS.keys()),
            width=16,
        )
        self.preset_combo.pack(side="left", padx=(10, 0))

        method_row = ttk.Frame(options_box, style="Card.TFrame")
        method_row.pack(fill="x", pady=4)

        ttk.Label(method_row, text="Compressão WebP (0-6):", style="Section.TLabel").pack(side="left")
        self.method_spin = ttk.Spinbox(
            method_row,
            from_=0,
            to=6,
            textvariable=self.method_var,
            width=6,
        )
        self.method_spin.pack(side="left", padx=(10, 0))

        ttk.Checkbutton(
            options_box,
            text="Pular arquivo se o WebP ficar maior que o original",
            variable=self.skip_if_larger_var,
        ).pack(anchor="w", pady=3)

        ttk.Checkbutton(
            options_box,
            text="Manter arquivo convertido já existente",
            variable=self.keep_existing_var,
        ).pack(anchor="w", pady=3)

        output_box = ttk.LabelFrame(left_frame, text="Destino", padding=12, style="Card.TLabelframe")
        output_box.pack(fill="x", pady=(12, 0))

        ttk.Entry(output_box, textvariable=self.output_path_var, state="readonly").pack(fill="x")

        action_box = ttk.LabelFrame(left_frame, text="Execução", padding=12, style="Card.TLabelframe")
        action_box.pack(fill="x", pady=(12, 12))

        self.start_button = ttk.Button(
            action_box,
            text="Iniciar conversão",
            command=self.start_conversion,
            style="Primary.TButton",
        )
        self.start_button.pack(fill="x", pady=3)

        self.open_output_button = ttk.Button(
            action_box,
            text="Abrir pasta de saída",
            command=self.open_output_folder,
            style="Soft.TButton",
        )
        self.open_output_button.pack(fill="x", pady=3)

        self.progress = ttk.Progressbar(
            action_box,
            mode="determinate",
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", pady=(12, 0))

        self.progress_label = ttk.Label(
            action_box,
            text="Aguardando...",
            style="Subtitle.TLabel",
        )
        self.progress_label.pack(anchor="w", pady=(6, 0))

        summary_box = ttk.LabelFrame(right_frame, text="Resumo", padding=12, style="Card.TLabelframe")
        summary_box.grid(row=0, column=0, sticky="ew")

        summary_grid = ttk.Frame(summary_box, style="App.TFrame")
        summary_grid.pack(fill="x")

        self._summary_item(summary_grid, "Processados", self.processed_count_var, 0, 0)
        self._summary_item(summary_grid, "Sucesso", self.success_count_var, 0, 1)
        self._summary_item(summary_grid, "Falhas", self.failed_count_var, 1, 0)
        self._summary_item(summary_grid, "Pulados", self.skipped_count_var, 1, 1)
        self._summary_item(summary_grid, "Total antes", self.total_before_var, 2, 0)
        self._summary_item(summary_grid, "Total depois", self.total_after_var, 2, 1)

        results_box = ttk.LabelFrame(right_frame, text="Resultados", padding=12, style="Card.TLabelframe")
        results_box.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        results_box.grid_rowconfigure(0, weight=1)
        results_box.grid_columnconfigure(0, weight=1)

        columns = ("status", "preset", "source", "output", "message")
        self.results_tree = ttk.Treeview(results_box, columns=columns, show="headings")

        self.results_tree.heading("status", text="Status")
        self.results_tree.heading("preset", text="Preset")
        self.results_tree.heading("source", text="Arquivo de origem")
        self.results_tree.heading("output", text="Arquivo de saída")
        self.results_tree.heading("message", text="Mensagem")

        self.results_tree.column("status", width=90, anchor="center")
        self.results_tree.column("preset", width=90, anchor="center")
        self.results_tree.column("source", width=300, anchor="w")
        self.results_tree.column("output", width=300, anchor="w")
        self.results_tree.column("message", width=340, anchor="w")

        tree_scroll_y = ttk.Scrollbar(results_box, orient="vertical", command=self.results_tree.yview)
        tree_scroll_x = ttk.Scrollbar(results_box, orient="horizontal", command=self.results_tree.xview)
        self.results_tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.results_tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")

        self.results_tree.tag_configure("SUCCESS", background="#eefaf2", foreground=COLORS["success_text"])
        self.results_tree.tag_configure("FAILED", background="#fff0f0", foreground=COLORS["danger_text"])
        self.results_tree.tag_configure("SKIPPED", background="#fff8e9", foreground=COLORS["warning_text"])

        log_box = ttk.LabelFrame(right_frame, text="Log", padding=12, style="Card.TLabelframe")
        log_box.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        log_box.grid_rowconfigure(0, weight=1)
        log_box.grid_columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_box,
            wrap="word",
            font=("Consolas", 10),
            bd=0,
            relief="flat",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            padx=10,
            pady=10,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        log_scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.toggle_preset_mode()

    def _build_folder_tab(self, parent: ttk.Frame) -> None:
        wrapper = ttk.Frame(parent, padding=8, style="App.TFrame")
        wrapper.pack(fill="both", expand=True)

        ttk.Label(
            wrapper,
            text="Adicione uma ou mais pastas para converter tudo recursivamente.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(wrapper, style="App.TFrame")
        list_frame.pack(fill="both", expand=True)

        self.folder_listbox = tk.Listbox(
            list_frame,
            height=11,
            selectmode=tk.EXTENDED,
            font=("Consolas", 10),
            activestyle="none",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            selectbackground="#f0d5e1",
            selectforeground=COLORS["text"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            relief="flat",
            bd=0,
        )
        self.folder_listbox.pack(fill="both", expand=True)

        buttons = ttk.Frame(wrapper, style="App.TFrame")
        buttons.pack(fill="x", pady=(10, 0))

        ttk.Button(buttons, text="Adicionar pasta", command=self.add_folder, style="Soft.TButton").pack(fill="x", pady=2)
        ttk.Button(buttons, text="Adicionar várias pastas", command=self.add_multiple_folders, style="Soft.TButton").pack(fill="x", pady=2)
        ttk.Button(buttons, text="Remover selecionadas", command=self.remove_selected_folders, style="Soft.TButton").pack(fill="x", pady=2)
        ttk.Button(buttons, text="Limpar lista", command=self.clear_folders, style="Soft.TButton").pack(fill="x", pady=2)

    def _build_single_image_tab(self, parent: ttk.Frame) -> None:
        wrapper = ttk.Frame(parent, padding=8, style="App.TFrame")
        wrapper.pack(fill="both", expand=True)

        ttk.Label(
            wrapper,
            text="Selecione uma ou mais imagens avulsas para otimização rápida.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(wrapper, style="App.TFrame")
        list_frame.pack(fill="both", expand=True)

        self.single_image_listbox = tk.Listbox(
            list_frame,
            height=11,
            selectmode=tk.EXTENDED,
            font=("Consolas", 10),
            activestyle="none",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            selectbackground="#f0d5e1",
            selectforeground=COLORS["text"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            relief="flat",
            bd=0,
        )
        self.single_image_listbox.pack(fill="both", expand=True)

        buttons = ttk.Frame(wrapper, style="App.TFrame")
        buttons.pack(fill="x", pady=(10, 0))

        ttk.Button(buttons, text="Selecionar imagem", command=self.add_single_image, style="Soft.TButton").pack(fill="x", pady=2)
        ttk.Button(buttons, text="Selecionar várias imagens", command=self.add_multiple_images, style="Soft.TButton").pack(fill="x", pady=2)
        ttk.Button(buttons, text="Remover selecionadas", command=self.remove_selected_single_images, style="Soft.TButton").pack(fill="x", pady=2)
        ttk.Button(buttons, text="Limpar lista", command=self.clear_single_images, style="Soft.TButton").pack(fill="x", pady=2)

    def _summary_item(
        self,
        parent: ttk.Frame,
        label_text: str,
        variable: tk.StringVar,
        row: int,
        column: int,
    ) -> None:
        card = ttk.Frame(parent, style="Surface.TFrame", padding=12)
        card.grid(row=row, column=column, sticky="ew", padx=5, pady=5)
        parent.grid_columnconfigure(column, weight=1)

        ttk.Label(card, text=label_text, style="SummaryKey.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="SummaryValue.TLabel").pack(anchor="w", pady=(4, 0))

    def toggle_preset_mode(self) -> None:
        state = "disabled" if self.generate_all_presets_var.get() else "readonly"
        self.preset_combo.configure(state=state)

    def add_folder(self) -> None:
        selected = filedialog.askdirectory(title="Selecione uma pasta")
        if selected:
            path = Path(selected)
            if path not in self.selected_folders:
                self.selected_folders.append(path)
                self.folder_listbox.insert(tk.END, str(path))

    def add_multiple_folders(self) -> None:
        while True:
            selected = filedialog.askdirectory(title="Selecione uma pasta (Cancelar para encerrar)")
            if not selected:
                break

            path = Path(selected)
            if path not in self.selected_folders:
                self.selected_folders.append(path)
                self.folder_listbox.insert(tk.END, str(path))

    def remove_selected_folders(self) -> None:
        selected_indices = list(self.folder_listbox.curselection())
        if not selected_indices:
            return

        for index in reversed(selected_indices):
            self.folder_listbox.delete(index)
            del self.selected_folders[index]

    def clear_folders(self) -> None:
        self.folder_listbox.delete(0, tk.END)
        self.selected_folders.clear()

    def add_single_image(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione uma imagem",
            filetypes=[
                ("Imagens suportadas", " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if selected:
            path = Path(selected)
            if path not in self.selected_single_images:
                self.selected_single_images.append(path)
                self.single_image_listbox.insert(tk.END, str(path))

    def add_multiple_images(self) -> None:
        selected_files = filedialog.askopenfilenames(
            title="Selecione uma ou mais imagens",
            filetypes=[
                ("Imagens suportadas", " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))),
                ("Todos os arquivos", "*.*"),
            ],
        )
        for selected in selected_files:
            path = Path(selected)
            if path not in self.selected_single_images:
                self.selected_single_images.append(path)
                self.single_image_listbox.insert(tk.END, str(path))

    def remove_selected_single_images(self) -> None:
        selected_indices = list(self.single_image_listbox.curselection())
        if not selected_indices:
            return

        for index in reversed(selected_indices):
            self.single_image_listbox.delete(index)
            del self.selected_single_images[index]

    def clear_single_images(self) -> None:
        self.single_image_listbox.delete(0, tk.END)
        self.selected_single_images.clear()

    def append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def clear_results_ui(self) -> None:
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

        self.results.clear()
        self.success_count_var.set("0")
        self.failed_count_var.set("0")
        self.skipped_count_var.set("0")
        self.processed_count_var.set("0")
        self.total_before_var.set("0 B")
        self.total_after_var.set("0 B")
        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.progress_label.configure(text="Aguardando...")

    def start_conversion(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("Processando", "A conversão já está em andamento.")
            return

        active_tab = self.selection_notebook.index(self.selection_notebook.select())
        is_folder_mode = active_tab == 0

        if is_folder_mode and not self.selected_folders:
            messagebox.showwarning("Sem pastas", "Selecione pelo menos uma pasta.")
            return

        if not is_folder_mode and not self.selected_single_images:
            messagebox.showwarning("Sem imagens", "Selecione pelo menos uma imagem.")
            return

        self.clear_results_ui()
        self.start_button.configure(state="disabled")

        output_root = self.get_output_root()
        output_root.mkdir(parents=True, exist_ok=True)
        self.output_path_var.set(str(output_root))

        selected_presets = (
            list(PRESETS.keys())
            if self.generate_all_presets_var.get()
            else [self.selected_preset_var.get()]
        )

        self.worker_thread = threading.Thread(
            target=self.run_conversion_worker,
            args=(
                is_folder_mode,
                self.selected_folders.copy(),
                self.selected_single_images.copy(),
                output_root,
                selected_presets,
                self.skip_if_larger_var.get(),
                self.keep_existing_var.get(),
                int(self.method_var.get()),
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def open_output_folder(self) -> None:
        output_root = self.get_output_root()
        output_root.mkdir(parents=True, exist_ok=True)

        try:
            import os
            import subprocess
            import sys

            if sys.platform.startswith("win"):
                os.startfile(output_root)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", str(output_root)], check=False)
            else:
                subprocess.run(["xdg-open", str(output_root)], check=False)
        except Exception as exc:
            messagebox.showerror("Erro", f"Não foi possível abrir a pasta:\n{exc}")

    def run_conversion_worker(
        self,
        is_folder_mode: bool,
        folders: list[Path],
        single_images: list[Path],
        output_root: Path,
        presets: list[str],
        skip_if_larger: bool,
        keep_existing: bool,
        method: int,
    ) -> None:
        local_results: list[ConversionResult] = []

        try:
            jobs: list[tuple[str, Path | None, Path, str]] = []

            if is_folder_mode:
                for folder in folders:
                    for image_file in iter_image_files(folder):
                        for preset_name in presets:
                            jobs.append(("folder", folder, image_file, preset_name))
            else:
                for image_file in single_images:
                    if image_file.is_file() and image_file.suffix.lower() in SUPPORTED_EXTENSIONS:
                        for preset_name in presets:
                            jobs.append(("single", None, image_file, preset_name))

            total_jobs = len(jobs)
            self.ui_queue.put(("progress_max", total_jobs))

            if total_jobs == 0:
                self.ui_queue.put(("log", "Nenhuma imagem compatível foi encontrada na seleção atual."))
                self.ui_queue.put(("done", output_root))
                return

            total_before = 0
            total_after = 0
            processed = 0
            success = 0
            failed = 0
            skipped = 0

            mode_label = "pastas" if is_folder_mode else "imagem(ns) avulsa(s)"
            self.ui_queue.put(("log", f"Iniciando conversão de {total_jobs} item(ns) no modo {mode_label}..."))

            for job_type, source_root, source_file, preset_name in jobs:
                config = PRESETS[preset_name]

                if job_type == "folder" and source_root is not None:
                    source_folder_name = sanitize_folder_name(source_root.name)
                    output_file = build_output_path_for_folder(
                        source_root=source_root,
                        source_file=source_file,
                        output_root=output_root,
                        source_folder_name=source_folder_name,
                        preset_name=preset_name,
                    )
                else:
                    output_file = build_output_path_for_single_image(
                        source_file=source_file,
                        output_root=output_root,
                        preset_name=preset_name,
                    )

                try:
                    original_size = source_file.stat().st_size
                    total_before += original_size

                    if keep_existing and output_file.exists():
                        converted_size = output_file.stat().st_size
                        total_after += converted_size
                        processed += 1
                        skipped += 1

                        result = ConversionResult(
                            status="SKIPPED",
                            source_file=str(source_file),
                            output_file=str(output_file),
                            preset=preset_name,
                            original_size=original_size,
                            converted_size=converted_size,
                            message="Arquivo já existia",
                        )
                        local_results.append(result)
                        self.ui_queue.put(("result", result))
                        self.ui_queue.put(("progress_step", processed))
                        continue

                    ensure_parent_dir(output_file)

                    with Image.open(source_file) as image:
                        image = fix_orientation(image)
                        image = resize_keep_ratio(image, config["width"])
                        image = convert_mode_for_webp(image)
                        image.save(
                            output_file,
                            format="WEBP",
                            quality=config["quality"],
                            method=method,
                            optimize=True,
                        )

                    converted_size = output_file.stat().st_size

                    if skip_if_larger and converted_size >= original_size:
                        output_file.unlink(missing_ok=True)
                        total_after += original_size
                        processed += 1
                        skipped += 1

                        result = ConversionResult(
                            status="SKIPPED",
                            source_file=str(source_file),
                            output_file="",
                            preset=preset_name,
                            original_size=original_size,
                            converted_size=converted_size,
                            message="WebP ficou maior que o original",
                        )
                        local_results.append(result)
                        self.ui_queue.put(("result", result))
                        self.ui_queue.put(("progress_step", processed))
                        continue

                    total_after += converted_size
                    processed += 1
                    success += 1

                    result = ConversionResult(
                        status="SUCCESS",
                        source_file=str(source_file),
                        output_file=str(output_file),
                        preset=preset_name,
                        original_size=original_size,
                        converted_size=converted_size,
                        message=f"{format_bytes(original_size)} -> {format_bytes(converted_size)}",
                    )
                    local_results.append(result)
                    self.ui_queue.put(("result", result))
                    self.ui_queue.put(("progress_step", processed))

                except Exception as exc:
                    processed += 1
                    failed += 1

                    result = ConversionResult(
                        status="FAILED",
                        source_file=str(source_file),
                        output_file=str(output_file),
                        preset=preset_name,
                        original_size=0,
                        converted_size=0,
                        message=str(exc),
                    )
                    local_results.append(result)
                    self.ui_queue.put(("result", result))
                    self.ui_queue.put(("log", f"Erro em {source_file}: {exc}"))
                    self.ui_queue.put(("progress_step", processed))

            self.ui_queue.put(
                (
                    "summary",
                    {
                        "processed": processed,
                        "success": success,
                        "failed": failed,
                        "skipped": skipped,
                        "before": total_before,
                        "after": total_after,
                    },
                )
            )

            report_path = save_report_csv(output_root, local_results)
            self.ui_queue.put(("log", f"Relatório CSV salvo em: {report_path}"))
            self.ui_queue.put(("done", output_root))

        except Exception:
            self.ui_queue.put(("log", traceback.format_exc()))
            self.ui_queue.put(("done", output_root))

    def _poll_queue(self) -> None:
        try:
            while True:
                event = self.ui_queue.get_nowait()
                event_type = event[0]

                if event_type == "log":
                    self.append_log(event[1])

                elif event_type == "progress_max":
                    total = event[1]
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = 0
                    self.progress_label.configure(text=f"0 / {total}")

                elif event_type == "progress_step":
                    current = event[1]
                    self.progress["value"] = current
                    total = int(self.progress["maximum"])
                    self.progress_label.configure(text=f"{current} / {total}")

                elif event_type == "result":
                    result: ConversionResult = event[1]
                    self.results.append(result)

                    self.results_tree.insert(
                        "",
                        tk.END,
                        values=(
                            result.status,
                            result.preset,
                            result.source_file,
                            result.output_file,
                            result.message,
                        ),
                        tags=(result.status,),
                    )

                elif event_type == "summary":
                    data = event[1]
                    self.processed_count_var.set(str(data["processed"]))
                    self.success_count_var.set(str(data["success"]))
                    self.failed_count_var.set(str(data["failed"]))
                    self.skipped_count_var.set(str(data["skipped"]))
                    self.total_before_var.set(format_bytes(data["before"]))
                    self.total_after_var.set(format_bytes(data["after"]))

                    self.append_log(
                        "Resumo: "
                        f"processados={data['processed']}, "
                        f"sucesso={data['success']}, "
                        f"falhas={data['failed']}, "
                        f"pulados={data['skipped']}, "
                        f"antes={format_bytes(data['before'])}, "
                        f"depois={format_bytes(data['after'])}"
                    )

                elif event_type == "done":
                    self.start_button.configure(state="normal")
                    self.append_log("Conversão finalizada.")

        except queue.Empty:
            pass

        self.root.after(120, self._poll_queue)


def main() -> None:
    root = tk.Tk()
    ImageConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
