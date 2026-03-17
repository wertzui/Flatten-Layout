import adsk.core
import adsk.fusion
import traceback

from commands import execute, default_component_name, LAYOUT_PADDING_CM


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, handlers, app, ui, summary_event_id):
        super().__init__()
        self._handlers = handlers
        self._app = app
        self._ui = ui
        self._summary_event_id = summary_event_id

    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            cmd = args.command
            inputs = cmd.commandInputs

            sel_input = inputs.addSelectionInput(
                "selectedComponents", "Components", "Select one or more components"
            )
            sel_input.addSelectionFilter("Occurrences")
            sel_input.setSelectionLimits(1, 0)

            inputs.addBoolValueInput(
                "perComponent", "One component per selection", True, "", True
            )

            inputs.addStringValueInput(
                "outputName", "Output component name", "Flattened Layout"
            )

            inputs.addValueInput(
                "bodySpacing", "Space between bodies",
                "mm", adsk.core.ValueInput.createByReal(LAYOUT_PADDING_CM)
            )

            comp_spacing = inputs.addValueInput(
                "compSpacing", "Space between components",
                "mm", adsk.core.ValueInput.createByReal(LAYOUT_PADDING_CM)
            )

            name_input = inputs.itemById("outputName")
            if name_input:
                name_input.isEnabled = False

            on_input_changed = InputChangedHandler()
            cmd.inputChanged.add(on_input_changed)
            self._handlers.append(on_input_changed)

            on_execute = CommandExecuteHandler(self._app, self._ui, self._summary_event_id)
            cmd.execute.add(on_execute)
            self._handlers.append(on_execute)

            on_destroy = CommandDestroyHandler()
            cmd.destroy.add(on_destroy)
            self._handlers.append(on_destroy)

        except Exception:
            self._ui.messageBox(f"CommandCreated failed:\n{traceback.format_exc()}")


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args: adsk.core.InputChangedEventArgs):
        try:
            inputs = args.inputs
            sel_input = inputs.itemById("selectedComponents")
            name_input = inputs.itemById("outputName")
            per_component_input = inputs.itemById("perComponent")
            per_comp = bool(per_component_input and per_component_input.value)
            if name_input:
                name_input.isEnabled = not per_comp
            comp_spacing_input = inputs.itemById("compSpacing")
            if comp_spacing_input:
                comp_spacing_input.isVisible = per_comp
            if not per_comp and sel_input and name_input:
                name_input.value = default_component_name(sel_input)
        except Exception:
            pass


class CommandDestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args: adsk.core.CommandEventArgs):
        pass


class SummaryEventHandler(adsk.core.CustomEventHandler):
    def __init__(self, ui):
        super().__init__()
        self._ui = ui

    def notify(self, args: adsk.core.CustomEventArgs):
        try:
            self._ui.messageBox(args.additionalInfo)
        except Exception:
            pass


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, app, ui, summary_event_id):
        super().__init__()
        self._app = app
        self._ui = ui
        self._summary_event_id = summary_event_id

    def notify(self, args: adsk.core.CommandEventArgs):
        try:
            msg = execute(args, self._app, self._ui)
            if msg:
                self._app.fireCustomEvent(self._summary_event_id, msg)
        except Exception:
            self._ui.messageBox(f"Flatten failed:\n{traceback.format_exc()}")


class MarkingMenuHandler(adsk.core.MarkingMenuEventHandler):
    def __init__(self, ui, cmd_id):
        super().__init__()
        self._ui = ui
        self._cmd_id = cmd_id

    def notify(self, args: adsk.core.MarkingMenuEventArgs):
        try:
            selected = self._ui.activeSelections
            if selected.count == 0:
                return
            has_occurrence = False
            for i in range(selected.count):
                if isinstance(selected.item(i).entity, adsk.fusion.Occurrence):
                    has_occurrence = True
                    break
            if not has_occurrence:
                return

            cmd_def = self._ui.commandDefinitions.itemById(self._cmd_id)
            if not cmd_def:
                return

            linear_menu = args.linearMarkingMenu
            linear_menu.controls.addCommand(cmd_def)
        except Exception:
            pass
