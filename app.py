import asyncio
import threading
from pathlib import Path

import gi

import engine

GTK_VERSION = "4.0"

gi.require_version("Gtk", GTK_VERSION)
gi.require_version("Gdk", GTK_VERSION)
from gi.repository import Gdk, GLib, Gtk  # noqa: E402  # pyright: ignore[reportAttributeAccessIssue]


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
DEFAULT_QUALITY = 24
RESOLUTION_SOURCE_SIZE = 0
RESOLUTION_MAX = 7680
RESOLUTION_STEP = 1
TITLE_CSS_CLASS = "title-1"
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
        self.selected_file: Path | None = None

        self.set_child(self._build_interface())

    def _build_interface(self) -> Gtk.Widget:
        root = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=SECTION_SPACING,
            margin_top=PAGE_MARGIN,
            margin_bottom=PAGE_MARGIN,
            margin_start=PAGE_MARGIN,
            margin_end=PAGE_MARGIN,
        )

        title = Gtk.Label(label="HEVC Reencoder")
        title.add_css_class(TITLE_CSS_CLASS)
        title.set_xalign(LEFT_ALIGN)
        root.append(title)

        file_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=ROW_SPACING)
        self.file_label = Gtk.Label(label="No file selected")
        self.file_label.set_hexpand(True)
        self.file_label.set_xalign(LEFT_ALIGN)
        file_row.append(self.file_label)
        self.choose_button = Gtk.Button(label="Choose file")
        self.choose_button.connect("clicked", self._on_choose_file)
        file_row.append(self.choose_button)
        root.append(file_row)

        quality_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        quality_row.append(Gtk.Label(label="Quality"))
        self.quality = Gtk.SpinButton.new_with_range(
            QUALITY_MIN,
            QUALITY_MAX,
            QUALITY_STEP,
        )
        self.quality.set_value(DEFAULT_QUALITY)
        quality_row.append(self.quality)
        root.append(quality_row)

        resolution_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        resolution_row.append(Gtk.Label(label="Resolution"))
        self.resolution = Gtk.SpinButton.new_with_range(
            RESOLUTION_SOURCE_SIZE,
            RESOLUTION_MAX,
            RESOLUTION_STEP,
        )
        self.resolution.set_value(RESOLUTION_SOURCE_SIZE)
        resolution_row.append(self.resolution)
        resolution_row.append(
            Gtk.Label(label=f"{RESOLUTION_SOURCE_SIZE} keeps source size")
        )
        root.append(resolution_row)

        self.progress = Gtk.ProgressBar()
        self.progress.set_hexpand(True)
        self.progress.set_show_text(True)
        root.append(self.progress)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(LEFT_ALIGN)
        root.append(self.status_label)

        action_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        action_row.set_halign(Gtk.Align.END)
        self.reencode_button = Gtk.Button(label="Reencode")
        self.reencode_button.connect("clicked", self._on_reencode)
        action_row.append(self.reencode_button)
        root.append(action_row)

        return root

    def _on_choose_file(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Choose video",
            self,
            Gtk.FileChooserAction.OPEN,
            "Open",
            "Cancel",
        )
        dialog.connect("response", self._on_file_selected)
        dialog.show()

    def _on_file_selected(
        self,
        dialog: Gtk.FileChooserNative,
        response: int,
    ) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            path = file.get_path() if file is not None else None

            if path is not None:
                self.selected_file = Path(path)
                self.file_label.set_text(self.selected_file.name)
                self.status_label.set_text("")

        dialog.destroy()

    def _on_reencode(self, _button: Gtk.Button) -> None:
        if self.selected_file is None:
            self.status_label.set_text("Choose a file first")
            return

        quality = self.quality.get_value_as_int()
        resolution_value = self.resolution.get_value_as_int()
        resolution = None

        if resolution_value != RESOLUTION_SOURCE_SIZE:
            resolution = resolution_value

        self._set_progress(PROGRESS_MIN)
        self.status_label.set_text("Encoding...")
        self.reencode_button.set_sensitive(False)
        self.choose_button.set_sensitive(False)

        thread = threading.Thread(
            target=self._reencode_worker,
            args=(self.selected_file, quality, resolution),
            daemon=True,
        )
        thread.start()

    def _reencode_worker(
        self,
        filename: Path,
        quality: int,
        resolution: int | None,
    ) -> None:
        try:
            output_path = asyncio.run(
                engine.reencode(
                    filename,
                    quality=quality,
                    resolution=resolution,
                    progress_callback=self._queue_progress,
                )
            )
        except Exception as error:
            GLib.idle_add(self._finish_reencode, None, str(error))
            return

        GLib.idle_add(self._finish_reencode, output_path, None)

    def _queue_progress(self, fraction: float) -> None:
        fraction = max(PROGRESS_MIN, min(PROGRESS_MAX, fraction))
        GLib.idle_add(self._set_progress, fraction)

    def _set_progress(self, fraction: float) -> bool:
        self.progress.set_fraction(fraction)
        self.progress.set_text(f"{fraction * 100:0.2f}%")
        return False

    def _finish_reencode(
        self,
        output_path: Path | None,
        error: str | None,
    ) -> bool:
        self.reencode_button.set_sensitive(True)
        self.choose_button.set_sensitive(True)

        if error is not None:
            self.status_label.set_text(error)
            return False

        self._set_progress(PROGRESS_MAX)
        if output_path is not None:
            self.status_label.set_text(f"Saved {output_path.name}")

        return False


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
