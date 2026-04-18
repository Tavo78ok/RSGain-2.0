#!/usr/bin/env python3
"""
RSGain GUI — GTK4 + libadwaita
Normalizador de volumen musical con ReplayGain 2.0
v1.1.1 — Fix: tema oscuro y CSS para GTK 4.14+
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, GLib, Gio, GObject, Gdk

import sys, os, shutil, subprocess, threading, json
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
APP_ID      = "io.github.Tavo78ok.RsgainGui"
APP_VERSION = "1.1.1"
CONFIG_DIR  = Path(GLib.get_user_config_dir()) / "rsgain-gui"
CONFIG_FILE = CONFIG_DIR / "config.json"

SUPPORTED_EXT = {
    ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac",
    ".wv", ".ape", ".mp4", ".mpc", ".wav", ".aiff", ".aif",
}
FORMAT_LABELS = {
    ".mp3": "MP3", ".flac": "FLAC", ".ogg": "OGG",  ".opus": "OPUS",
    ".m4a": "M4A", ".aac": "AAC",  ".wv":  "WV",   ".ape":  "APE",
    ".wav": "WAV", ".aiff":"AIFF", ".aif": "AIFF",
}

DEFAULT_PROFILE = {
    "mode": 0, "lufs": -18.0, "peak": -1.0,
    "clip": True, "dry": False,
}
DEFAULT_CONFIG = {
    "default_folder": str(Path.home() / "Music"),
    "on_finish":  "toast",
    "threads":    0,
    "tag_format": "auto",
    "theme":      "system",
    "profiles":   {"Por defecto": DEFAULT_PROFILE.copy()},
    "last_profile": "Por defecto",
}

# ── CSS: sin alpha() ni variables de color que pueden fallar en GTK 4.14+ ──
CSS = """
.format-badge {
    border-radius: 6px;
    padding: 1px 7px;
    font-size: 9px;
    font-weight: bold;
}
.log-view {
    font-size: 12px;
}
.run-button {
    font-weight: bold;
}
"""


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────
class Config:
    def __init__(self):
        self._data = {}
        self.load()

    def load(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data = {**DEFAULT_CONFIG, **loaded}
                if "profiles" not in self._data:
                    self._data["profiles"] = DEFAULT_CONFIG["profiles"].copy()
            else:
                self._data = json.loads(json.dumps(DEFAULT_CONFIG))
        except Exception:
            self._data = json.loads(json.dumps(DEFAULT_CONFIG))

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[config] Error al guardar: {e}")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    @property
    def profiles(self):
        return self._data.setdefault("profiles", {})

    def profile_names(self):
        return list(self.profiles.keys())

    def get_profile(self, name):
        return {**DEFAULT_PROFILE, **self.profiles.get(name, {})}

    def save_profile(self, name, data):
        self._data["profiles"][name] = data
        self._data["last_profile"]   = name
        self.save()

    def delete_profile(self, name):
        if name in self._data["profiles"] and len(self._data["profiles"]) > 1:
            del self._data["profiles"][name]
            self._data["last_profile"] = next(iter(self._data["profiles"]))
            self.save()
            return True
        return False

    @property
    def last_profile(self):
        lp = self._data.get("last_profile", "")
        if lp not in self.profiles:
            lp = next(iter(self.profiles), "")
        return lp

    @last_profile.setter
    def last_profile(self, name):
        self._data["last_profile"] = name
        self.save()


# ─────────────────────────────────────────────────────────────────────────────
#  MODELO
# ─────────────────────────────────────────────────────────────────────────────
class AudioItem(GObject.Object):
    __gtype_name__ = "AudioItem"

    def __init__(self, path, is_folder):
        super().__init__()
        self.path      = path
        self.is_folder = is_folder
        self.name      = Path(path).name
        self.ext       = Path(path).suffix.lower()
        self.done      = False
        self.success   = False


# ─────────────────────────────────────────────────────────────────────────────
#  WORKER
# ─────────────────────────────────────────────────────────────────────────────
class Worker:
    def __init__(self, items, target_lufs, true_peak, clip_prevention,
                 album_mode, dry_run, threads, tag_format,
                 on_log, on_progress, on_file_done, on_finished):
        self.items           = items
        self.target_lufs     = target_lufs
        self.true_peak       = true_peak
        self.clip_prevention = clip_prevention
        self.album_mode      = album_mode
        self.dry_run         = dry_run
        self.threads         = threads
        self.tag_format      = tag_format
        self.on_log          = on_log
        self.on_progress     = on_progress
        self.on_file_done    = on_file_done
        self.on_finished     = on_finished
        self._stop           = False

    def stop(self): self._stop = True

    def _emit_log(self, msg, level="info"):
        GLib.idle_add(self.on_log, msg, level)

    def _emit_progress(self, cur, total):
        GLib.idle_add(self.on_progress, cur, total)

    def _emit_file_done(self, path, ok):
        GLib.idle_add(self.on_file_done, path, ok)

    def _emit_finished(self, ok):
        GLib.idle_add(self.on_finished, ok)

    def run(self):
        if not shutil.which("rsgain"):
            self._emit_log("rsgain no está en PATH. Instálalo: sudo apt install rsgain", "error")
            self._emit_finished(False)
            return

        folders = [p for p, f in self.items if f]
        files   = [p for p, f in self.items if not f]

        if self.album_mode and folders:
            items_to_process = [(p, True) for p in folders] + [(p, False) for p in files]
            total = len(items_to_process); done = 0; all_ok = True
            for path, is_folder in items_to_process:
                if self._stop: break
                if is_folder:
                    self._emit_log(f"Carpeta: {path}", "info")
                    ok = self._run_easy(path)
                else:
                    self._emit_log(f"Archivo: {Path(path).name}", "info")
                    ok = self._run_single(path)
                if not ok: all_ok = False
                done += 1
                self._emit_progress(done, total)
                self._emit_file_done(path, ok)
        else:
            all_audio = list(files)
            for path in folders:
                for ext in SUPPORTED_EXT:
                    all_audio += [str(x) for x in Path(path).rglob(f"*{ext}")]
            total = len(all_audio); done = 0; all_ok = True
            for path in all_audio:
                if self._stop: break
                self._emit_log(f"    {Path(path).name}", "info")
                ok = self._run_single(path)
                if not ok: all_ok = False
                done += 1
                self._emit_progress(done, total)
                self._emit_file_done(path, ok)

        if self._stop:
            self._emit_log("Procesamiento cancelado.", "warn")
            self._emit_finished(False)
        else:
            self._emit_finished(all_ok)

    def _extra_args(self):
        args = ["-l", str(self.target_lufs)]
        if self.true_peak != -1.0:
            args += ["-t", str(self.true_peak)]
        if self.clip_prevention:
            args += ["-c", "a"]
        if self.dry_run:
            args += ["-s", "s"]
        if self.threads > 0:
            args += ["-j", str(self.threads)]
        if self.tag_format != "auto":
            args += ["-O", self.tag_format]
        return args

    def _run_easy(self, folder):
        extra = ["-l", str(self.target_lufs)]
        if self.dry_run: extra += ["-s", "s"]
        if self.threads > 0: extra += ["-j", str(self.threads)]
        return self._exec(["rsgain", "easy"] + extra + [folder])

    def _run_single(self, fpath):
        return self._exec(["rsgain", "custom"] + self._extra_args() + [fpath])

    def _exec(self, cmd):
        self._emit_log("$ " + " ".join(cmd), "cmd")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            for line in (r.stdout + r.stderr).splitlines():
                if line.strip():
                    self._emit_log("  " + line, "out" if r.returncode == 0 else "error")
            return r.returncode == 0
        except Exception as e:
            self._emit_log(f"  Error: {e}", "error")
            return False


# ─────────────────────────────────────────────────────────────────────────────
#  VENTANA DE PREFERENCIAS
# ─────────────────────────────────────────────────────────────────────────────
class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, config, on_theme_changed):
        super().__init__()
        self.set_title("Preferencias")
        self.set_search_enabled(True)
        self._config = config
        self._on_theme_changed = on_theme_changed
        self._build_general_page()
        self._build_processing_page()
        self._build_appearance_page()

    def _build_general_page(self):
        page = Adw.PreferencesPage()
        page.set_title("General")
        page.set_icon_name("preferences-system-symbolic")
        self.add(page)

        folder_group = Adw.PreferencesGroup()
        folder_group.set_title("Carpetas")
        folder_group.set_description("El diálogo de archivos abrirá aquí por defecto")

        self.folder_row = Adw.ActionRow()
        self.folder_row.set_title("Carpeta de música")
        self.folder_row.set_subtitle(
            self._config.get("default_folder", str(Path.home() / "Music"))
        )
        btn = Gtk.Button()
        btn.set_icon_name("folder-open-symbolic")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", self._on_choose_folder)
        self.folder_row.add_suffix(btn)
        folder_group.add(self.folder_row)
        page.add(folder_group)

        finish_group = Adw.PreferencesGroup()
        finish_group.set_title("Al terminar el proceso")
        self.finish_row = Adw.ComboRow()
        self.finish_row.set_title("Notificación")
        self.finish_row.set_model(Gtk.StringList.new([
            "Toast en la ventana", "Notificación del sistema", "Nada",
        ]))
        self.finish_row.set_selected(
            {"toast": 0, "notify": 1, "nothing": 2}.get(
                self._config.get("on_finish", "toast"), 0
            )
        )
        self.finish_row.connect("notify::selected", self._on_finish_changed)
        finish_group.add(self.finish_row)
        page.add(finish_group)

    def _build_processing_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Procesamiento")
        page.set_icon_name("media-playback-start-symbolic")
        self.add(page)

        perf_group = Adw.PreferencesGroup()
        perf_group.set_title("Rendimiento")
        self.threads_row = Adw.SpinRow()
        self.threads_row.set_adjustment(Gtk.Adjustment(
            value=self._config.get("threads", 0),
            lower=0, upper=32, step_increment=1, page_increment=4
        ))
        self.threads_row.set_title("Hilos de procesamiento")
        self.threads_row.set_subtitle("0 = automático (recomendado)")
        self.threads_row.set_digits(0)
        self.threads_row.connect("notify::value", self._on_threads_changed)
        perf_group.add(self.threads_row)
        page.add(perf_group)

        tag_group = Adw.PreferencesGroup()
        tag_group.set_title("Formato de etiquetas")
        self.tag_row = Adw.ComboRow()
        self.tag_row.set_title("Formato de etiqueta")
        self.tag_row.set_model(Gtk.StringList.new([
            "Automático (recomendado)",
            "ID3v2 — MP3",
            "Vorbis Comment — FLAC / OGG",
            "APEv2 — WV / APE / MPC",
        ]))
        self.tag_row.set_selected(
            {"auto": 0, "id3v2": 1, "vorbis": 2, "ape": 3}.get(
                self._config.get("tag_format", "auto"), 0
            )
        )
        self.tag_row.connect("notify::selected", self._on_tag_changed)
        tag_group.add(self.tag_row)
        page.add(tag_group)

    def _build_appearance_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Apariencia")
        page.set_icon_name("applications-graphics-symbolic")
        self.add(page)

        theme_group = Adw.PreferencesGroup()
        theme_group.set_title("Tema de color")
        self.theme_row = Adw.ComboRow()
        self.theme_row.set_title("Tema")
        self.theme_row.set_subtitle("Anula el tema del sistema si lo deseas")
        self.theme_row.set_model(Gtk.StringList.new([
            "Seguir el sistema", "Claro", "Oscuro",
        ]))
        self.theme_row.set_selected(
            {"system": 0, "light": 1, "dark": 2}.get(
                self._config.get("theme", "system"), 0
            )
        )
        self.theme_row.connect("notify::selected", self._on_theme_row_changed)
        theme_group.add(self.theme_row)
        page.add(theme_group)

    def _on_choose_folder(self, btn):
        dialog = Gtk.FileDialog()
        dialog.set_title("Seleccionar carpeta de música por defecto")
        dialog.select_folder(None, None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog, result):
        try:
            gfile = dialog.select_folder_finish(result)
            if gfile:
                path = gfile.get_path()
                self.folder_row.set_subtitle(path)
                self._config.set("default_folder", path)
        except GLib.Error:
            pass

    def _on_finish_changed(self, row, _):
        self._config.set("on_finish", ["toast", "notify", "nothing"][row.get_selected()])

    def _on_threads_changed(self, row, _):
        self._config.set("threads", int(row.get_value()))

    def _on_tag_changed(self, row, _):
        self._config.set("tag_format", ["auto", "id3v2", "vorbis", "ape"][row.get_selected()])

    def _on_theme_row_changed(self, row, _):
        theme = ["system", "light", "dark"][row.get_selected()]
        self._config.set("theme", theme)
        self._on_theme_changed(theme)


# ─────────────────────────────────────────────────────────────────────────────
#  DIÁLOGO GUARDAR PERFIL
# ─────────────────────────────────────────────────────────────────────────────
class SaveProfileDialog(Adw.MessageDialog):
    def __init__(self, parent, current_name=""):
        super().__init__(transient_for=parent)
        self.set_heading("Guardar perfil")
        self.set_body("Escribe un nombre para este perfil de ajustes:")
        self.entry = Gtk.Entry()
        self.entry.set_text(current_name)
        self.entry.set_placeholder_text("Nombre del perfil")
        self.entry.set_margin_top(8)
        self.entry.set_activates_default(True)
        self.set_extra_child(self.entry)
        self.add_response("cancel", "Cancelar")
        self.add_response("save",   "Guardar")
        self.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response("save")

    def get_name(self):
        return self.entry.get_text().strip()


# ─────────────────────────────────────────────────────────────────────────────
#  VENTANA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app, config):
        super().__init__(application=app)
        self.set_title("RSGain")
        self.set_default_size(900, 660)
        self.set_size_request(640, 500)

        self._config  = config
        self._items   = []
        self._worker  = None
        self._thread  = None
        self._running = False

        self._build_ui()
        self._load_profile(config.last_profile)
        self._check_rsgain()

        # CORREGIDO: aplicar tema DESPUÉS de que la ventana esté construida
        GLib.idle_add(self._apply_theme_from_config)

    def _apply_theme_from_config(self):
        self._apply_theme(self._config.get("theme", "system"))
        return False  # no repetir

    # ── Tema ───────────────────────────────────────────────────────────────────
    def _apply_theme(self, theme):
        try:
            manager = Adw.StyleManager.get_default()
            if manager is None:
                return
            scheme = {
                "system": Adw.ColorScheme.DEFAULT,
                "light":  Adw.ColorScheme.FORCE_LIGHT,
                "dark":   Adw.ColorScheme.FORCE_DARK,
            }.get(theme, Adw.ColorScheme.DEFAULT)
            manager.set_color_scheme(scheme)
        except Exception as e:
            print(f"[theme] No se pudo aplicar el tema '{theme}': {e}")

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        # HeaderBar
        header = Adw.HeaderBar()

        add_btn = Gtk.Button()
        add_btn.set_icon_name("list-add-symbolic")
        add_btn.set_tooltip_text("Añadir archivos")
        add_btn.connect("clicked", self._on_add_clicked)
        header.pack_start(add_btn)

        folder_btn = Gtk.Button()
        folder_btn.set_icon_name("folder-open-symbolic")
        folder_btn.set_tooltip_text("Añadir carpeta")
        folder_btn.connect("clicked", self._on_add_folder_clicked)
        header.pack_start(folder_btn)

        # Selector de perfil en el centro
        profile_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        profile_box.set_valign(Gtk.Align.CENTER)

        lbl = Gtk.Label(label="Perfil:")
        lbl.add_css_class("dim-label")
        lbl.add_css_class("caption")
        profile_box.append(lbl)

        self.profile_combo = Gtk.DropDown()
        self.profile_combo.set_tooltip_text("Perfil activo")
        self._refresh_profile_model()
        self.profile_combo.connect("notify::selected", self._on_profile_selected)
        profile_box.append(self.profile_combo)

        save_btn = Gtk.Button()
        save_btn.set_icon_name("document-save-symbolic")
        save_btn.set_tooltip_text("Guardar ajustes como perfil")
        save_btn.connect("clicked", self._on_save_profile)
        profile_box.append(save_btn)

        self.del_profile_btn = Gtk.Button()
        self.del_profile_btn.set_icon_name("edit-delete-symbolic")
        self.del_profile_btn.set_tooltip_text("Eliminar perfil")
        self.del_profile_btn.add_css_class("destructive-action")
        self.del_profile_btn.connect("clicked", self._on_delete_profile)
        self.del_profile_btn.set_sensitive(len(self._config.profile_names()) > 1)
        profile_box.append(self.del_profile_btn)

        header.set_title_widget(profile_box)

        prefs_btn = Gtk.Button()
        prefs_btn.set_icon_name("preferences-system-symbolic")
        prefs_btn.set_tooltip_text("Preferencias")
        prefs_btn.connect("clicked", self._on_open_prefs)
        header.pack_end(prefs_btn)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_menu_model(self._build_menu())
        header.pack_end(menu_btn)

        toolbar_view.add_top_bar(header)

        # Banner
        self.rsgain_banner = Adw.Banner()
        self.rsgain_banner.set_title("rsgain no está instalado")
        self.rsgain_banner.set_button_label("Cómo instalar")
        self.rsgain_banner.connect("button-clicked", self._on_install_help)
        self.rsgain_banner.set_revealed(False)
        toolbar_view.add_top_bar(self.rsgain_banner)

        # Cuerpo
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        toolbar_view.set_content(hbox)
        hbox.append(self._build_left_panel())
        hbox.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        hbox.append(self._build_right_panel())

        toolbar_view.add_bottom_bar(self._build_bottom_bar())

    # ── Panel izquierdo ────────────────────────────────────────────────────────
    def _build_left_panel(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_hexpand(True)
        box.set_size_request(360, -1)

        self.empty_page = Adw.StatusPage()
        self.empty_page.set_icon_name("audio-x-generic-symbolic")
        self.empty_page.set_title("Sin archivos")
        self.empty_page.set_description("Arrastra archivos de audio\no carpetas de música")
        self.empty_page.set_vexpand(True)
        self.empty_page.add_css_class("compact")

        empty_btn = Gtk.Button(label="Añadir archivos…")
        empty_btn.add_css_class("suggested-action")
        empty_btn.add_css_class("pill")
        empty_btn.set_halign(Gtk.Align.CENTER)
        empty_btn.connect("clicked", self._on_add_clicked)
        self.empty_page.set_child(empty_btn)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.set_margin_top(8)
        self.list_box.set_margin_bottom(8)
        self.list_box.set_margin_start(12)
        self.list_box.set_margin_end(12)
        scroll.set_child(self.list_box)

        self.list_stack = Gtk.Stack()
        self.list_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.list_stack.set_vexpand(True)
        self.list_stack.add_named(self.empty_page, "empty")
        self.list_stack.add_named(scroll, "list")
        self.list_stack.set_visible_child_name("empty")
        box.append(self.list_stack)

        action_bar = Gtk.ActionBar()
        self.count_label = Gtk.Label(label="0 elementos")
        self.count_label.add_css_class("caption")
        self.count_label.add_css_class("dim-label")
        action_bar.pack_start(self.count_label)

        btn_clear = Gtk.Button()
        btn_clear.set_icon_name("edit-clear-all-symbolic")
        btn_clear.set_tooltip_text("Limpiar lista")
        btn_clear.connect("clicked", self._on_clear_clicked)
        action_bar.pack_end(btn_clear)

        self.btn_remove = Gtk.Button()
        self.btn_remove.set_icon_name("list-remove-symbolic")
        self.btn_remove.set_tooltip_text("Quitar selección")
        self.btn_remove.set_sensitive(False)
        self.btn_remove.connect("clicked", self._on_remove_clicked)
        action_bar.pack_end(self.btn_remove)

        self.list_box.connect(
            "selected-rows-changed",
            lambda lb: self.btn_remove.set_sensitive(bool(lb.get_selected_rows()))
        )
        box.append(action_bar)

        dnd = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        dnd.connect("drop", self._on_drop_files)
        box.add_controller(dnd)

        return box

    # ── Panel derecho ──────────────────────────────────────────────────────────
    def _build_right_panel(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_size_request(320, -1)

        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        self.view_stack.add_titled_with_icon(
            self._build_settings_page(), "settings",
            "Ajustes", "preferences-system-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self._build_log_page(), "log",
            "Registro", "utilities-terminal-symbolic"
        )

        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.view_stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)

        box.append(switcher)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        box.append(self.view_stack)
        return box

    # ── Ajustes ────────────────────────────────────────────────────────────────
    def _build_settings_page(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(380)
        clamp.set_margin_top(16)
        clamp.set_margin_bottom(16)
        clamp.set_margin_start(12)
        clamp.set_margin_end(12)
        scroll.set_child(clamp)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(vbox)

        mode_group = Adw.PreferencesGroup()
        mode_group.set_title("Modo de procesamiento")
        self.mode_row = Adw.ComboRow()
        self.mode_row.set_title("Algoritmo")
        self.mode_row.set_subtitle("Cómo se agrupan y analizan las pistas")
        self.mode_row.set_model(Gtk.StringList.new([
            "Easy — Detección automática de álbumes",
            "Track — Pista por pista",
        ]))
        self.mode_row.set_selected(0)
        mode_group.add(self.mode_row)
        vbox.append(mode_group)

        vol_group = Adw.PreferencesGroup()
        vol_group.set_title("Nivel de volumen")

        preset_row = Adw.ActionRow()
        preset_row.set_title("Presets")
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        preset_box.set_valign(Gtk.Align.CENTER)
        self.preset_buttons = []
        for label, val, tip in [
            ("EBU",    -23.0, "EBU R128 — Broadcast"),
            ("rsgain", -18.0, "Estándar por defecto"),
            ("Stream", -14.0, "Spotify / Apple Music"),
        ]:
            b = Gtk.ToggleButton(label=label)
            b.set_tooltip_text(f"{tip} · {val} LUFS")
            b.connect("toggled", self._on_preset_toggled, val)
            preset_box.append(b)
            self.preset_buttons.append((b, val))
        preset_row.add_suffix(preset_box)
        vol_group.add(preset_row)

        self.lufs_row = Adw.SpinRow()
        self.lufs_row.set_adjustment(Gtk.Adjustment(
            value=-18.0, lower=-30.0, upper=-5.0,
            step_increment=0.5, page_increment=1.0
        ))
        self.lufs_row.set_title("Volumen objetivo")
        self.lufs_row.set_subtitle("LUFS")
        self.lufs_row.set_digits(1)
        self.lufs_row.connect("notify::value", self._on_lufs_changed)
        vol_group.add(self.lufs_row)

        self.peak_row = Adw.SpinRow()
        self.peak_row.set_adjustment(Gtk.Adjustment(
            value=-1.0, lower=-9.0, upper=0.0,
            step_increment=0.5, page_increment=1.0
        ))
        self.peak_row.set_title("True Peak límite")
        self.peak_row.set_subtitle("dBTP")
        self.peak_row.set_digits(1)
        vol_group.add(self.peak_row)
        vbox.append(vol_group)

        opts_group = Adw.PreferencesGroup()
        opts_group.set_title("Opciones")

        self.clip_row = Adw.SwitchRow()
        self.clip_row.set_title("Prevención de clipping")
        self.clip_row.set_subtitle("Reduce la ganancia si supera el true peak")
        self.clip_row.set_active(True)
        opts_group.add(self.clip_row)

        self.dry_row = Adw.SwitchRow()
        self.dry_row.set_title("Solo análisis")
        self.dry_row.set_subtitle("Escanea sin modificar los archivos")
        opts_group.add(self.dry_row)

        vbox.append(opts_group)
        return scroll

    # ── Log ────────────────────────────────────────────────────────────────────
    def _build_log_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_vexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.log_buffer = Gtk.TextBuffer()
        for tag, color in [
            ("info",  "#888888"), ("ok",    "#57c75e"),
            ("warn",  "#e5a50a"), ("error", "#e05c5c"),
            ("cmd",   "#729fcf"), ("out",   "#aaaaaa"),
        ]:
            self.log_buffer.create_tag(tag, foreground=color)

        self.log_view = Gtk.TextView(buffer=self.log_buffer)
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.add_css_class("log-view")
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_margin_start(8)
        self.log_view.set_margin_end(8)
        self.log_view.set_margin_top(8)
        scroll.set_child(self.log_view)
        box.append(scroll)

        log_action = Gtk.ActionBar()
        btn_clear_log = Gtk.Button()
        btn_clear_log.set_icon_name("edit-clear-symbolic")
        btn_clear_log.set_tooltip_text("Limpiar registro")
        btn_clear_log.connect("clicked", lambda _: self.log_buffer.set_text(""))
        log_action.pack_end(btn_clear_log)
        box.append(log_action)
        return box

    # ── Barra inferior ─────────────────────────────────────────────────────────
    def _build_bottom_bar(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        inner = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12, margin_start=16, margin_end=16,
            margin_top=10, margin_bottom=10,
        )
        box.append(inner)

        prog_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        prog_box.set_hexpand(True)

        self.progress_label = Gtk.Label(label="Listo")
        self.progress_label.set_halign(Gtk.Align.START)
        self.progress_label.add_css_class("caption")
        self.progress_label.add_css_class("dim-label")
        prog_box.append(self.progress_label)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_show_text(False)
        prog_box.append(self.progress_bar)
        inner.append(prog_box)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.btn_stop = Gtk.Button()
        self.btn_stop.set_icon_name("media-playback-stop-symbolic")
        self.btn_stop.set_tooltip_text("Detener")
        self.btn_stop.add_css_class("destructive-action")
        self.btn_stop.set_sensitive(False)
        self.btn_stop.connect("clicked", self._on_stop)
        btn_box.append(self.btn_stop)

        self.btn_run = Gtk.Button(label="Procesar")
        self.btn_run.add_css_class("suggested-action")
        self.btn_run.add_css_class("run-button")
        self.btn_run.connect("clicked", self._on_run)
        btn_box.append(self.btn_run)

        inner.append(btn_box)
        return box

    def _build_menu(self):
        menu = Gio.Menu()
        menu.append("Preferencias",     "app.preferences")
        menu.append("Acerca de RSGain", "app.about")
        return menu

    # ── Perfiles ───────────────────────────────────────────────────────────────
    def _refresh_profile_model(self):
        names = self._config.profile_names()
        self.profile_combo.set_model(Gtk.StringList.new(names))
        last = self._config.last_profile
        idx  = names.index(last) if last in names else 0
        self.profile_combo.set_selected(idx)

    def _load_profile(self, name):
        if not name: return
        p = self._config.get_profile(name)
        self.mode_row.set_selected(p.get("mode", 0))
        self.lufs_row.set_value(p.get("lufs", -18.0))
        self.peak_row.set_value(p.get("peak", -1.0))
        self.clip_row.set_active(p.get("clip", True))
        self.dry_row.set_active(p.get("dry", False))
        self._sync_preset_buttons(p.get("lufs", -18.0))

    def _current_settings(self):
        return {
            "mode": self.mode_row.get_selected(),
            "lufs": self.lufs_row.get_value(),
            "peak": self.peak_row.get_value(),
            "clip": self.clip_row.get_active(),
            "dry":  self.dry_row.get_active(),
        }

    def _on_profile_selected(self, combo, _):
        model = combo.get_model()
        idx   = combo.get_selected()
        if model and idx < model.get_n_items():
            name = model.get_item(idx).get_string()
            self._load_profile(name)
            self._config.last_profile = name
            self.del_profile_btn.set_sensitive(len(self._config.profile_names()) > 1)

    def _on_save_profile(self, *_):
        dialog = SaveProfileDialog(self, self._config.last_profile)
        dialog.connect("response", self._on_save_profile_response)
        dialog.present()

    def _on_save_profile_response(self, dialog, response):
        if response == "save":
            name = dialog.get_name()
            if name:
                self._config.save_profile(name, self._current_settings())
                self._refresh_profile_model()
                self._toast(f"Perfil «{name}» guardado")
        dialog.close()

    def _on_delete_profile(self, *_):
        name    = self._config.last_profile
        confirm = Adw.MessageDialog(transient_for=self)
        confirm.set_heading("¿Eliminar perfil?")
        confirm.set_body(f"Se eliminará el perfil «{name}».")
        confirm.add_response("cancel", "Cancelar")
        confirm.add_response("delete", "Eliminar")
        confirm.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        confirm.set_default_response("cancel")
        confirm.connect("response", self._on_delete_confirmed, name)
        confirm.present()

    def _on_delete_confirmed(self, dialog, response, name):
        if response == "delete":
            if self._config.delete_profile(name):
                self._refresh_profile_model()
                self._load_profile(self._config.last_profile)
                self._toast(f"Perfil «{name}» eliminado")
        dialog.close()

    # ── Preferencias ───────────────────────────────────────────────────────────
    def _on_open_prefs(self, *_):
        PreferencesDialog(self._config, self._apply_theme).present(self)

    # ── Archivos ───────────────────────────────────────────────────────────────
    def _on_add_clicked(self, *_):
        dialog = Gtk.FileDialog()
        dialog.set_title("Añadir archivos de audio")
        default = self._config.get("default_folder")
        if default and Path(default).exists():
            dialog.set_initial_folder(Gio.File.new_for_path(default))
        f = Gtk.FileFilter()
        f.set_name("Archivos de audio")
        for ext in SUPPORTED_EXT:
            f.add_pattern(f"*{ext}")
            f.add_pattern(f"*{ext.upper()}")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dialog.set_filters(store)
        dialog.set_default_filter(f)
        dialog.open_multiple(self, None, self._on_files_chosen)

    def _on_add_folder_clicked(self, *_):
        dialog = Gtk.FileDialog()
        dialog.set_title("Seleccionar carpeta de música")
        default = self._config.get("default_folder")
        if default and Path(default).exists():
            dialog.set_initial_folder(Gio.File.new_for_path(default))
        dialog.select_folder(self, None, self._on_folder_chosen)

    def _on_files_chosen(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
            for i in range(files.get_n_items()):
                gfile = files.get_item(i)
                path  = gfile.get_path()
                if path and Path(path).suffix.lower() in SUPPORTED_EXT:
                    self._add_item(path, False)
        except GLib.Error:
            pass

    def _on_folder_chosen(self, dialog, result):
        try:
            gfile = dialog.select_folder_finish(result)
            if gfile:
                path = gfile.get_path()
                if path: self._add_item(path, True)
        except GLib.Error:
            pass

    def _on_drop_files(self, target, value, x, y):
        if isinstance(value, Gdk.FileList):
            for gfile in value.get_files():
                path = gfile.get_path()
                if path:
                    if os.path.isdir(path):
                        self._add_item(path, True)
                    elif Path(path).suffix.lower() in SUPPORTED_EXT:
                        self._add_item(path, False)
        return True

    def _add_item(self, path, is_folder):
        if any(it.path == path for it in self._items): return
        item = AudioItem(path, is_folder)
        self._items.append(item)
        self.list_box.append(self._make_row(item))
        self._update_state()

    def _make_row(self, item):
        row = Adw.ActionRow()
        row.set_title(item.name)
        row.set_subtitle(item.path)
        row.set_subtitle_lines(1)
        row.set_use_markup(False)

        icon = Gtk.Image.new_from_icon_name(
            "folder-music-symbolic" if item.is_folder else "audio-x-generic-symbolic"
        )
        row.add_prefix(icon)

        if not item.is_folder and item.ext in FORMAT_LABELS:
            badge = Gtk.Label(label=FORMAT_LABELS[item.ext])
            badge.add_css_class("format-badge")
            badge.set_valign(Gtk.Align.CENTER)
            row.add_suffix(badge)

        status_icon = Gtk.Image.new_from_icon_name("content-loading-symbolic")
        status_icon.set_pixel_size(16)
        status_icon.set_visible(False)
        status_icon.set_valign(Gtk.Align.CENTER)
        row.add_suffix(status_icon)
        row._status_icon = status_icon
        row._item = item
        return row

    def _on_remove_clicked(self, *_):
        for row in self.list_box.get_selected_rows():
            self._items = [it for it in self._items if it.path != row._item.path]
            self.list_box.remove(row)
        self._update_state()

    def _on_clear_clicked(self, *_):
        self._items.clear()
        child = self.list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.list_box.remove(child)
            child = nxt
        self._update_state()

    def _update_state(self):
        n       = len(self._items)
        folders = sum(1 for it in self._items if it.is_folder)
        files   = n - folders
        parts   = []
        if folders: parts.append(f"{folders} carpeta{'s' if folders > 1 else ''}")
        if files:   parts.append(f"{files} archivo{'s' if files > 1 else ''}")
        self.count_label.set_label(", ".join(parts) if parts else "0 elementos")
        self.list_stack.set_visible_child_name("list" if n else "empty")

    # ── Presets ────────────────────────────────────────────────────────────────
    def _on_preset_toggled(self, btn, val):
        if btn.get_active():
            self.lufs_row.set_value(val)
            for b, v in self.preset_buttons:
                if v != val:
                    b.handler_block_by_func(self._on_preset_toggled)
                    b.set_active(False)
                    b.handler_unblock_by_func(self._on_preset_toggled)

    def _on_lufs_changed(self, row, _):
        self._sync_preset_buttons(row.get_value())

    def _sync_preset_buttons(self, val):
        for b, v in self.preset_buttons:
            b.handler_block_by_func(self._on_preset_toggled)
            b.set_active(abs(v - val) < 0.01)
            b.handler_unblock_by_func(self._on_preset_toggled)

    # ── rsgain ─────────────────────────────────────────────────────────────────
    def _check_rsgain(self):
        if shutil.which("rsgain"):
            try:
                r = subprocess.run(
                    ["rsgain", "--version"],
                    capture_output=True, text=True, timeout=5
                )
                ver = (r.stdout + r.stderr).strip().split("\n")[0]
                self._log(f"✓ {ver or 'rsgain OK'}", "ok")
            except Exception:
                self._log("rsgain detectado", "ok")
        else:
            self.rsgain_banner.set_revealed(True)
            self._log("rsgain no encontrado. sudo apt install rsgain", "error")

    def _on_install_help(self, *_):
        dialog = Adw.MessageDialog(transient_for=self)
        dialog.set_heading("Instalar rsgain")
        dialog.set_body(
            "Ubuntu / Debian:\n  sudo apt install rsgain\n\n"
            "Arch Linux:\n  pacman -S rsgain\n\n"
            "Más info: https://github.com/complexlogic/rsgain"
        )
        dialog.add_response("close", "Cerrar")
        dialog.set_default_response("close")
        dialog.present()

    # ── Procesamiento ──────────────────────────────────────────────────────────
    def _on_run(self, *_):
        if not self._items:
            self._toast("Añade archivos o carpetas primero"); return
        if not shutil.which("rsgain"):
            self.rsgain_banner.set_revealed(True)
            self._toast("rsgain no está instalado"); return

        self._worker = Worker(
            items=[(it.path, it.is_folder) for it in self._items],
            target_lufs=self.lufs_row.get_value(),
            true_peak=self.peak_row.get_value(),
            clip_prevention=self.clip_row.get_active(),
            album_mode=(self.mode_row.get_selected() == 0),
            dry_run=self.dry_row.get_active(),
            threads=self._config.get("threads", 0),
            tag_format=self._config.get("tag_format", "auto"),
            on_log=self._log,
            on_progress=self._on_progress,
            on_file_done=self._on_file_done,
            on_finished=self._on_finished,
        )
        dry = " · Solo análisis" if self.dry_row.get_active() else ""
        self._log(f"Iniciando — {self.lufs_row.get_value():.1f} LUFS{dry}", "ok")
        self._set_running(True)
        self.progress_bar.set_fraction(0.0)
        self.progress_label.set_label("Procesando…")
        self.view_stack.set_visible_child_name("log")
        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()

    def _on_stop(self, *_):
        if self._worker: self._worker.stop()

    def _set_running(self, running):
        self._running = running
        self.btn_run.set_sensitive(not running)
        self.btn_stop.set_sensitive(running)
        for w in [self.mode_row, self.lufs_row, self.peak_row,
                  self.clip_row, self.dry_row, self.profile_combo]:
            w.set_sensitive(not running)

    def _on_progress(self, cur, total):
        self.progress_bar.set_fraction(cur / total if total else 0)
        self.progress_label.set_label(f"{cur} de {total}")

    def _on_file_done(self, path, ok):
        child = self.list_box.get_first_child()
        while child:
            if hasattr(child, "_item") and child._item.path == path:
                child._item.done = True; child._item.success = ok
                icon = child._status_icon
                icon.set_visible(True)
                icon.set_from_icon_name(
                    "emblem-ok-symbolic" if ok else "dialog-error-symbolic"
                )
                break
            child = child.get_next_sibling()

    def _on_finished(self, all_ok):
        self._set_running(False)
        if all_ok:
            self.progress_bar.set_fraction(1.0)
            self.progress_label.set_label("Completado")
            self._toast("Volumen normalizado correctamente")
        else:
            self.progress_label.set_label("Finalizado con advertencias")
            self._toast("Finalizado con algunos errores")

    def _toast(self, message):
        toast = Adw.Toast(title=message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _log(self, message, level="info"):
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert_with_tags_by_name(end, message + "\n", level)
        adj = self.log_view.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) or False)


# ─────────────────────────────────────────────────────────────────────────────
#  APLICACIÓN
# ─────────────────────────────────────────────────────────────────────────────
class RSGainApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self._config = Config()
        self.connect("activate", self._on_activate)

        for name, cb in [("preferences", self._on_prefs_action),
                         ("about", self._on_about)]:
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)

    def _on_activate(self, app):
        # CSS cargado aquí — display ya disponible
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self.window = MainWindow(app, self._config)
        self.window.present()

    def _on_prefs_action(self, *_):
        PreferencesDialog(
            self._config,
            lambda theme: self.window._apply_theme(theme)
        ).present(self.window)

    def _on_about(self, *_):
        dialog = Adw.AboutDialog()
        dialog.set_application_name("RSGain GUI")
        dialog.set_version(APP_VERSION)
        dialog.set_developer_name("Tavo78ok")
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.set_comments(
            "Interfaz gráfica para rsgain (ReplayGain 2.0).\n"
            "Normaliza el volumen de tu biblioteca musical."
        )
        dialog.set_website("https://github.com/Tavo78ok/rsgain-gui")
        dialog.set_application_icon("audio-x-generic")
        dialog.present(self.window)


def main():
    app = RSGainApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
