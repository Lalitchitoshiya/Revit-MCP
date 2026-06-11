using Autodesk.Revit.DB;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Plans.Actions;

/// <summary>
/// `place_wall` (docs/04 §4.3, FR-E1): a straight wall from start to end on a
/// level, of a given wall type, with a height and optional base offset.
/// </summary>
public sealed class WallActionHandler : IActionHandler
{
    private const double MinLengthFeet = 0.01;          // ~3mm: below this is degenerate
    private const double ShortWarnFeet = 1.0;           // ~305mm: warn but allow
    private static readonly double DefaultHeightFeet = 3000.0 / 304.8; // 3 m if unspecified

    public string Op => "place_wall";

    public ActionPreview Preview(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles)
    {
        var r = new ActionPreview();
        var p = action.Params;

        var haveStart = PlanJson.TryPoint(p, "start", u, out var start, out var d1);
        if (!haveStart) r.Add(d1!);
        var haveEnd = PlanJson.TryPoint(p, "end", u, out var end, out var d2);
        if (!haveEnd) r.Add(d2!);

        var haveType = PlanJson.TryResolveType(doc, p, "type", BuiltInCategory.OST_Walls, out var typeId, out var d3);
        if (!haveType) r.Add(d3!);

        var haveLevel = PlanJson.TryResolveLevel(doc, p, "level", out var level, out var d4);
        if (!haveLevel) r.Add(d4!);

        double heightFeet = DefaultHeightFeet;
        if (PlanJson.TryLength(p, "height", u, required: false, out var h, out var dh)) heightFeet = h;
        else if (dh != null) r.Add(dh);

        if (PlanJson.TryLength(p, "base_offset", u, required: false, out _, out var dbo) is false && dbo != null)
            r.Add(dbo);

        if (haveStart && haveEnd)
        {
            var lengthFeet = start.DistanceTo(end);
            if (lengthFeet < MinLengthFeet)
                r.Add(Diagnostic.Error(DiagCodes.ZeroLength, "Wall start and end are the same point."));
            else if (lengthFeet < ShortWarnFeet)
                r.Add(Diagnostic.Warning(DiagCodes.WallVeryShort,
                    $"Wall is only {u.Len(lengthFeet)} {u.LengthLabel} long."));

            r.Preview = new
            {
                length = new { value = u.Len(lengthFeet), unit = u.LengthLabel },
                height = new { value = u.Len(heightFeet), unit = u.LengthLabel },
            };
        }

        r.Resolved = new
        {
            type_id = haveType ? typeId.Value : (long?)null,
            level_id = haveLevel ? level!.Id.Value : (long?)null,
            level_name = level?.Name,
        };
        return r;
    }

    public ActionResult Execute(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles)
    {
        var p = action.Params;

        if (!PlanJson.TryPoint(p, "start", u, out var start, out var e1)) throw new InvalidOperationException(e1!.Message);
        if (!PlanJson.TryPoint(p, "end", u, out var end, out var e2)) throw new InvalidOperationException(e2!.Message);
        if (!PlanJson.TryResolveType(doc, p, "type", BuiltInCategory.OST_Walls, out var typeId, out var e3))
            throw new InvalidOperationException(e3!.Message);
        if (!PlanJson.TryResolveLevel(doc, p, "level", out var level, out var e4))
            throw new InvalidOperationException(e4!.Message);

        var heightFeet = PlanJson.TryLength(p, "height", u, false, out var h, out _) ? h : DefaultHeightFeet;
        var offsetFeet = PlanJson.TryLength(p, "base_offset", u, false, out var o, out _) ? o : 0.0;

        var z = level!.Elevation;
        var line = Line.CreateBound(new XYZ(start.X, start.Y, z), new XYZ(end.X, end.Y, z));

        var wall = Wall.Create(doc, line, typeId, level.Id, heightFeet, offsetFeet, flip: false, structural: false);
        return new ActionResult(wall.Id, "Walls");
    }
}
