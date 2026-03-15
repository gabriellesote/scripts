# supabase_folder_uploader.py

import mimetypes
import os
import queue
import threading
from pathlib import Path
from typing import List, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from supabase import Client, create_client


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".svg",
    ".avif",
}


class SupabaseFolderUploaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Supabase Image Folder Uploader")
        self.root.geometry("1600x900")
        self.root.minsize(1200, 720)

        self.selected_folders: List[str] = []
        self.discovered_files: List[Tuple[str, str, str]] = []
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.is_uploading = False

        self.url_var = tk.StringVar()
        self.key_var = tk.StringVar()
        self.bucket_var = tk.StringVar()
        self.base_path_var = tk.StringVar()
        self.upsert_var = tk.BooleanVar(value=True)
        self.summary_var = tk.StringVar(value="Pronto para começar.")
        self.progress_var = tk.DoubleVar(value=0)

        self._configure_root()
        self._build_ui()
        self._poll_log_queue()

    def _configure_root(self) -> None:
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)

        style = ttk.Style()
        try:
            if "clam" in style.theme_names():
                style.theme_use("clam")
        except Exception:
            pass

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.rowconfigure(2, weight=1)
        main.columnconfigure(0, weight=1)

        self._build_header(main)
        self._build_top_section(main)
        self._build_bottom_section(main)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        title = ttk.Label(
            header,
            text="Supabase Image Folder Uploader",
            font=("Arial", 18, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = ttk.Label(
            header,
            text="Selecione pastas com imagens, revise os arquivos encontrados e envie tudo para o bucket do Supabase.",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_top_section(self, parent: ttk.Frame) -> None:
        top_pane = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        top_pane.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        left_frame = ttk.Labelframe(top_pane, text="Configuração do Supabase", padding=12)
        right_frame = ttk.Labelframe(top_pane, text="Pastas selecionadas", padding=12)

        top_pane.add(left_frame, weight=3)
        top_pane.add(right_frame, weight=2)

        self._build_config_panel(left_frame)
        self._build_folders_panel(right_frame)

    def _build_config_panel(self, parent: ttk.Labelframe) -> None:
        parent.columnconfigure(1, weight=1)

        ttk.Label(parent, text="Supabase URL").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(parent, textvariable=self.url_var).grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(parent, text="Supabase Key").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(parent, textvariable=self.key_var, show="*").grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(parent, text="Bucket").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(parent, textvariable=self.bucket_var).grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(parent, text="Base path no bucket").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=6)
        ttk.Entry(parent, textvariable=self.base_path_var).grid(row=3, column=1, sticky="ew", pady=6)

        ttk.Checkbutton(
            parent,
            text="Sobrescrever arquivos existentes (upsert)",
            variable=self.upsert_var,
        ).grid(row=4, column=1, sticky="w", pady=(8, 0))

    def _build_folders_panel(self, parent: ttk.Labelframe) -> None:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        buttons = ttk.Frame(parent)
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for col in range(4):
            buttons.columnconfigure(col, weight=1)

        ttk.Button(buttons, text="Adicionar pasta", command=self.add_folder).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="Remover selecionada", command=self.remove_selected_folder).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(buttons, text="Limpar", command=self.clear_folders).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(buttons, text="Escanear imagens", command=self.scan_images).grid(row=0, column=3, sticky="ew", padx=(4, 0))

        list_frame = ttk.Frame(parent)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.folders_listbox = tk.Listbox(list_frame, activestyle="none")
        self.folders_listbox.grid(row=0, column=0, sticky="nsew")

        folders_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.folders_listbox.yview)
        folders_scroll.grid(row=0, column=1, sticky="ns")
        self.folders_listbox.config(yscrollcommand=folders_scroll.set)

    def _build_bottom_section(self, parent: ttk.Frame) -> None:
        bottom_pane = ttk.Panedwindow(parent, orient=tk.VERTICAL)
        bottom_pane.grid(row=2, column=0, sticky="nsew")
        parent.rowconfigure(2, weight=1)

        files_frame = ttk.Labelframe(bottom_pane, text="Arquivos encontrados", padding=12)
        logs_frame = ttk.Labelframe(bottom_pane, text="Upload e logs", padding=12)

        bottom_pane.add(files_frame, weight=4)
        bottom_pane.add(logs_frame, weight=2)

        self._build_files_panel(files_frame)
        self._build_logs_panel(logs_frame)

    def _build_files_panel(self, parent: ttk.Labelframe) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        columns = ("folder_name", "local_path", "remote_path", "status")
        self.files_tree = ttk.Treeview(parent, columns=columns, show="headings")

        self.files_tree.heading("folder_name", text="Pasta")
        self.files_tree.heading("local_path", text="Arquivo local")
        self.files_tree.heading("remote_path", text="Destino no bucket")
        self.files_tree.heading("status", text="Status")

        self.files_tree.column("folder_name", width=160, minwidth=120, anchor="w", stretch=True)
        self.files_tree.column("local_path", width=520, minwidth=260, anchor="w", stretch=True)
        self.files_tree.column("remote_path", width=520, minwidth=260, anchor="w", stretch=True)
        self.files_tree.column("status", width=120, minwidth=100, anchor="center", stretch=False)

        y_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.files_tree.yview)
        x_scroll = ttk.Scrollbar(parent, orient="horizontal", command=self.files_tree.xview)

        self.files_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.files_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

    def _build_logs_panel(self, parent: ttk.Labelframe) -> None:
        parent.rowconfigure(2, weight=1)
        parent.columnconfigure(0, weight=1)

        action_row = ttk.Frame(parent)
        action_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        action_row.columnconfigure(1, weight=1)

        self.upload_button = ttk.Button(action_row, text="Iniciar upload", command=self.start_upload)
        self.upload_button.grid(row=0, column=0, sticky="w")

        progress_frame = ttk.Frame(action_row)
        progress_frame.grid(row=0, column=1, sticky="ew", padx=(12, 12))
        progress_frame.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky="ew")

        self.progress_label = ttk.Label(action_row, text="0 / 0", width=10, anchor="e")
        self.progress_label.grid(row=0, column=2, sticky="e")

        ttk.Label(parent, textvariable=self.summary_var).grid(row=1, column=0, sticky="w", pady=(0, 8))

        log_frame = ttk.Frame(parent)
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=10, wrap="none")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_y_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_y_scroll.grid(row=0, column=1, sticky="ns")

        log_x_scroll = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log_text.xview)
        log_x_scroll.grid(row=1, column=0, sticky="ew")

        self.log_text.configure(
            state="disabled",
            yscrollcommand=log_y_scroll.set,
            xscrollcommand=log_x_scroll.set,
        )

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Selecione uma pasta com imagens")
        if not folder:
            return

        if folder not in self.selected_folders:
            self.selected_folders.append(folder)
            self.folders_listbox.insert(tk.END, folder)
            self._log(f"Pasta adicionada: {folder}")
        else:
            self._log(f"Pasta já selecionada: {folder}")

    def remove_selected_folder(self) -> None:
        selection = self.folders_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        folder = self.folders_listbox.get(index)
        self.folders_listbox.delete(index)
        self.selected_folders.remove(folder)
        self._log(f"Pasta removida: {folder}")

    def clear_folders(self) -> None:
        self.selected_folders.clear()
        self.discovered_files.clear()
        self.folders_listbox.delete(0, tk.END)

        for item in self.files_tree.get_children():
            self.files_tree.delete(item)

        self.progress_var.set(0)
        self.progress_label.config(text="0 / 0")
        self.summary_var.set("Pastas limpas.")
        self._log("Todas as pastas foram removidas.")

    def scan_images(self) -> None:
        if not self.selected_folders:
            messagebox.showwarning("Aviso", "Adicione pelo menos uma pasta primeiro.")
            return

        self.discovered_files.clear()
        for item in self.files_tree.get_children():
            self.files_tree.delete(item)

        base_path = self._normalize_base_path(self.base_path_var.get())
        total_found = 0

        for folder in self.selected_folders:
            folder_path = Path(folder)
            folder_name = folder_path.name

            for file_path in folder_path.rglob("*"):
                if not file_path.is_file():
                    continue

                if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue

                relative_path = file_path.relative_to(folder_path).as_posix()
                remote_path = f"{folder_name}/{relative_path}"

                if base_path:
                    remote_path = f"{base_path}/{remote_path}"

                self.discovered_files.append((folder_name, str(file_path), remote_path))
                self.files_tree.insert(
                    "",
                    tk.END,
                    values=(folder_name, str(file_path), remote_path, "Pendente"),
                )
                total_found += 1

        self.progress_var.set(0)
        self.progress_label.config(text=f"0 / {total_found}")
        self.summary_var.set(f"{total_found} imagem(ns) encontradas.")
        self._log(f"Escaneamento concluído. Total de imagens encontradas: {total_found}")

        if total_found == 0:
            messagebox.showinfo("Resultado", "Nenhuma imagem encontrada nas pastas selecionadas.")

    def start_upload(self) -> None:
        if self.is_uploading:
            return

        if not self.discovered_files:
            messagebox.showwarning("Aviso", "Nenhuma imagem listada. Clique em 'Escanear imagens' primeiro.")
            return

        url = self.url_var.get().strip()
        key = self.key_var.get().strip()
        bucket = self.bucket_var.get().strip()

        if not url or not key or not bucket:
            messagebox.showwarning("Aviso", "Preencha Supabase URL, Key e Bucket.")
            return

        self.is_uploading = True
        self.upload_button.config(state="disabled")
        self.summary_var.set("Upload em andamento...")

        thread = threading.Thread(target=self._upload_worker, daemon=True)
        thread.start()

    def _upload_worker(self) -> None:
        try:
            url = self.url_var.get().strip()
            key = self.key_var.get().strip()
            bucket = self.bucket_var.get().strip()
            upsert = self.upsert_var.get()

            client: Client = create_client(url, key)

            total = len(self.discovered_files)
            success_count = 0
            fail_count = 0

            tree_items = self.files_tree.get_children()

            for index, ((_, local_path, remote_path), item_id) in enumerate(zip(self.discovered_files, tree_items), start=1):
                try:
                    self._set_tree_status(item_id, "Enviando")

                    with open(local_path, "rb") as file_data:
                        content = file_data.read()

                    content_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"

                    client.storage.from_(bucket).upload(
                        path=remote_path,
                        file=content,
                        file_options={
                            "content-type": content_type,
                            "upsert": str(upsert).lower(),
                        },
                    )

                    success_count += 1
                    self._set_tree_status(item_id, "Sucesso")
                    self._log(f"OK    | {local_path} -> {bucket}/{remote_path}")

                except Exception as error:
                    fail_count += 1
                    self._set_tree_status(item_id, "Falhou")
                    self._log(f"ERRO  | {local_path} -> {bucket}/{remote_path} | {error}")

                progress_percent = (index / total) * 100 if total else 0
                self._set_progress(progress_percent, index, total)

            self.summary_var.set(
                f"Upload finalizado. Sucessos: {success_count} | Falhas: {fail_count} | Total: {total}"
            )
            self._log("Upload finalizado.")
            self._log(f"Resumo -> Sucessos: {success_count}, Falhas: {fail_count}, Total: {total}")

        except Exception as error:
            self.summary_var.set("Falha ao iniciar upload. Verifique os dados do Supabase.")
            self._log(f"Erro geral no upload: {error}")

        finally:
            self.is_uploading = False
            self.root.after(0, lambda: self.upload_button.config(state="normal"))

    def _normalize_base_path(self, base_path: str) -> str:
        return base_path.strip().strip("/")

    def _set_progress(self, percent: float, current: int, total: int) -> None:
        self.root.after(0, lambda: self.progress_var.set(percent))
        self.root.after(0, lambda: self.progress_label.config(text=f"{current} / {total}"))

    def _set_tree_status(self, item_id: str, status: str) -> None:
        def update() -> None:
            values = list(self.files_tree.item(item_id, "values"))
            if len(values) == 4:
                values[3] = status
                self.files_tree.item(item_id, values=values)

        self.root.after(0, update)

    def _log(self, message: str) -> None:
        self.log_queue.put(message)

    def _poll_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, message + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._poll_log_queue)


def main() -> None:
    root = tk.Tk()
    SupabaseFolderUploaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
