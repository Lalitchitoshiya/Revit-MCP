using Autodesk.Revit.DB;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `grids.list` (docs/04 §4.1, FR-D2). Returns grids plus computed intersections
/// of non-parallel linear grids, so Claude can resolve "grid A-1" to a point.
/// </summary>
public sealed class GridsListCommand : DocumentCommand
{
    private const double ParallelEps = 1e-6;

    public override string Method => "grids.list";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var u = DocUnits.From(ctx.Doc);
        var grids = new FilteredElementCollector(ctx.Doc)
            .OfClass(typeof(Grid)).Cast<Grid>().ToList();

        var gridData = new List<object>();
        var lines = new List<(string Name, XYZ P, XYZ D)>();

        foreach (var g in grids)
        {
            var curve = g.Curve;
            var p0 = curve.GetEndPoint(0);
            var p1 = curve.GetEndPoint(1);
            var isLine = curve is Line;
            gridData.Add(new
            {
                id = ModelRead.IdOf(g),
                name = g.Name,
                kind = isLine ? "line" : "arc",
                start = u.Pt2(p0),
                end = u.Pt2(p1),
            });
            if (isLine) lines.Add((g.Name, p0, (p1 - p0).Normalize()));
        }

        var intersections = new List<object>();
        for (var i = 0; i < lines.Count; i++)
        for (var j = i + 1; j < lines.Count; j++)
        {
            if (TryIntersectXY(lines[i].P, lines[i].D, lines[j].P, lines[j].D, out var pt))
            {
                intersections.Add(new
                {
                    grids = new[] { lines[i].Name, lines[j].Name },
                    point = u.Pt2(pt),
                });
            }
        }

        return RpcResponse.Success(request.Id, new { unit = u.LengthLabel, grids = gridData, intersections });
    }

    /// <summary>Infinite-line intersection in the XY plane; false if parallel.</summary>
    private static bool TryIntersectXY(XYZ p1, XYZ d1, XYZ p2, XYZ d2, out XYZ point)
    {
        point = XYZ.Zero;
        var det = d1.X * (-d2.Y) - (-d2.X) * d1.Y;
        if (Math.Abs(det) < ParallelEps) return false;

        var bx = p2.X - p1.X;
        var by = p2.Y - p1.Y;
        var t = (bx * (-d2.Y) - (-d2.X) * by) / det;
        point = new XYZ(p1.X + t * d1.X, p1.Y + t * d1.Y, 0);
        return true;
    }
}
