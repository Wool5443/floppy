import asyncio
import logging
import threading
from pathlib import Path
from time import monotonic
from typing import Any

import gi

from . import engine, eta, utils as u
from .logging_config import configure_logging

GTK_VERSION = "4.0"

gi.require_version("Gtk", GTK_VERSION)
gi.require_version("Gdk", GTK_VERSION)

from gi.repository import (  # noqa: E402
    Gdk,  # pyright: ignore[reportAttributeAccessIssue]
    GLib,  # pyright: ignore[reportAttributeAccessIssue]
    Gtk,  # pyright: ignore[reportAttributeAccessIssue]
)

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
PRESET_DEFAULT_LABEL = "Default"
APP_CSS = """
progressbar progress {
    background: #3584e4;
}
"""
logger = logging.getLogger(__name__)


class FloppyApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID)

    def do_activate(self) -> None:
        logger.info("Activating application")
        window = MainWindow(self)
        load_css()
        window.present()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: FloppyApp) -> None:
        super().__init__(application=app, title="Floppy")
        self.set_icon_name(APPLICATION_ID)
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.selected_files: list[Path] = []
        self.output_folder: Path | None = None
        self.reencode_controller: engine.ReencodeController | None = None
        self.available_encode_configurations: dict[
            str,
            list[u.EncodeConfiguration],
        ] = {}
        self.preset_available = False

        self.set_child(self._build_interface())
        self._load_encode_options()

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

    def _on_choose_folder(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Choose folder",
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Open",
            "Cancel",
        )
        dialog.connect("response", self._on_folder_selected)
        dialog.show()

    def _on_choose_output_folder(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Choose output folder",
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "Open",
            "Cancel",
        )
        dialog.connect("response", self._on_output_folder_selected)
        dialog.show()

    def _on_file_selected(
        self,
        dialog: Gtk.FileChooserNative,
        response: int,
    ) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            self._set_selected_files(self._paths_from_files(dialog.get_files()))

        dialog.destroy()

    def _on_folder_selected(
        self,
        dialog: Gtk.FileChooserNative,
        response: int,
    ) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            path = None if file is None else file.get_path()

            if path is not None:
                self._set_selected_files(u.collect_video_files(path))

        dialog.destroy()

    def _on_output_folder_selected(
        self,
        dialog: Gtk.FileChooserNative,
        response: int,
    ) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            path = None if file is None else file.get_path()

            if path is not None:
                self.output_folder = Path(path)
                self.output_folder_label_widget.set_text(self.output_folder.name)
                logger.info("Selected output folder: %s", self.output_folder)

        dialog.destroy()

    def _on_reencode(self, _button: Gtk.Button) -> None:
        if not self.selected_files:
            self.status_label_widget.set_text("Choose input first")
            return

        quality = self.quality_spin_button.get_value_as_int()
        resolution_value = self.resolution_spin_button.get_value_as_int()
        frame_rate_value = self.frame_rate_spin_button.get_value_as_int()
        copy_metadata = self.metadata_check_button.get_active()
        preset = self._get_selected_preset()
        video_codec = self._get_selected_video_codec()
        resolution = None
        frame_rate = None

        if video_codec is None:
            self.status_label_widget.set_text("No codec available")
            return

        if resolution_value != RESOLUTION_SOURCE_SIZE:
            resolution = resolution_value
        if frame_rate_value != FRAME_RATE_SOURCE:
            frame_rate = frame_rate_value

        self._set_progress(PROGRESS_MIN)
        self.status_label_widget.set_text("Encoding...")
        self.reencode_controller = engine.ReencodeController()
        self._set_encoding_state(True)
        logger.info(
            "Starting batch: files=%s quality=%s resolution=%s frame_rate=%s "
            "copy_metadata=%s video_codec=%s preset=%s output_folder=%s",
            len(self.selected_files),
            quality,
            resolution,
            frame_rate,
            copy_metadata,
            video_codec,
            preset,
            self.output_folder,
        )

        thread = threading.Thread(
            target=self._reencode_worker,
            args=(
                self.selected_files.copy(),
                quality,
                resolution,
                frame_rate,
                copy_metadata,
                video_codec,
                preset,
                self.output_folder,
                self.reencode_controller,
            ),
            daemon=True,
        )
        thread.start()

    def _on_stop(self, _button: Gtk.Button) -> None:
        if self.reencode_controller is None:
            return

        self.stop_button.set_sensitive(False)
        self.status_label_widget.set_text("Stopping...")
        logger.info("Stopping batch")
        self.reencode_controller.cancel()

    def _reencode_worker(
        self,
        filenames: list[Path],
        quality: int,
        resolution: int | None,
        frame_rate: float | None,
        copy_metadata: bool,
        video_codec: str,
        preset: str | None,
        output_folder: Path | None,
        controller: engine.ReencodeController,
    ) -> None:
        completed = 0
        total = len(filenames)
        batch_started_at = monotonic()

        try:
            for filename in filenames:
                if controller.cancelled:
                    logger.info("Batch cancelled before next file")
                    break

                logger.info("Encoding file %s/%s: %s", completed + 1, total, filename)
                GLib.idle_add(self._set_progress, PROGRESS_MIN)
                GLib.idle_add(
                    self.status_label_widget.set_text,
                    self._encoding_status(
                        completed,
                        total,
                        filename.name,
                        None,
                    ),
                )
                status_callback = self._make_status_callback(
                    completed,
                    total,
                    filename.name,
                )
                asyncio.run(
                    engine.reencode(
                        filename,
                        quality=quality,
                        resolution=resolution,
                        frame_rate=frame_rate,
                        copy_metadata=copy_metadata,
                        progress_callback=self._make_progress_callback(
                            completed,
                            total,
                            filename.name,
                            batch_started_at,
                        ),
                        status_callback=status_callback,
                        preset=preset,
                        controller=controller,
                        output_folder=output_folder,
                        video_codec=video_codec,
                    )
                )
                completed += 1
                logger.info("Completed file %s/%s: %s", completed, total, filename)
                GLib.idle_add(
                    self.status_label_widget.set_text,
                    f"{completed}/{total} reencoded",
                )
                GLib.idle_add(self._set_progress, PROGRESS_MAX)
        except engine.ReencodeStopped:
            logger.info("Batch stopped after %s/%s files", completed, total)
            GLib.idle_add(self._finish_reencode, completed, total, None, True)
            return
        except Exception as error:
            logger.exception("Batch failed after %s/%s files", completed, total)
            GLib.idle_add(self._finish_reencode, completed, total, str(error), False)
            return

        logger.info("Batch finished: %s/%s files", completed, total)
        GLib.idle_add(self._finish_reencode, completed, total, None, controller.cancelled)

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

        paths = []

        for file in files:
            if file is None or (path := file.get_path()) is None:
                continue

            candidate = Path(path)
            if candidate.is_dir():
                paths.extend(u.collect_video_files(candidate))
            else:
                paths.append(candidate)

        return paths

    def _set_selected_files(self, paths: list[Path]) -> None:
        self.selected_files = paths
        self.status_label_widget.set_text("")
        logger.info("Selected input files: %s", len(paths))

        match len(paths):
            case 0:
                self.file_label_widget.set_text("No files selected")
            case 1:
                self.file_label_widget.set_text(paths[0].name)
            case count:
                self.file_label_widget.set_text(f"{count} files selected")

    def _make_progress_callback(
        self,
        completed: int,
        total: int,
        filename: str,
        batch_started_at: float,
    ) -> engine.ProgressCallback:
        def progress_callback(fraction: float) -> None:
            fraction = max(PROGRESS_MIN, min(PROGRESS_MAX, fraction))
            remaining_seconds = eta.estimate_remaining_seconds(
                monotonic() - batch_started_at,
                completed,
                fraction,
                total,
            )
            GLib.idle_add(self._set_progress, fraction)
            GLib.idle_add(
                self.status_label_widget.set_text,
                self._encoding_status(
                    completed,
                    total,
                    filename,
                    remaining_seconds,
                ),
            )

        return progress_callback

    def _encoding_status(
        self,
        completed: int,
        total: int,
        filename: str,
        remaining_seconds: float | None,
    ) -> str:
        status = f"{completed}/{total} reencoded - Encoding {filename}"

        if remaining_seconds is None:
            return f"{status} - calculating remaining time"

        return f"{status} - remaining {eta.format_remaining_time(remaining_seconds)}"

    def _set_progress(self, fraction: float) -> bool:
        self.progress_bar.set_fraction(fraction)
        self.progress_bar.set_text(f"{fraction * 100:0.2f}%")
        return False

    def _finish_reencode(
        self,
        completed: int,
        total: int,
        error: str | None,
        stopped: bool = False,
    ) -> bool:
        self.reencode_controller = None
        self._set_encoding_state(False)

        if error is not None:
            self.status_label_widget.set_text(
                f"Failed after {completed}/{total}: {error}"
            )
            return False

        if stopped:
            self.status_label_widget.set_text(f"{completed}/{total} reencoded - stopped")
            return False

        self._set_progress(PROGRESS_MAX)
        self.status_label_widget.set_text(f"{completed}/{total} reencoded")

        return False

    def _make_status_callback(
        self,
        completed: int,
        total: int,
        filename: str,
    ) -> engine.StatusCallback:
        return lambda message: GLib.idle_add(
            self.status_label_widget.set_text,
            f"{completed}/{total} reencoded - {filename}: {message}",
        )

    def _set_encoding_state(self, encoding: bool) -> None:
        self.reencode_button.set_sensitive(not encoding)
        self.choose_button.set_sensitive(not encoding)
        self.choose_output_folder_button.set_sensitive(not encoding)
        self.quality_spin_button.set_sensitive(not encoding)
        self.resolution_spin_button.set_sensitive(not encoding)
        self.frame_rate_spin_button.set_sensitive(not encoding)
        self.metadata_check_button.set_sensitive(not encoding)
        self.codec_combo_box.set_sensitive(
            not encoding and bool(self.available_encode_configurations)
        )
        self.preset_combo_box.set_sensitive(not encoding and self.preset_available)
        self.stop_button.set_sensitive(encoding)

    def _get_selected_video_codec(self) -> str | None:
        active_text = self.codec_combo_box.get_active_text()

        if active_text is None:
            return None

        for video_codec, label in u.VIDEO_CODEC_LABELS.items():
            if active_text.startswith(label):
                return video_codec

        return None

    def _get_selected_preset(self) -> str | None:
        preset = self.preset_combo_box.get_active_text()

        if preset is None or preset == PRESET_DEFAULT_LABEL:
            return None

        return preset

    def _load_encode_options(self) -> None:
        thread = threading.Thread(target=self._load_encode_options_worker, daemon=True)
        thread.start()

    def _load_encode_options_worker(self) -> None:
        try:
            available_configurations = engine.get_available_encode_configurations()
        except Exception as error:
            GLib.idle_add(
                self.status_label_widget.set_text,
                f"Could not detect encoders: {error}",
            )
            return

        GLib.idle_add(
            self._set_encode_options,
            available_configurations,
        )

    def _set_encode_options(
        self,
        available_configurations: dict[str, list[u.EncodeConfiguration]],
    ) -> bool:
        self.available_encode_configurations = {
            video_codec: configurations
            for video_codec, configurations in available_configurations.items()
            if configurations
        }
        self.codec_combo_box.remove_all()

        for video_codec in (u.VIDEO_CODEC_HEVC, u.VIDEO_CODEC_AV1):
            configurations = self.available_encode_configurations.get(video_codec, [])
            if not configurations:
                continue

            selected = configurations[0]
            self.codec_combo_box.append_text(
                f"{u.VIDEO_CODEC_LABELS[video_codec]} ({selected.name})"
            )

        self.availability_label_widget.set_text(
            u.format_availability_summary(available_configurations)
        )

        if not self.available_encode_configurations:
            self.codec_combo_box.append_text("No codecs")
            self.codec_combo_box.set_active(0)
            self.codec_combo_box.set_sensitive(False)
            self.reencode_button.set_sensitive(False)
            self._set_preset_options([], None)
            self.status_label_widget.set_text("No usable encoder found in ffmpeg.")
            return False

        self.codec_combo_box.set_active(0)
        self.codec_combo_box.set_sensitive(self.reencode_controller is None)
        self.reencode_button.set_sensitive(self.reencode_controller is None)
        self._update_preset_options_for_selected_codec()
        return False

    def _on_codec_changed(self, _combo_box: Gtk.ComboBoxText) -> None:
        self._update_preset_options_for_selected_codec()

    def _update_preset_options_for_selected_codec(self) -> None:
        video_codec = self._get_selected_video_codec()
        if video_codec is None:
            self._set_preset_options([], None)
            return

        configurations = self.available_encode_configurations.get(video_codec, [])
        if not configurations:
            self._set_preset_options([], None)
            return

        encode_configuration = configurations[0]
        self._set_preset_options(
            u.get_preset_options(encode_configuration),
            u.get_default_preset(encode_configuration),
        )

    def _set_preset_options(
        self,
        presets: list[str],
        default_preset: str | None,
    ) -> bool:
        self.preset_combo_box.remove_all()

        if not presets:
            self.preset_available = False
            self.preset_combo_box.append_text("No presets")
            self.preset_combo_box.set_active(0)
            self.preset_combo_box.set_sensitive(False)
            return False

        self.preset_combo_box.append_text(PRESET_DEFAULT_LABEL)
        for preset in presets:
            self.preset_combo_box.append_text(preset)

        active_index = 0
        if default_preset in presets:
            active_index = presets.index(default_preset) + 1

        self.preset_combo_box.set_active(active_index)
        self.preset_available = True
        self.preset_combo_box.set_sensitive(self.reencode_controller is None)
        return False

    def _build_interface(self) -> Gtk.Widget:
        root = self._create_root_box()
        root.append(self._create_title_label())
        root.append(self._create_file_row())
        root.append(self._create_output_folder_row())
        root.append(self._create_drop_hint_label())
        root.append(self._create_quality_row())
        root.append(self._create_codec_row())
        root.append(self._create_preset_row())
        root.append(self._create_resolution_row())
        root.append(self._create_frame_rate_row())
        root.append(self._create_metadata_row())
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
        title = Gtk.Label(label="Video Reencoder")
        title.add_css_class(TITLE_CSS_CLASS)
        title.set_xalign(LEFT_ALIGN)
        return title

    def _create_file_row(self) -> Gtk.Box:
        file_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=ROW_SPACING)
        self.file_label_widget = Gtk.Label(label="No files selected")
        self.file_label_widget.set_hexpand(True)
        self.file_label_widget.set_xalign(LEFT_ALIGN)
        file_row.append(self.file_label_widget)

        self.choose_button = Gtk.MenuButton(label="Choose input")
        self.choose_button.set_popover(self._create_input_popover())
        file_row.append(self.choose_button)
        return file_row

    def _create_input_popover(self) -> Gtk.Popover:
        popover = Gtk.Popover()
        input_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=ROW_SPACING,
            margin_top=ROW_SPACING,
            margin_bottom=ROW_SPACING,
            margin_start=ROW_SPACING,
            margin_end=ROW_SPACING,
        )

        choose_files_button = Gtk.Button(label="Files")
        choose_files_button.connect("clicked", self._on_choose_file)
        input_box.append(choose_files_button)

        choose_folder_button = Gtk.Button(label="Folder")
        choose_folder_button.connect("clicked", self._on_choose_folder)
        input_box.append(choose_folder_button)

        popover.set_child(input_box)
        return popover

    def _create_output_folder_row(self) -> Gtk.Box:
        output_folder_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        self.output_folder_label_widget = Gtk.Label(label="Output: source folder")
        self.output_folder_label_widget.set_hexpand(True)
        self.output_folder_label_widget.set_xalign(LEFT_ALIGN)
        output_folder_row.append(self.output_folder_label_widget)
        self.choose_output_folder_button = Gtk.Button(label="Choose output folder")
        self.choose_output_folder_button.connect(
            "clicked",
            self._on_choose_output_folder,
        )
        output_folder_row.append(self.choose_output_folder_button)
        return output_folder_row

    def _create_drop_hint_label(self) -> Gtk.Label:
        hint_label = Gtk.Label(label="Drag video files/folders here or choose input")
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
        quality_row.append(self._create_quality_hint_label())
        return quality_row

    def _create_quality_hint_label(self) -> Gtk.Label:
        hint_label = Gtk.Label(label="Less means higher quality")
        hint_label.add_css_class(DIM_LABEL_CSS_CLASS)
        hint_label.set_xalign(LEFT_ALIGN)
        return hint_label

    def _create_codec_row(self) -> Gtk.Box:
        codec_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        codec_row.append(Gtk.Label(label="Codec"))
        self.codec_combo_box = Gtk.ComboBoxText()
        self.codec_combo_box.append_text("Detecting...")
        self.codec_combo_box.set_active(0)
        self.codec_combo_box.set_sensitive(False)
        self.codec_combo_box.connect("changed", self._on_codec_changed)
        codec_row.append(self.codec_combo_box)
        self.availability_label_widget = Gtk.Label(label="Detecting acceleration...")
        self.availability_label_widget.add_css_class(DIM_LABEL_CSS_CLASS)
        self.availability_label_widget.set_xalign(LEFT_ALIGN)
        self.availability_label_widget.set_hexpand(True)
        codec_row.append(self.availability_label_widget)
        return codec_row

    def _create_preset_row(self) -> Gtk.Box:
        preset_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        preset_row.append(Gtk.Label(label="Preset"))
        self.preset_combo_box = Gtk.ComboBoxText()
        self.preset_combo_box.append_text("Detecting...")
        self.preset_combo_box.set_active(0)
        self.preset_combo_box.set_sensitive(False)
        preset_row.append(self.preset_combo_box)
        return preset_row

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

    def _create_metadata_row(self) -> Gtk.Box:
        metadata_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=ROW_SPACING,
        )
        self.metadata_check_button = Gtk.CheckButton(label="Copy metadata")
        metadata_row.append(self.metadata_check_button)
        return metadata_row

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
        self.stop_button = Gtk.Button(label="Stop")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self._on_stop)
        action_row.append(self.stop_button)
        self.reencode_button = Gtk.Button(label="Reencode")
        self.reencode_button.set_sensitive(False)
        self.reencode_button.connect("clicked", self._on_reencode)
        action_row.append(self.reencode_button)
        return action_row


def main() -> int:
    configure_logging()
    logger.info("Starting Floppy")
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
