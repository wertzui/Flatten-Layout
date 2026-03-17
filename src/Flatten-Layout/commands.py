import adsk.core
import adsk.fusion

from layout import build_layout_items, copy_and_rotate_bodies, arrange_bodies_in_grid, arrange_components_in_grid
from geometry import collect_bodies


LAYOUT_PADDING_CM = 1.0  # 10 mm expressed in cm (Fusion internal unit)


def default_component_name(sel_input: adsk.core.SelectionCommandInput) -> str:
    count = sel_input.selectionCount
    if count == 0:
        return "Flattened Layout"
    if count > 3:
        return "Flattened Layout"
    names = [sel_input.selection(i).entity.component.name for i in range(count)]
    return "Flattened " + ", ".join(names)


def execute(args: adsk.core.CommandEventArgs, app, ui):
    cmd = args.command
    inputs = cmd.commandInputs
    sel_input: adsk.core.SelectionCommandInput = inputs.itemById("selectedComponents")
    name_input: adsk.core.StringValueCommandInput = inputs.itemById("outputName")
    per_component_input = inputs.itemById("perComponent")
    body_spacing_input: adsk.core.ValueCommandInput = inputs.itemById("bodySpacing")
    comp_spacing_input: adsk.core.ValueCommandInput = inputs.itemById("compSpacing")

    output_name = (name_input.value.strip() if name_input and name_input.value.strip()
                   else default_component_name(sel_input))
    per_component = bool(per_component_input and per_component_input.value)
    body_padding = body_spacing_input.value if body_spacing_input else LAYOUT_PADDING_CM
    comp_padding = comp_spacing_input.value if comp_spacing_input else LAYOUT_PADDING_CM

    design: adsk.fusion.Design = app.activeProduct
    if not design:
        ui.messageBox("No active Fusion design.")
        return

    active_comp = design.activeComponent

    if per_component:
        total_laid_out, total_skipped = _execute_per_component(
            sel_input, active_comp, body_padding, comp_padding, ui)
    else:
        total_laid_out, total_skipped = _execute_single(
            sel_input, output_name, active_comp, body_padding, ui)

    if total_laid_out is None:
        return

    app.activeViewport.refresh()
    msg = f"Laid out {total_laid_out} body/bodies."
    if total_skipped:
        msg += f"\nSkipped {total_skipped} body/bodies (no planar faces)."
    return msg


def _execute_single(sel_input, output_name, active_comp, body_padding, ui):
    selected_occs = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
    body_records = []
    for occ in selected_occs:
        collect_bodies(occ, occ.transform, body_records)

    if not body_records:
        ui.messageBox("No visible bodies found in the selected components.")
        return None, 0

    layout_items, skipped = build_layout_items(body_records)
    if not layout_items:
        ui.messageBox("No bodies with planar faces found. Nothing to lay out.")
        return None, skipped

    target_occ = active_comp.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    target_occ.component.name = output_name
    copy_and_rotate_bodies(layout_items, target_occ)
    arrange_bodies_in_grid(layout_items, target_occ.component, body_padding)
    return len(layout_items), skipped


def _execute_per_component(sel_input, active_comp, body_padding, comp_padding, ui):
    selected_occs = [sel_input.selection(i).entity for i in range(sel_input.selectionCount)]
    target_occs = []
    total_laid_out = 0
    total_skipped = 0

    for occ in selected_occs:
        body_records = []
        collect_bodies(occ, occ.transform, body_records)

        if not body_records:
            continue

        layout_items, skipped = build_layout_items(body_records)
        total_skipped += skipped

        if not layout_items:
            continue

        target_occ = active_comp.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        target_occ.component.name = "Flat " + occ.component.name
        copy_and_rotate_bodies(layout_items, target_occ)
        arrange_bodies_in_grid(layout_items, target_occ.component, body_padding)
        total_laid_out += len(layout_items)
        target_occs.append(target_occ)

    if not target_occs:
        ui.messageBox("No visible bodies with planar faces found in the selected components.")
        return None, total_skipped

    if len(target_occs) > 1:
        arrange_components_in_grid(target_occs, comp_padding)

    return total_laid_out, total_skipped
