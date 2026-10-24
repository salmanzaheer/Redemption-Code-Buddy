"""
Redemption Code Buddy

Easily generate redemption codes personalized to your needs. Developed with Flet by Salman Zaheer.

"""

from pathlib import Path

import flet as ft

from core import (
    AMBIGUOUS,
    SYMBOLS,
    GenerationConfig,
    generate_codes,
    load_existing_codes,
    resolve_output_path,
    save_codes,
)
from profiler import (
    DEFAULT_LOG_FILE,
    Timer,
    format_duration,
    format_report,
    logger,
    reset_stats,
    set_logging_enabled,
    setup_logging,
)

# this is unnecessary but at some point Flet called buttons ElevatedButton
AppButton = getattr(ft, "Button", None) or ft.ElevatedButton

PREVIEW_LIMIT = 500


def main(page: ft.Page):
    log_path = setup_logging(enabled=True, log_file=DEFAULT_LOG_FILE)
    logger.info("Application started")

    page.title = "Redemption Code Buddy"
    page.appbar = ft.AppBar(
        title=ft.Text("Redemption Code Buddy", color=ft.Colors.BLACK),
        center_title=True,
        bgcolor=ft.Colors.AMBER_400,
    )
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 20
    try:
        page.window.width = 720
        page.window.height = 1000
    except Exception:
        pass

    generated: list[str] = []

    # Desktop apps can write straight to a path the user picks. Web and mobile
    # have no normal file system, so the bytes are handed to the picker instead
    # (in a browser that triggers a normal download).
    is_desktop = not page.web and page.platform in (
        ft.PagePlatform.WINDOWS,
        ft.PagePlatform.MACOS,
        ft.PagePlatform.LINUX,
    )
    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    # ------------------------------------------------------------ controls
    count_field = ft.TextField(
        label="Number of codes",
        value="100",
        width=200,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    length_field = ft.TextField(
        label="Random part length",
        value="12",
        width=200,
        keyboard_type=ft.KeyboardType.NUMBER,
        helper="Excludes prefix/suffix/separators",
    )
    group_field = ft.TextField(
        label="Group size (0 = none)",
        value="4",
        width=200,
        keyboard_type=ft.KeyboardType.NUMBER,
        helper="e.g. 4 -> ABCD-EFGH-IJKL",
    )

    prefix_field = ft.TextField(label="Prefix", width=200, hint_text="e.g. PROMO")
    suffix_field = ft.TextField(label="Suffix", width=200, hint_text="e.g. 2026")
    separator_field = ft.TextField(
        label="Separator",
        value="-",
        width=200,
        helper="Used between groups, prefix and suffix",
    )

    digits_cb = ft.Checkbox(label="Numbers (0-9)", value=True)
    upper_cb = ft.Checkbox(label="Uppercase letters (A-Z)", value=True)
    lower_cb = ft.Checkbox(label="Lowercase letters (a-z)", value=False)
    symbols_cb = ft.Checkbox(label=f"Symbols ({SYMBOLS})", value=False)

    custom_chars_field = ft.TextField(
        label="Extra custom characters", width=300, hint_text="added to the pool"
    )
    exclude_chars_field = ft.TextField(
        label="Characters to exclude", width=300, hint_text="removed from the pool"
    )

    ambiguous_cb = ft.Checkbox(
        label=f"Exclude look-alike characters ({AMBIGUOUS})", value=True
    )
    no_repeat_cb = ft.Checkbox(
        label="No identical characters side by side", value=False
    )
    force_upper_cb = ft.Checkbox(label="Force final code to UPPERCASE", value=False)
    force_lower_cb = ft.Checkbox(label="Force final code to lowercase", value=False)

    filename_field = ft.TextField(label="File name", value="codes.txt", width=250)
    timestamp_cb = ft.Checkbox(label="Add timestamp to file name", value=False)
    append_cb = ft.Checkbox(
        label="Append to file if it exists (otherwise overwrite)",
        value=False,
        visible=is_desktop,
    )
    dedupe_cb = ft.Checkbox(
        label="When appending, skip codes already in the file",
        value=True,
        visible=is_desktop,
    )

    logging_cb = ft.Checkbox(label="Enable logging", value=True)
    log_path_text = ft.Text(f"Log file: {log_path}", size=12, selectable=True)
    report_text = ft.Text(
        "No timing data recorded yet.", font_family="Consolas", size=12, selectable=True
    )

    status_text = ft.Text("", size=14)
    timing_text = ft.Text(
        "", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300
    )
    stats_text = ft.Text("", size=13, italic=True)
    preview_list = ft.ListView(expand=True, spacing=2, height=260)

    # ------------------------------------------------------------- helpers
    def set_status(message, error=False):
        status_text.value = message
        status_text.color = ft.Colors.RED_300 if error else ft.Colors.GREEN_300
        page.update()

    def notify(message):
        """Pop-up notification"""
        try:
            snack = ft.SnackBar(content=ft.Text(message), duration=6000)
            page.show_dialog(snack)
        except Exception:
            logger.exception("Could not show notification")

    def refresh_report():
        report_text.value = format_report()

    def read_int(field, name):
        try:
            return int((field.value or "").strip())
        except ValueError:
            raise ValueError(f"'{name}' must be a whole number.")

    def read_config() -> GenerationConfig:
        return GenerationConfig(
            count=read_int(count_field, "Number of codes"),
            length=read_int(length_field, "Random part length"),
            group_size=read_int(group_field, "Group size"),
            use_digits=digits_cb.value,
            use_upper=upper_cb.value,
            use_lower=lower_cb.value,
            use_symbols=symbols_cb.value,
            custom_chars=custom_chars_field.value or "",
            exclude_chars=exclude_chars_field.value or "",
            exclude_ambiguous=ambiguous_cb.value,
            no_repeats=no_repeat_cb.value,
            prefix=prefix_field.value or "",
            suffix=suffix_field.value or "",
            separator=separator_field.value or "",
            force_upper=force_upper_cb.value,
            force_lower=force_lower_cb.value,
        )

    def suggested_file_name() -> str:
        return resolve_output_path(filename_field.value, timestamp_cb.value).name

    def refresh_preview():
        preview_list.controls.clear()
        for code in generated[:PREVIEW_LIMIT]:
            preview_list.controls.append(
                ft.Text(code, selectable=True, font_family="Consolas")
            )
        if len(generated) > PREVIEW_LIMIT:
            preview_list.controls.append(
                ft.Text(
                    f"... and {len(generated) - PREVIEW_LIMIT:,} more (all will be saved).",
                    italic=True,
                )
            )

    # ------------------------------------------------------------ handlers
    def on_generate(e):
        logger.info("Generate button pressed")
        try:
            config = read_config()

            # This timer measures exactly what the user cares about:
            # how long generating ALL the codes took.
            with Timer("ui.generate_all_codes", record_stats=True) as gen_timer:
                result = generate_codes(config)

            generated.clear()
            generated.extend(result.codes)

            with Timer("ui.refresh_preview", record_stats=True) as ui_timer:
                refresh_preview()

            n = len(result.codes)
            rate = n / gen_timer.elapsed if gen_timer.elapsed > 0 else float("inf")
            timing_text.value = (
                f"Generation time: {gen_timer.pretty}  ({rate:,.0f} codes/s)"
            )
            stats_text.value = (
                f"Pool size: {result.charset_size} characters  |  "
                f"Possible combinations: {result.capacity:,}  |  "
                f"Duplicates rejected: {result.duplicates_rejected:,}  |  "
                f"Preview render: {ui_timer.pretty}"
            )
            refresh_report()
            set_status(f"Generated {n:,} unique codes.")
            notify(f"Generated {n:,} codes in {gen_timer.pretty}")
            logger.info("Generated %s codes in %s", f"{n:,}", gen_timer.pretty)
        except ValueError as err:
            logger.warning("Generation rejected: %s", err)
            set_status(str(err), error=True)

    async def on_save(e):
        if not generated:
            set_status("Nothing to save yet. Generate codes first.", error=True)
            return
        name = suggested_file_name()
        try:
            if is_desktop:
                chosen = await file_picker.save_file(
                    dialog_title="Save redemption codes",
                    file_name=name,
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["txt"],
                )
                if not chosen:
                    set_status("Save cancelled.")
                    return
                path = Path(chosen)
                to_write, skipped = generated, 0
                if append_cb.value and dedupe_cb.value:
                    existing = load_existing_codes(path)
                    to_write = [c for c in generated if c not in existing]
                    skipped = len(generated) - len(to_write)
                if not to_write:
                    set_status("Every code is already in that file; nothing to add.")
                    return
                with Timer("ui.save_codes", record_stats=True) as t:
                    save_codes(path, to_write, append=append_cb.value)
                msg = f"Saved {len(to_write):,} codes to: {path}  (took {t.pretty})"
                if skipped:
                    msg += f"  |  skipped {skipped:,} already in file"
                refresh_report()
                set_status(msg)
                notify(f"Saved {len(to_write):,} codes in {t.pretty}")
            else:
                data = ("\n".join(generated) + "\n").encode("utf-8")
                with Timer("ui.save_codes", record_stats=True) as t:
                    chosen = await file_picker.save_file(
                        dialog_title="Save redemption codes",
                        file_name=name,
                        src_bytes=data,
                    )
                refresh_report()
                where = f"to: {chosen}" if chosen else f"as {name}"
                set_status(f"Saved {len(generated):,} codes {where}")
                notify(f"Saved {len(generated):,} codes")
        except Exception as err:
            logger.exception("Save failed")
            set_status(f"Could not save file: {err}", error=True)

    async def on_copy(e):
        if not generated:
            set_status("Nothing to copy yet. Generate codes first.", error=True)
            return
        try:
            await ft.Clipboard().set("\n".join(generated))
            set_status(f"Copied {len(generated):,} codes to the clipboard.")
        except Exception as err:
            logger.exception("Clipboard failed")
            set_status(f"Clipboard not available: {err}", error=True)

    def on_clear(e):
        generated.clear()
        preview_list.controls.clear()
        stats_text.value = ""
        timing_text.value = ""
        set_status("Cleared.")

    def on_logging_toggle(e):
        if logging_cb.value:
            set_logging_enabled(True)
            logger.info("Logging enabled")
        else:
            logger.info("Logging disabled")
            set_logging_enabled(False)
        page.update()

    def on_reset_stats(e):
        reset_stats()
        refresh_report()
        page.update()

    def on_refresh_report(e):
        refresh_report()
        page.update()

    # layout
    def section(title, *controls):
        return ft.Container(
            content=ft.Column(
                [ft.Text(title, size=16, weight=ft.FontWeight.BOLD), *controls],
                spacing=10,
            ),
            padding=15,
            border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=10,
        )

    page.add(
        # ft.Text("Redemption Code Buddy", size=28, weight=ft.FontWeight.BOLD),
        ft.Text("Create unique, cryptographically random redemption codes.", size=14),
        section(
            "Quantity and length",
            ft.Row([count_field, length_field, group_field], wrap=True),
        ),
        section(
            "Character types",
            ft.Row([digits_cb, upper_cb, lower_cb, symbols_cb], wrap=True),
            ft.Row([custom_chars_field, exclude_chars_field], wrap=True),
            ambiguous_cb,
            no_repeat_cb,
        ),
        section(
            "Format",
            ft.Row([prefix_field, suffix_field, separator_field], wrap=True),
            ft.Row([force_upper_cb, force_lower_cb], wrap=True),
        ),
        section(
            "Output",
            ft.Row([filename_field], wrap=True),
            timestamp_cb,
            append_cb,
            dedupe_cb,
        ),
        ft.Row(
            [
                ft.Button("Generate", icon=ft.Icons.AUTO_AWESOME, on_click=on_generate),
                ft.Button("Save to text file", icon=ft.Icons.SAVE, on_click=on_save),
                ft.Button("Copy all", icon=ft.Icons.CONTENT_COPY, on_click=on_copy),
                ft.Button("Clear", icon=ft.Icons.DELETE_OUTLINE, on_click=on_clear),
            ],
            wrap=True,
        ),
        status_text,
        timing_text,
        stats_text,
        ft.Text("Preview", size=16, weight=ft.FontWeight.BOLD),
        ft.Container(
            content=preview_list,
            padding=10,
            border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=10,
        ),  # Hiding the logging screen for the main branch
        section(
            "Logging and profiling",
            logging_cb,
            log_path_text,
            ft.Row(
                [
                    ft.Button(
                        "Refresh report",
                        icon=ft.Icons.REFRESH,
                        on_click=on_refresh_report,
                    ),
                    ft.Button(
                        "Reset statistics",
                        icon=ft.Icons.RESTART_ALT,
                        on_click=on_reset_stats,
                    ),
                ],
                wrap=True,
            ),
            ft.Row([report_text], scroll=ft.ScrollMode.AUTO),
        ),
    )
    logging_cb.on_change = on_logging_toggle
    page.update()


if __name__ == "__main__":
    ft.run(main)
