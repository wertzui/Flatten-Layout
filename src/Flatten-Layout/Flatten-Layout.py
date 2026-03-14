import adsk.core
import adsk.fusion
import math
import os
import traceback

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
LAYOUT_PADDING_CM = 1.0  # 10 mm expressed in cm (Fusion internal unit)


# ---------------------------------------------------------------------------
# Add-in lifecycle
# ---------------------------------------------------------------------------

def run(context):
    try:
        global _app, _ui
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        cmd_defs = _ui.commandDefinitions
        # Remove leftover definition if present.
        existing = cmd_defs.itemById(CMD_ID)
        if existing:
            existing.deleteMe()

        cmd_def = cmd_defs.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESCRIPTION,
                                                _RESOURCES_DIR)

        on_created = CommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        # Register a custom event used to show the summary message
        # after the execute handler has fully returned (cursor reset).
        global _summary_event
        _summary_event = _app.registerCustomEvent(SUMMARY_EVENT_ID)
        on_summary = SummaryEventHandler()
        _summary_event.add(on_summary)
        _handlers.append(on_summary)

        # Add to SOLID > TOOLS panel (works across workspaces).
        panel = _ui.allToolbarPanels.itemById(TOOLBAR_PANEL_ID)
        if panel:
            existing_ctrl = panel.controls.itemById(CMD_ID)
            if not existing_ctrl:
                panel.controls.addCommand(cmd_def)

    except Exception:
        if _ui:
            _ui.messageBox(f"Flatten add-in failed to start:\n{traceback.format_exc()}")


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById(TOOLBAR_PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
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


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args: adsk.core.CommandCreatedEventArgs):
        try:
            cmd = args.command
            inputs = cmd.commandInputs

            sel_input = inputs.addSelectionInput(
                "selectedComponents", "Components", "Select one or more components"
            )
            sel_input.addSelectionFilter("Occurrences")
            sel_input.setSelectionLimits(1, 0)  # min 1, unlimited max

            inputs.addStringValueInput(
                "outputName", "Output component name", "Flattened Layout"
            )

            inputs.addBoolValueInput(
                "perComponent", "One component per selection", True, "", False
            )

            on_input_changed = InputChangedHandler()
            cmd.inputChanged.add(on_input_changed)
            _handlers.append(on_input_changed)

            on_execute = CommandExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)

            on_destroy = CommandDestroyHandler()
            cmd.destroy.add(on_destroy)
            _handlers.append(on_destroy)

        except Exception:
            _ui.messageBox(f"CommandCreated failed:\n{traceback.format_exc()}")


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    """Keep the output name field in sync with the selection."""
    def notify(self, args: adsk.core.InputChangedEventArgs):
        try:
            inputs = args.inputs
            sel_input: adsk.core.SelectionCommandInput = inputs.itemById("selectedComponents")
            name_input: adsk.core.StringValueCommandInput = inputs.itemById("outputName")
            per_component_input = inputs.itemById("perComponent")
            per_comp = bool(per_component_input and per_component_input.value)
            if name_input:
                name_input.isEnabled = not per_comp
            if not per_comp and sel_input and name_input:
                name_input.value = _default_component_name(sel_input)
        except Exception:
            pass


class CommandDestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args: adsk.core.CommandEventArgs):
        # Allow garbage-collection of per-command handlers on next cycle.
        pass


