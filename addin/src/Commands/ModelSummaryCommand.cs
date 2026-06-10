using Autodesk.Revit.DB;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>`model.summary` (docs/04 §4.1, FR-D1).</summary>
public sealed class ModelSummaryCommand : DocumentCommand
{
    public override string Method => "model.summary";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var doc = ctx.Doc;
        var u = DocUnits.From(doc);

        var levels = new FilteredElementCollector(doc)
            .OfClass(typeof(Level)).Cast<Level>()
            .OrderBy(l => l.Elevation)
            .Select(l => new { id = ModelRead.IdOf(l), name = l.Name, elevation = u.Len(l.Elevation) })
            .ToList();

        var counts = new Dictionary<string, int>();
        foreach (var name in CategoryMap.SummaryCategories)
        {
            if (!CategoryMap.TryResolve(name, out var bic)) continue;
            counts[name] = new FilteredElementCollector(doc)
                .OfCategory(bic).WhereElementIsNotElementType().GetElementCount();
        }

        double[]? basePoint = null;
        try
        {
            var bp = BasePoint.GetProjectBasePoint(doc);
            if (bp != null) basePoint = u.Pt3(bp.Position);
        }
        catch { /* base point not available */ }

        var result = new
        {
            project_title = doc.Title,
            units = new { length = u.LengthLabel, area = u.AreaLabel },
            project_base_point = basePoint,
            levels,
            category_counts = counts,
        };
        return RpcResponse.Success(request.Id, result);
    }
}
