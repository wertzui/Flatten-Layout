import adsk.core
import adsk.fusion
import math


def collect_bodies(occ: adsk.fusion.Occurrence,
                   current_world_transform: adsk.core.Matrix3D,
                   out: list):
    """Recursively collect visible bodies from *occ* and its children."""
    comp = occ.component

    for j in range(comp.bRepBodies.count):
        body = comp.bRepBodies.item(j)
        if body.isVisible:
            out.append((body, current_world_transform.copy()))

    for k in range(occ.childOccurrences.count):
        child = occ.childOccurrences.item(k)
        if child.isLightBulbOn:
            child_world = child.transform.copy()
            child_world.transformBy(current_world_transform)
            collect_bodies(child, child_world, out)


def find_largest_planar_face(body: adsk.fusion.BRepBody):
    """Return the planar BRepFace with the largest area, or None.

    When multiple faces share the same largest area:
    - Prefer a face already facing straight upward (normal ≈ 0,0,1).
    - Otherwise prefer the face whose normal points most outward from
      the body's bounding-box centre."""
    AREA_TOL = 1e-4  # cm² tolerance for considering areas equal

    # Collect all planar faces and find the maximum area.
    planar_faces = []
    best_area = -1.0
    for i in range(body.faces.count):
        face = body.faces.item(i)
        if face.geometry.surfaceType == adsk.core.SurfaceTypes.PlaneSurfaceType:
            planar_faces.append(face)
            if face.area > best_area:
                best_area = face.area

    if best_area < 0:
        return None

    # Keep only those within tolerance of the maximum area.
    candidates = [f for f in planar_faces if abs(f.area - best_area) <= AREA_TOL]

    if len(candidates) == 1:
        return candidates[0]

    # Prefer a face already pointing straight up.
    for face in candidates:
        n = face.geometry.normal
        if abs(n.x) < 1e-6 and abs(n.y) < 1e-6 and n.z > 0:
            return face

    # Fall back to the face pointing most outward from the parent component's centre.
    comp = body.parentComponent
    comp_bb = comp.boundingBox
    cx = (comp_bb.minPoint.x + comp_bb.maxPoint.x) / 2.0
    cy = (comp_bb.minPoint.y + comp_bb.maxPoint.y) / 2.0
    cz = (comp_bb.minPoint.z + comp_bb.maxPoint.z) / 2.0

    best = candidates[0]
    best_outward = float("-inf")
    for face in candidates:
        pt = face.pointOnFace
        n = face.geometry.normal
        outward = (pt.x - cx) * n.x + (pt.y - cy) * n.y + (pt.z - cz) * n.z
        if outward > best_outward:
            best_outward = outward
            best = face
    return best


def compute_flat_rotation(normal: adsk.core.Vector3D) -> adsk.core.Matrix3D:
    """Return a Matrix3D that rotates *normal* to point upward (0,0,1)."""
    target = adsk.core.Vector3D.create(0.0, 0.0, 1.0)

    dot = normal.dotProduct(target)
    dot = max(-1.0, min(1.0, dot))

    if abs(dot - 1.0) < 1e-10:
        return adsk.core.Matrix3D.create()

    if abs(dot + 1.0) < 1e-10:
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