class SummaryEventHandler(adsk.core.CustomEventHandler):
    """Runs after the execute handler has returned, so the cursor is normal."""
    def notify(self, args: adsk.core.CustomEventArgs):
        try:
            _ui.messageBox(args.additionalInfo)
        except Exception:
            pass


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args: adsk.core.CommandEventArgs):
        try:
            _execute(args)
        except Exception:
            _ui.messageBox(f"Flatten failed:\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _default_component_name(sel_input: adsk.core.SelectionCommandInput) -> str:
    count = sel_input.selectionCount
    if count == 0:
        return "Flattened Layout"
    if count > 3:
        return "Flattened Layout"
    names = [sel_input.selection(i).entity.component.name for i in range(count)]
    return "Flattened " + ", ".join(names)


def _execute(args: adsk.core.CommandEventArgs):
    cmd = args.command
    inputs = cmd.commandInputs
    sel_input: adsk.core.SelectionCommandInput = inputs.itemById("selectedComponents")
    name_input: adsk.core.StringValueCommandInput = inputs.itemById("outputName")
    per_component_input = inputs.itemById("perComponent")

    output_name = (name_input.value.strip() if name_input and name_input.value.strip()
                   else _default_component_name(sel_input))
    per_component = bool(per_component_input and per_component_input.value)

    design: adsk.fusion.Design = _app.activeProduct
    if not design:
        _ui.messageBox("No active Fusion design.")
        return

    root = design.rootComponent

    if per_component:
        total_laid_out, total_skipped = _execute_per_component(sel_input, root)
    else:
        total_laid_out, total_skipped = _execute_single(sel_input, output_name, root)

    if total_laid_out is None:
        return  # early-exit; message already shown

    _app.activeViewport.refresh()
    msg = f"Laid out {total_laid_out} body/bodies."
    if total_skipped:
        msg += f"\nSkipped {total_skipped} body/bodies (no planar faces)."
    _app.fireCustomEvent(SUMMARY_EVENT_ID, msg)


def _execute_single(sel_input, output_name, root):
    """Original behaviour: all selected bodies flattened into one component."""
    # Snapshot selections before any design modifications invalidate the indices.
    selected_occs = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
    body_records = []
    for occ in selected_occs:
        _collect_bodies(occ, occ.transform, body_records)

    if not body_records:
        _ui.messageBox("No visible bodies found in the selected components.")
        return None, 0

    layout_items, skipped = _build_layout_items(body_records)
    if not layout_items:
        _ui.messageBox("No bodies with planar faces found. Nothing to lay out.")
        return None, skipped

    target_occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    target_occ.component.name = output_name
    _copy_and_rotate_bodies(layout_items, target_occ)
    _arrange_bodies_in_grid(layout_items, target_occ.component)
    return len(layout_items), skipped


def _execute_per_component(sel_input, root):
    """New behaviour: one flat component created per selected occurrence."""
    # Snapshot selections before any design modifications invalidate the indices.
    selected_occs = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
    target_occs = []
    total_laid_out = 0
    total_skipped = 0

    for occ in selected_occs:
        body_records = []
        _collect_bodies(occ, occ.transform, body_records)

        if not body_records:
            continue

        layout_items, skipped = _build_layout_items(body_records)
        total_skipped += skipped

        if not layout_items:
            continue

        target_occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        target_occ.component.name = "Flat " + occ.component.name
        _copy_and_rotate_bodies(layout_items, target_occ)
        _arrange_bodies_in_grid(layout_items, target_occ.component)
        total_laid_out += len(layout_items)
        target_occs.append(target_occ)

    if not target_occs:
        _ui.messageBox("No visible bodies with planar faces found in the selected components.")
        return None, total_skipped

    if len(target_occs) > 1:
        _arrange_components_in_grid(target_occs)

    return total_laid_out, total_skipped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_layout_items(body_records):
    """Convert (body, world_transform) pairs into _LayoutItem objects with
    rotation transforms already computed."""
    layout_items = []
    skipped = 0
    for body, world_transform in body_records:
        best_face = _find_largest_planar_face(body)
        if best_face is None:
            skipped += 1
            continue
        # Transform face normal to world space.
        normal: adsk.core.Vector3D = best_face.geometry.normal.copy()
        _transform_vector(normal, world_transform)
        normal.normalize()
        item = _LayoutItem(body, world_transform, normal)
        item.rotation = _compute_flat_rotation(normal)
        # Build combined transform: world first, then rotation (lay flat).
        combined = item.rotation.copy()
        combined.transformBy(item.world_transform)
        item.combined_no_layout = combined
        layout_items.append(item)
    return layout_items, skipped


def _copy_and_rotate_bodies(layout_items, target_occ):
    """Copy bodies into *target_occ* and apply the flattening rotation.
    Populates each item's bounding-box fields (min_x/y/z, width, depth)
    and copied_body after the move."""
    target_comp = target_occ.component
    for item in layout_items:
        copied_body = item.body.copyToComponent(target_occ)
        if copied_body.assemblyContext:
            copied_body = copied_body.nativeObject

        # Apply rotation (lay flat).
        move_feats = target_comp.features.moveFeatures
        bodies_coll = adsk.core.ObjectCollection.create()
        bodies_coll.add(copied_body)
        move_input = move_feats.createInput2(bodies_coll)
        move_input.defineAsFreeMove(item.combined_no_layout)
        move_feats.add(move_input)

        # Read actual bounding box AFTER the rotation move.
        bb = copied_body.boundingBox
        item.min_x = bb.minPoint.x
        item.min_y = bb.minPoint.y
        item.min_z = bb.minPoint.z
        item.width = bb.maxPoint.x - bb.minPoint.x
        item.depth = bb.maxPoint.y - bb.minPoint.y
        item.copied_body = copied_body


def _arrange_bodies_in_grid(layout_items, target_comp):
    """Place bodies in a rectangular grid inside *target_comp*, translating
    each body to its assigned cell and shifting Z to zero."""
    total_area = sum(it.width * it.depth for it in layout_items)
    max_row_width = max(
        math.sqrt(total_area) * 1.5,
        max(it.width for it in layout_items) + LAYOUT_PADDING_CM,
    )

    # Sort large-first for better packing.
    layout_items.sort(key=lambda it: max(it.width, it.depth), reverse=True)

    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0

    for item in layout_items:
        if cursor_x + item.width > max_row_width and cursor_x > 0:
            cursor_x = 0.0
            cursor_y += row_height + LAYOUT_PADDING_CM
            row_height = 0.0
        item.layout_x = cursor_x
        item.layout_y = cursor_y
        cursor_x += item.width + LAYOUT_PADDING_CM
        row_height = max(row_height, item.depth)

    move_feats = target_comp.features.moveFeatures
    for item in layout_items:
        shift = adsk.core.Matrix3D.create()
        shift.translation = adsk.core.Vector3D.create(
            item.layout_x - item.min_x,
            item.layout_y - item.min_y,
            -item.min_z,
        )
        bodies_coll = adsk.core.ObjectCollection.create()
        bodies_coll.add(item.copied_body)
        move_input = move_feats.createInput2(bodies_coll)
        move_input.defineAsFreeMove(shift)
        move_feats.add(move_input)


def _arrange_components_in_grid(target_occs):
    """Translate root-level occurrences in a grid so their bounding boxes
    do not overlap.  Each occurrence is assumed to have an identity transform
    initially (bodies already laid out in component-local space)."""

    class _CompBounds:
        __slots__ = ("occ", "min_x", "min_y", "width", "depth",
                     "layout_x", "layout_y")

    bounds_list = []
    for occ in target_occs:
        cb = _CompBounds()
        cb.occ = occ
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")
        for j in range(occ.component.bRepBodies.count):
            bb = occ.component.bRepBodies.item(j).boundingBox
            if bb.minPoint.x < min_x:
                min_x = bb.minPoint.x
            if bb.minPoint.y < min_y:
                min_y = bb.minPoint.y
            if bb.maxPoint.x > max_x:
                max_x = bb.maxPoint.x
            if bb.maxPoint.y > max_y:
                max_y = bb.maxPoint.y
        cb.min_x = min_x if math.isfinite(min_x) else 0.0
        cb.min_y = min_y if math.isfinite(min_y) else 0.0
        cb.width = max(max_x - min_x, 0.0) if math.isfinite(max_x) else 0.0
        cb.depth = max(max_y - min_y, 0.0) if math.isfinite(max_y) else 0.0
        bounds_list.append(cb)

    total_area = sum(cb.width * cb.depth for cb in bounds_list)
    max_row_width = max(
        math.sqrt(total_area) * 1.5 if total_area > 0 else 0.0,
        max(cb.width for cb in bounds_list) + LAYOUT_PADDING_CM,
    )

    bounds_list.sort(key=lambda cb: max(cb.width, cb.depth), reverse=True)

    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0

    for cb in bounds_list:
        if cursor_x + cb.width > max_row_width and cursor_x > 0:
            cursor_x = 0.0
            cursor_y += row_height + LAYOUT_PADDING_CM
            row_height = 0.0
        cb.layout_x = cursor_x
        cb.layout_y = cursor_y
        cursor_x += cb.width + LAYOUT_PADDING_CM
        row_height = max(row_height, cb.depth)

    for cb in bounds_list:
        t = adsk.core.Matrix3D.create()
        t.translation = adsk.core.Vector3D.create(
            cb.layout_x - cb.min_x,
            cb.layout_y - cb.min_y,
            0.0,
        )
        cb.occ.transform = t


class _LayoutItem:
    """Holds per-body data through the layout pipeline."""
    __slots__ = (
        "body", "world_transform", "normal",
        "rotation", "width", "depth", "min_x", "min_y", "min_z",
        "combined_no_layout", "layout_x", "layout_y", "copied_body",
    )

    def __init__(self, body, world_transform, normal):
        self.body = body
        self.world_transform = world_transform
        self.normal = normal
        self.rotation = None
        self.width = 0.0
        self.depth = 0.0
        self.min_x = 0.0
        self.min_y = 0.0
        self.min_z = 0.0
        self.combined_no_layout = None
        self.layout_x = 0.0
        self.layout_y = 0.0
        self.copied_body = None


def _collect_bodies(occ: adsk.fusion.Occurrence,
                    current_world_transform: adsk.core.Matrix3D,
                    out: list):
    """Recursively collect visible bodies from *occ* and its children."""
    comp = occ.component

    for j in range(comp.bRepBodies.count):
        body = comp.bRepBodies.item(j)
        if body.isVisible:
            out.append((body, current_world_transform.copy()))

    # Recurse into child occurrences.
    for k in range(occ.childOccurrences.count):
        child = occ.childOccurrences.item(k)
        if child.isLightBulbOn:
            # Accumulate transform: child local -> parent local -> world
            child_world = child.transform.copy()
            child_world.transformBy(current_world_transform)
            _collect_bodies(child, child_world, out)


def _find_largest_planar_face(body: adsk.fusion.BRepBody):
    """Return the planar BRepFace with the largest area, or None."""
    best = None
    best_area = -1.0
    for i in range(body.faces.count):
        face = body.faces.item(i)
        geo = face.geometry
        if geo.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
            if face.area > best_area:
                best_area = face.area
                best = face
    return best


def _compute_flat_rotation(normal: adsk.core.Vector3D) -> adsk.core.Matrix3D:
    """Return a Matrix3D that rotates *normal* to point downward (0,0,-1)."""
    target = adsk.core.Vector3D.create(0.0, 0.0, -1.0)

    dot = normal.dotProduct(target)
    # Clamp for numerical safety.
    dot = max(-1.0, min(1.0, dot))

    if abs(dot - 1.0) < 1e-10:
        # Already aligned.
        return adsk.core.Matrix3D.create()

    if abs(dot + 1.0) < 1e-10:
        # Opposite direction – rotate 180° around X.
        m = adsk.core.Matrix3D.create()
        m.setToRotation(math.pi, adsk.core.Vector3D.create(1, 0, 0),
                        adsk.core.Point3D.create(0, 0, 0))
        return m

    axis = normal.crossProduct(target)
    axis.normalize()
    angle = math.acos(dot)

    m = adsk.core.Matrix3D.create()
    m.setToRotation(angle, axis, adsk.core.Point3D.create(0, 0, 0))
    return m


def _transform_vector(vec: adsk.core.Vector3D, matrix: adsk.core.Matrix3D):
    """Transform a direction vector by the rotational part of *matrix*."""
    # Transform a point at vec and subtract the translation to get pure rotation.
    p = adsk.core.Point3D.create(vec.x, vec.y, vec.z)
    p.transformBy(matrix)
    origin = adsk.core.Point3D.create(0, 0, 0)
    origin.transformBy(matrix)
    vec.x = p.x - origin.x
    vec.y = p.y - origin.y
    vec.z = p.z - origin.z


