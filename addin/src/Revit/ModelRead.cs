using Autodesk.Revit.DB;

namespace RevitMCP.Addin.Revit;

/// <summary>Read-only helpers shared by the discovery commands (Phase 1).</summary>
public static class ModelRead
{
    public static long IdOf(Element e) => e.Id.Value;

    public static long IdOf(ElementId id) => id.Value;

    public static ElementId ToElementId(long value) => new(value);

    public static string? LevelName(Document doc, ElementId levelId)
    {
        if (levelId == ElementId.InvalidElementId) return null;
        return doc.GetElement(levelId) is Level lvl ? lvl.Name : null;
    }

    /// <summary>Best-effort type name for an instance or type element.</summary>
    public static string? TypeName(Document doc, Element e)
    {
        if (e is ElementType et) return et.Name;
        var typeId = e.GetTypeId();
        return typeId != ElementId.InvalidElementId && doc.GetElement(typeId) is ElementType t ? t.Name : null;
    }

    /// <summary>Category-appropriate geometry summary (docs/04 §4.1 query_elements).</summary>
    public static object GeometrySummary(Document doc, Element e, DocUnits u)
    {
        switch (e)
        {
            case Wall wall when wall.Location is LocationCurve lc && lc.Curve is Line line:
                return new
                {
                    kind = "wall",
                    line = new[] { u.Pt2(line.GetEndPoint(0)), u.Pt2(line.GetEndPoint(1)) },
                    height = TryLen(wall, BuiltInParameter.WALL_USER_HEIGHT_PARAM, u),
                    // Exterior-face normal in plan, to disambiguate "the north wall" etc.
                    facing = WallFacing(wall),
                };

            case FamilyInstance fi:
                return new
                {
                    kind = "instance",
                    host_id = fi.Host != null ? IdOf(fi.Host) : (long?)null,
                    location = (fi.Location as LocationPoint)?.Point is { } p ? u.Pt2(p) : null,
                };

            case Floor floor:
                return new { kind = "floor", area = TryLen(floor, BuiltInParameter.HOST_AREA_COMPUTED, u, isArea: true) };
        }

        // Rooms (SpatialElement) and generic fallback.
        if (e.Category?.Id.Value == (long)BuiltInCategory.OST_Rooms)
        {
            return new
            {
                kind = "room",
                area = TryLen(e, BuiltInParameter.ROOM_AREA, u, isArea: true),
                name = e.Name,
                number = e.get_Parameter(BuiltInParameter.ROOM_NUMBER)?.AsString(),
            };
        }

        var bb = e.get_BoundingBox(null);
        return new
        {
            kind = "bbox",
            center = bb != null ? u.Pt3((bb.Min + bb.Max) * 0.5) : null,
        };
    }

    /// <summary>Exterior-face normal as [x, y] + a cardinal label, for spatial language.</summary>
    private static object? WallFacing(Wall wall)
    {
        try
        {
            var n = wall.Orientation;
            return new { x = Math.Round(n.X, 3), y = Math.Round(n.Y, 3), cardinal = Cardinal(n.X, n.Y) };
        }
        catch { return null; }
    }

    private static string Cardinal(double x, double y)
    {
        if (Math.Abs(x) >= Math.Abs(y)) return x >= 0 ? "east" : "west";
        return y >= 0 ? "north" : "south";
    }

    private static double? TryLen(Element e, BuiltInParameter bip, DocUnits u, bool isArea = false)
    {
        var p = e.get_Parameter(bip);
        if (p == null || p.StorageType != StorageType.Double) return null;
        var v = p.AsDouble();
        return isArea ? u.Area(v) : u.Len(v);
    }
}
