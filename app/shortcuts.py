from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QT_TRANSLATE_NOOP


@dataclass(frozen=True)
class ShortcutDefinition:
    id: str
    label: str
    description: str
    default: str


SHORTCUT_DEFINITIONS: tuple[ShortcutDefinition, ...] = (
    ShortcutDefinition(
        id="save_project",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Save Project"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Save the current project file."),
        default="Ctrl+S",
    ),
    ShortcutDefinition(
        id="save_current_image",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Save Current Image"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Save the currently loaded image."),
        default="Ctrl+E",
    ),
    ShortcutDefinition(
        id="undo",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Undo"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Undo the last editing action."),
        default="Ctrl+Z",
    ),
    ShortcutDefinition(
        id="redo",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Redo"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Redo the previously undone action."),
        default="Ctrl+Y",
    ),
    ShortcutDefinition(
        id="delete_selected_box",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Delete Selected Box"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Delete the currently selected text box."),
        default="Delete",
    ),
    ShortcutDefinition(
        id="restore_text_blocks",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Restore Text Blocks"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Draw saved text blocks back onto the image for editing."),
        default="Ctrl+Shift+R",
    ),
    ShortcutDefinition(
        id="toggle_brush_strokes",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle Brush Strokes"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Toggle brush stroke drawing on or off."),
        default="Ctrl+D",
    ),
    ShortcutDefinition(
        id="select_all",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Select All"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Select the whole page on the canvas."),
        default="Ctrl+A",
    ),
    ShortcutDefinition(
        id="deselect",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Deselect"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Drop the canvas selection."),
        default="Ctrl+Shift+A",
    ),
    ShortcutDefinition(
        id="invert_selection",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Invert Selection"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Select everything on the page that is not selected."),
        default="Ctrl+Shift+I",
    ),
)


# Canvas tools, one key per group as in Photoshop (and PhotoCraft, which follows
# it): the key picks the group's first tool, or keeps the tool in hand if it is
# already one of the group; Shift + the key steps to the next tool in the group.
# Tool names are `viewer.current_tool` values / `main.tool_buttons` keys.
TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "tool_move": ("box",),
    "tool_hand": ("pan",),
    "tool_type": ("type",),
    "tool_brush": ("brush", "paint"),
    "tool_eraser": ("eraser", "restore"),
    "tool_healing": ("spotheal", "aibrush", "heal"),
    "tool_clone": ("clone",),
    "tool_fill": ("fill",),
    "tool_eyedropper": ("eyedropper",),
    "tool_marquee": ("marquee",),
    "tool_lasso": ("lasso",),
    "tool_wand": ("wand", "balloon"),
}

SHORTCUT_DEFINITIONS = SHORTCUT_DEFINITIONS + (
    ShortcutDefinition(
        id="tool_move",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Box Tool"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Draw, select and move text boxes."),
        default="V",
    ),
    ShortcutDefinition(
        id="tool_hand",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Hand Tool"),
        description=QT_TRANSLATE_NOOP(
            "ShortcutDefinitions", "Pan the page. Holding Space pans with any tool."
        ),
        default="H",
    ),
    ShortcutDefinition(
        id="tool_type",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Type Tool"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Click on the page to type your own text."),
        default="T",
    ),
    ShortcutDefinition(
        id="tool_brush",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Brush Tools"),
        description=QT_TRANSLATE_NOOP(
            "ShortcutDefinitions", "Cleaning brush; Shift + the key switches to the paint brush and back."
        ),
        default="B",
    ),
    ShortcutDefinition(
        id="tool_eraser",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Eraser Tools"),
        description=QT_TRANSLATE_NOOP(
            "ShortcutDefinitions", "Stroke eraser; Shift + the key switches to the restore eraser and back."
        ),
        default="E",
    ),
    ShortcutDefinition(
        id="tool_healing",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Healing Tools"),
        description=QT_TRANSLATE_NOOP(
            "ShortcutDefinitions",
            "Spot healing brush; Shift + the key steps to the AI inpaint brush and the healing brush.",
        ),
        default="J",
    ),
    ShortcutDefinition(
        id="tool_clone",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Clone Stamp"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Paint with a copy of another part of the page."),
        default="S",
    ),
    ShortcutDefinition(
        id="tool_fill",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Fill Bucket"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Fill a flat area with the paint colour."),
        default="G",
    ),
    ShortcutDefinition(
        id="tool_eyedropper",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Eyedropper"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Pick the paint colour from the page."),
        default="I",
    ),
    ShortcutDefinition(
        id="tool_marquee",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Rectangle Select"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Select a rectangle of the page."),
        default="M",
    ),
    ShortcutDefinition(
        id="tool_lasso",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Lasso"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Select an irregular shape."),
        default="L",
    ),
    ShortcutDefinition(
        id="tool_wand",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Magic Wand"),
        description=QT_TRANSLATE_NOOP(
            "ShortcutDefinitions", "Select a region in one click; Shift + the key switches to the balloon tool and back."
        ),
        default="W",
    ),
    ShortcutDefinition(
        id="brush_smaller",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Smaller Brush"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Make the brush or eraser smaller."),
        default="[",
    ),
    ShortcutDefinition(
        id="brush_larger",
        label=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Larger Brush"),
        description=QT_TRANSLATE_NOOP("ShortcutDefinitions", "Make the brush or eraser larger."),
        default="]",
    ),
)


def next_tool(group: tuple[str, ...], current: str | None, cycle: bool) -> str:
    """The tool a group's key picks: the one in hand if it belongs to the group
    (or the next one, when cycling), otherwise the group's first."""
    if current in group:
        index = group.index(current)
        return group[(index + 1) % len(group)] if cycle else current
    return group[0]


def brush_size_step(size: int, larger: bool) -> int:
    """Photoshop-like steps: fine for a small brush, coarser for a big one."""
    step = 1 if size < 10 else 5 if size < 50 else 10
    if not larger and size <= 10 and size > 1:
        step = 1
    return size + step if larger else max(1, size - step)


def get_shortcut_definitions() -> tuple[ShortcutDefinition, ...]:
    return SHORTCUT_DEFINITIONS


def get_default_shortcuts() -> dict[str, str]:
    return {definition.id: definition.default for definition in SHORTCUT_DEFINITIONS}
