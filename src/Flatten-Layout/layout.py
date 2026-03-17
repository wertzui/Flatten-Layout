import adsk.core
import adsk.fusion
import math

from geometry import find_largest_planar_face, compute_flat_rotation


class LayoutItem:
    """Holds per-body data through the layout pipeline."""
    __slots__ = (
        "body", "world_transform",
        "width", "depth", "min_x", "min_y", "min_z",
        "layout_x", "layout_y", "copied_body",
    )

    def __init__(self, body, world_transform):
        self.body = body
        self.world_transform = world_transform
        self.width = 0.0
        self.depth = 0.0
        self.min_x = 0.0
        self.min_y = 0.0
        self.min_z = 0.0
        self.layout_x = 0.0
        self.layout_y = 0.0
        self.copied_body = None


def build_layout_items(body_records):
    """Filter body_records to those that have at least one planar face and
    wrap them in LayoutItem objects."""
    layout_items = []
    skipped = 0
    for body, world_transform in body_records:
        best_face = find_largest_planar_face(body)
        if best_face is None:
            skipped += 1
            continue
        item = LayoutItem(body, world_transform)
        layout_items.append(item)
    return layout_items, skipped


def copy_and_rotate_bodies(layout_items, target_occ):
    """Copy bodies into *target_occ* and apply the flattening rotation.
    Populates each item's bounding-box fields (min_x/y/z, width, depth)
    and copied_body after the move."""
    target_comp = target_occ.component
    for item in layout_items:
        copied_body = item.body.copyToComponent(target_occ)
        if copied_body.assemblyContext:
            copied_body = copied_body.nativeObject

        # Determine flattening rotation from the *copied* body's actual
        # geometry so we are always in the correct coordinate space.
        best_face = find_largest_planar_face(copied_body)
        normal = best_face.geometry.normal.copy()
        normal.normalize()
        rotation = compute_flat_rotation(normal)

        # Apply rotation (lay flat), unless already aligned.
        move_feats = target_comp.features.moveFeatures
        if not rotation.isEqualTo(adsk.core.Matrix3D.create()):
            bodies_coll = adsk.core.ObjectCollection.create()
            bodies_coll.add(copied_body)
            move_input = move_feats.createInput2(bodies_coll)
            move_input.defineAsFreeMove(rotation)
            move_feats.add(move_input)

        # Read actual bounding box AFTER the rotation move.
        bb = copied_body.boundingBox
        item.min_x = bb.minPoint.x
        item.min_y = bb.minPoint.y
        item.min_z = bb.minPoint.z
        item.width = bb.maxPoint.x - bb.minPoint.x
        item.depth = bb.maxPoint.y - bb.minPoint.y
        item.copied_body = copied_body

        # Ensure the longer side is along the Y-axis.
        if item.width > item.depth:
            rot90 = adsk.core.Matrix3D.create()
            rot90.setToRotation(math.pi / 2, adsk.core.Vector3D.create(0, 0, 1),
                                adsk.core.Point3D.create(0, 0, 0))
            bodies_coll2 = adsk.core.ObjectCollection.create()
            bodies_coll2.add(copied_body)
            move_input2 = move_feats.createInput2(bodies_coll2)
            move_input2.defineAsFreeMove(rot90)
            move_feats.add(move_input2)
            bb = copied_body.boundingBox
            item.min_x = bb.minPoint.x
            item.min_y = bb.minPoint.y
            item.min_z = bb.minPoint.z
            item.width = bb.maxPoint.x - bb.minPoint.x
            item.depth = bb.maxPoint.y - bb.minPoint.y


def arrange_bodies_in_grid(layout_items, target_comp, padding):
    """Place bodies in a rectangular grid inside *target_comp*, translating
    each body to its assigned cell and shifting Z to zero."""
    total_area = sum(it.width * it.depth for it in layout_items)
    max_row_width = max(
        math.sqrt(total_area) * 1.5,
        max(it.width for it in layout_items) + padding,
    )

    layout_items.sort(key=lambda it: max(it.width, it.depth), reverse=True)

    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0

    for item in layout_items:
        if cursor_x + item.width > max_row_width and cursor_x > 0:
            cursor_x = 0.0
            cursor_y += row_height + padding
            row_height = 0.0
        item.layout_x = cursor_x
        item.layout_y = cursor_y
        cursor_x += item.width + padding
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


def arrange_components_in_grid(target_occs, padding):
    """Translate occurrences in a grid so their bounding boxes do not overlap."""

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
        max(cb.width for cb in bounds_list) + padding,
    )

    bounds_list.sort(key=lambda cb: max(cb.width, cb.depth), reverse=True)

    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0

    for cb in bounds_list:
        if cursor_x + cb.width > max_row_width and cursor_x > 0:
            cursor_x = 0.0
            cursor_y += row_height + padding
            row_height = 0.0
        cb.layout_x = cursor_x
        cb.layout_y = cursor_y
        cursor_x += cb.width + padding
        row_height = max(row_height, cb.depth)

    for cb in bounds_list:
        t = adsk.core.Matrix3D.create()
        t.translation = adsk.core.Vector3D.create(
            cb.layout_x - cb.min_x,
            cb.layout_y - cb.min_y,
            0.0,
        )
        cb.occ.transform = t
