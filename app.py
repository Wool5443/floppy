import asyncio
import threading
from pathlib import Path
from typing import Any

import gi

import engine

GTK_VERSION = "4.0"

gi.require_version("Gtk", GTK_VERSION)
gi.require_version("Gdk", GTK_VERSION)

from gi.repository import Gdk, GLib, Gtk # pyright: ignore[reportAttributeAccessIssue] # noqa: E402

APPLICATION_ID = "dev.floppy.Reencoder"
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 420
PAGE_MARGIN = 16
SECTION_SPACING = 12
ROW_SPACING = 8
LEFT_ALIGN = 0
QUALITY_MIN = 1
QUALITY_MAX = 51
QUALITY_STEP = 1
DEFAULT_QUALITY = 30
RESOLUTION_SOURCE_SIZE = 0
RESOLUTION_MAX = 7680
RESOLUTION_STEP = 1
FRAME_RATE_SOURCE = 0
FRAME_RATE_MAX = 240
FRAME_RATE_STEP = 1
TITLE_CSS_CLASS = "title-1"
DIM_LABEL_CSS_CLASS = "dim-label"
PROGRESS_MIN = 0.0
PROGRESS_MAX = 1.0
APP_CSS = """
progressbar progress {
    background: #3584e4;
}
"""


class FloppyApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID)

    def do_activate(self) -> None:
        window = MainWindow(self)
        load_css()
        window.present()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: FloppyApp) -> None:
        super().__init__(application=app, title="Floppy")
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.selected_files: list[Path] = []

        self.set_child(self._build_interface())

    def _on_choose_file(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Choose video",
            self,
            Gtk.FileChooserAction.OPEN,
            "Open",
            "Cancel",
        )
        dialog.set_select_multiple(True)
        dialog.connect("response", self._on_file_selected)
        dialog.show()

    def _on_file_selected(
        self,
        dialog: Gtk.FileChooserNative,
        response: int,
    ) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            self._set_selected_files(self._paths_from_files(dialog.get_files()))

        dialog.destroy()

    def _on_reencode(self, _button: Gtk.Button) -> None:
        if not self.selected_files:
            self.status_label_widget.set_text("Choose files first")
            return

        quality = self.quality_spin_button.get_value_as_int()
        resolution_value = self.resolution_spin_button.get_value_as_int()
        frame_rate_value = self.frame_rate_spin_button.get_value_as_int()
        resolution = None
        frame_rate = None

        if resolution_value != RESOLUTION_SOURCE_SIZE:
            resolution = resolution_value
        if frame_rate_value != FRAME_RATE_SOURCE:
            frame_rate = frame_rate_value

        self._set_progress(PROGRESS_MIN)
        self.status_label_widget.set_text("Encoding...")
        self.reencode_button.set_sensitive(False)
        self.choose_button.set_sensitive(False)

        thread = threading.Thread(
            target=self._reencode_worker,
            args=(self.selected_files.copy(), quality, resolution, frame_rate),
            daemon=True,
        )
        thread.start()

    def _reencode_worker(
        self,
        filenames: list[Path],
        quality: int,
        resolution: int | None,
        frame_rate: float | None,
    ) -> None:
        completed = 0
        total = len(filenames)

        try:
            for filename in filenames:
                GLib.idle_add(self._set_progress, PROGRESS_MIN)
                GLib.idle_add(
                    self.status_label_widget.set_text,
                    f"{completed}/{total} reencoded - Encoding {filename.name}",
                )
                asyncio.run(
                    engine.reencode(
                        filename,
                        quality=quality,
                        resolution=resolution,
                        frame_rate=frame_rate,
                        progress_callback=self._queue_progress,
                    )
                )
                completed += 1
                GLib.idle_add(
                    self.status_label_widget.set_text,
                    f"{completed}/{total} reencoded",
                )
                GLib.idle_add(self._set_progress, PROGRESS_MAX)
        except Exception as error:
            GLib.idle_add(self._finish_reencode, completed, total, str(error))
            return

        GLib.idle_add(self._finish_reencode, completed, total, None)

    def _on_files_dropped(
        self,
        _drop_target: Gtk.DropTarget,
        file_list: Gdk.FileList,
        _x: float,
        _y: float,
    ) -> bool:
        paths = self._paths_from_files(file_list.get_files())
        self._set_selected_files(paths)
        return bool(paths)

    def _paths_from_files(self, files: Any) -> list[Path]:
        if hasattr(files, "get_n_items"):
            files = [files.get_item(index) for index in range(files.get_n_items())]

        return [
            Path(path)
            for file in files
            if file is not None and (path := file.get_path()) is not None
        ]

    def _set_selected_files(self, paths: list[Path]) -> None:
        self.selected_files = paths
        self.status_label_widget.set_text("")

        match len(paths):
            case 0:
                self.file_label_widget.set_text("No files selected")
            case 1:
                self.file_label_widget.set_text(paths[0].name)
            case count:
                self.file_label_widget.set_text(f"{count} files selected")

    def _queue_progress(self, fraction: float) -> None:
        fraction = max(PROGRESS_MIN, min(PROGRESS_MAX, fraction))
        GLib.idle_add(self._set_progress, fraction)

    def _set_progress(self, fraction: float) -> bool:
        self.progress_bar.set_fraction(fraction)
        self.progress_bar.set_text(f"{fraction * 100:0.2f}%")
        return False

    def _finish_reencode(
        self,
        completed: int,
        total: int,
        error: str | None,
    ) -> bool:
        self.reencode_button.set_sensitive(True)
        self.choose_button.set_sensitive(True)

        if error is not None:
            self.status_label_widget.set_text(
                f"Failed after {completed}/{total}: {error}"
            )
            return False

        self._set_progress(PROGRESS_MAX)
        self.status_label_widget.set_text(f"{completed}/{total} reencoded")

        return False

    def _build_interface(self) -> Gtk.Widget:
        root = self._create_root_box()
        root.append(self._create_title_label())
        root.append(self._create_file_row())
        root.append(self._create_drop_hint_label())
        root.append(self._create_quality_row())
        root.append(self._create_resolution_row())
        root.append(self._create_frame_rate_row())
        root.append(self._create_progress_bar())
        root.append(self._create_status_label())
        root.append(self._create_action_row())
        self._add_file_drop_target(root)

        return root

    def _add_file_drop_target(self, widget: Gtk.Widget) -> None:
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_files_dropped)
        widget.add_controller(drop_target)

    def _create_root_box(self) -> Gtk.Box:
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=SECTION_SPACING,
            margin_top=PAGE_MARGIN,
            margin_bottom=PAGE_MARGIN,
            margin_start=PAGE_MARGIN,
            margin_end=PAGE_MARGIN,
        )
        return root

    def _create_title_label(self) -> Gtk.Label:
        title = Gtk.Label(label="HEVC Reencoder")
        title.add_css_class(TITLE_CSS_CLASS)
        title.set_xalign(LEFT_ALIGN)
        return title

    def _create_file_row(self) -> Gtk.Box:
        file_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=ROW_SPACING)
        self.file_label_widget = Gtk.Label(label="No files selected")
        self.file_label_widget.set_hexpand(True)
        self.file_label_widget.set_xalign(LEFT_ALIGN)
        file_row.append(self.file_label_widget)
        self.choose_button = Gtk.Button(label="Choose files")
        self.choose_button.connect("clicked", self._on_choose_file)
        file_row.append(self.choose_button)
        return file_row

    def _create_drop_hint_label(self) -> Gtk.Label:
        hint_label = Gtk.Label(label="Drag video files here or choose files")
        hint_label.add_css_class(DIM_LABEL_CSS_CLASS)
        hint_label.set_xalign(LEFT_ALIGN)
        return hint_label

    def _create_quality_row(self) -> Gtk.Box:
        quality_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        quality_row.append(Gtk.Label(label="Quality"))
        self.quality_spin_button = Gtk.SpinButton.new_with_range(
            QUALITY_MIN,
            QUALITY_MAX,
            QUALITY_STEP,
        )
        self.quality_spin_button.set_value(DEFAULT_QUALITY)
        quality_row.append(self.quality_spin_button)
        return quality_row

    def _create_resolution_row(self) -> Gtk.Box:
        resolution_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        resolution_row.append(Gtk.Label(label="Resolution"))
        self.resolution_spin_button = Gtk.SpinButton.new_with_range(
            RESOLUTION_SOURCE_SIZE,
            RESOLUTION_MAX,
            RESOLUTION_STEP,
        )
        self.resolution_spin_button.set_value(RESOLUTION_SOURCE_SIZE)
        resolution_row.append(self.resolution_spin_button)
        resolution_row.append(
            Gtk.Label(label=f"{RESOLUTION_SOURCE_SIZE} keeps source size")
        )
        return resolution_row

    def _create_frame_rate_row(self) -> Gtk.Box:
        frame_rate_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        frame_rate_row.append(Gtk.Label(label="Frame rate"))
        self.frame_rate_spin_button = Gtk.SpinButton.new_with_range(
            FRAME_RATE_SOURCE,
            FRAME_RATE_MAX,
            FRAME_RATE_STEP,
        )
        self.frame_rate_spin_button.set_value(FRAME_RATE_SOURCE)
        frame_rate_row.append(self.frame_rate_spin_button)
        frame_rate_row.append(Gtk.Label(label=f"{FRAME_RATE_SOURCE} keeps source FPS"))
        return frame_rate_row

    def _create_progress_bar(self) -> Gtk.ProgressBar:
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_hexpand(True)
        self.progress_bar.set_show_text(True)
        return self.progress_bar

    def _create_status_label(self) -> Gtk.Label:
        self.status_label_widget = Gtk.Label(label="")
        self.status_label_widget.set_xalign(LEFT_ALIGN)
        return self.status_label_widget

    def _create_action_row(self) -> Gtk.Box:
        action_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        action_row.set_halign(Gtk.Align.END)
        self.reencode_button = Gtk.Button(label="Reencode")
        self.reencode_button.connect("clicked", self._on_reencode)
        action_row.append(self.reencode_button)
        return action_row


def main() -> int:
    app = FloppyApp()
    return app.run()


def load_css() -> None:
    display = Gdk.Display.get_default()

    if display is None:
        return

    provider = Gtk.CssProvider()
    provider.load_from_data(APP_CSS.encode())
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


if __name__ == "__main__":
    raise SystemExit(main())
