using Autodesk.Revit.DB;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Plans.Actions;

/// <summary>`place_floor` (docs/04 §4.3, FR-E4): a floor from a closed boundary
/// loop on a level, of a given floor type.</summary>
public sealed class FloorActionHandler : IActionHandler
{
    public string Op => "place_floor";
    public string ProducedCategory => "floors";

    public ActionPreview Preview(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, string> handleCategories)
    {
        var r = new ActionPreview();
        var p = action.Params;

        var haveBoundary = PlanJson.TryPointList(p, "boundary", u, out var pts, out var bErr);
        if (!haveBoundary) r.Add(bErr!);
        else if (pts.Count < 3) r.Add(Diagnostic.Error(DiagCodes.InvalidBoundary, "A floor needs at least 3 points."));

        var haveType = PlanJson.TryResolveType(doc, p, "type", BuiltInCategory.OST_Floors, out var typeId, out var tErr);
        if (!haveType) r.Add(tErr!);
        var haveLevel = PlanJson.TryResolveLevel(doc, p, "level", out var level, out var lErr);
        if (!haveLevel) r.Add(lErr!);

        if (haveBoundary && pts.Count >= 3)
        {
            var area = PolygonAreaSqFt(pts);
            r.Preview = new { area = new { value = u.Area(area), unit = u.AreaLabel }, points = pts.Count };
        }
        r.Resolved = new { type_id = haveType ? typeId.Value : (long?)null, level_id = haveLevel ? level!.Id.Value : (long?)null };
        return r;
    }

    public ActionResult Execute(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles)
    {
        var p = action.Params;
        if (!PlanJson.TryPointList(p, "boundary", u, out var pts, out var e1)) throw new InvalidOperationException(e1!.Message);
        if (pts.Count < 3) throw new InvalidOperationException("A floor needs at least 3 points.");
        if (!PlanJson.TryResolveType(doc, p, "type", BuiltInCategory.OST_Floors, out var typeId, out var e2))
            throw new InvalidOperationException(e2!.Message);
        if (!PlanJson.TryResolveLevel(doc, p, "level", out var level, out var e3))
            throw new InvalidOperationException(e3!.Message);

        var z = level!.Elevation;
        var loop = new CurveLoop();
        for (var i = 0; i < pts.Count; i++)
        {
            var a = new XYZ(pts[i].X, pts[i].Y, z);
            var b = new XYZ(pts[(i + 1) % pts.Count].X, pts[(i + 1) % pts.Count].Y, z);
            loop.Append(Line.CreateBound(a, b));
        }

        var floor = Floor.Create(doc, new List<CurveLoop> { loop }, typeId, level.Id);
        return new ActionResult(floor.Id, "Floors");
    }

    private static double PolygonAreaSqFt(IReadOnlyList<XYZ> pts)
    {
        double sum = 0;
        for (var i = 0; i < pts.Count; i++)
        {
            var a = pts[i];
            var b = pts[(i + 1) % pts.Count];
            sum += a.X * b.Y - b.X * a.Y;
        }
        return Math.Abs(sum) / 2.0;
    }
}
