import adsk.core
import adsk.fusion
import importlib
import json
import os
import sys
import traceback

# Ensure the add-in directory is on sys.path so submodules can be imported.
_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
if _ADDIN_DIR not in sys.path:
    sys.path.insert(0, _ADDIN_DIR)

# Import (and force-reload on re-run) so code changes take effect immediately.
import geometry
import layout
import commands
import handlers
importlib.reload(geometry)
importlib.reload(layout)
importlib.reload(commands)
importlib.reload(handlers)

from handlers import (
    CommandCreatedHandler,
    SummaryEventHandler,
    MarkingMenuHandler,
)

# Global references kept alive for the add-in lifetime.
_app: adsk.core.Application = None
_ui: adsk.core.UserInterface = None
_handlers = []

SUMMARY_EVENT_ID = "flattenLayoutSummaryEvent"
_summary_event = None

CMD_ID = "flattenLayoutCmd"
CMD_NAME = "Flatten & Layout"
CMD_DESCRIPTION = (
    "Copy visible bodies from selected components, orient each on its "
    "largest flat face, and arrange them in a grid."
)
TOOLBAR_PANEL_ID = "SolidModifyPanel"  # Design > Solid > Modify
_RESOURCES_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources')
_STATE_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), '.state.json')


def _save_promoted_state(is_promoted: bool):
    try:
        with open(_STATE_FILE, 'w') as f:
            json.dump({"isPromoted": is_promoted}, f)
    except Exception:
        pass


def _load_promoted_state() -> bool:
    try:
        with open(_STATE_FILE, 'r') as f:
            return json.load(f).get("isPromoted", False)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Add-in lifecycle
# ---------------------------------------------------------------------------

def run(context):
    try:
        global _app, _ui
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        cmd_defs = _ui.commandDefinitions
        existing = cmd_defs.itemById(CMD_ID)
        if existing:
            existing.deleteMe()

        cmd_def = cmd_defs.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESCRIPTION,
                                                _RESOURCES_DIR)

        on_created = CommandCreatedHandler(_handlers, _app, _ui, SUMMARY_EVENT_ID)
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        global _summary_event
        _summary_event = _app.registerCustomEvent(SUMMARY_EVENT_ID)
        on_summary = SummaryEventHandler(_ui)
        _summary_event.add(on_summary)
        _handlers.append(on_summary)

        panel = _ui.allToolbarPanels.itemById(TOOLBAR_PANEL_ID)
        if panel:
            existing_ctrl = panel.controls.itemById(CMD_ID)
            if not existing_ctrl:
                ctrl = panel.controls.addCommand(cmd_def)
                ctrl.isPromoted = _load_promoted_state()

        on_marking_menu = MarkingMenuHandler(_ui, CMD_ID)
        _ui.markingMenuDisplaying.add(on_marking_menu)
        _handlers.append(on_marking_menu)

    except Exception:
        if _ui:
            _ui.messageBox(f"Flatten add-in failed to start:\n{traceback.format_exc()}")


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById(TOOLBAR_PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
                _save_promoted_state(ctrl.isPromoted)
                ctrl.deleteMe()

        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()

        global _summary_event
        if _summary_event:
            _app.unregisterCustomEvent(SUMMARY_EVENT_ID)
            _summary_event = None

        _handlers.clear()

    except Exception:
        if _ui:
            _ui.messageBox(f"Flatten add-in failed to stop:\n{traceback.format_exc()}")



