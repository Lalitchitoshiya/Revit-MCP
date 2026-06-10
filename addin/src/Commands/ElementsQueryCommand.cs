using System.Text.Json;
using Autodesk.Revit.DB;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `elements.query` (docs/04 §4.1, FR-D5). Filters existing instances by
/// category / level / proximity / ids and returns a geometry summary each.
/// Results are capped to keep payloads bounded.
/// </summary>
public sealed class ElementsQueryCommand : DocumentCommand
{
    private const int DefaultLimit = 200;

    public override string Method => "elements.query";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var doc = ctx.Doc;
        var u = DocUnits.From(doc);
        var p = request.Params;
        var limit = GetInt(p, "limit") ?? DefaultLimit;

        IEnumerable<Element> source;

        var ids = GetLongArray(p, "ids");
        if (ids.Count > 0)
        {
            source = ids.Select(id => doc.GetElement(ModelRead.ToElementId(id))).Where(e => e != null)!;
        }
        else
        {
            var collector = new FilteredElementCollector(doc).WhereElementIsNotElementType();
            var category = TypesListCommand.GetString(p, "category");
            if (category != null)
            {
                if (!CategoryMap.TryResolve(category, out var bic))
                    return RpcResponse.Failure(request.Id, ErrorCodes.InvalidParams, $"Unknown category '{category}'.");
                collector = collector.OfCategory(bic);
            }
            source = collector;
        }

        // Optional level filter (by name or id).
        var levelName = TypesListCommand.GetString(p, "level");
        var levelId = GetInt(p, "level_id");
        ElementId? wantLevel = ResolveLevel(doc, levelName, levelId);
        if (wantLevel != null)
            source = source.Where(e => e.LevelId == wantLevel);

        // Optional proximity filter (point in model units, radius in model units).
        var near = GetDoubleArray(p, "near_point");
        var radius = GetDouble(p, "radius");
        if (near.Count >= 2 && radius is { } r)
        {
            var center = new XYZ(u.ToFeet(near[0]), u.ToFeet(near[1]), 0);
            var rFeet = u.ToFeet(r);
            source = source.Where(e => WithinXY(e, center, rFeet));
        }

        var truncated = false;
        var list = new List<object>();
        foreach (var e in source)
        {
            if (list.Count >= limit) { truncated = true; break; }
            list.Add(new
            {
                id = ModelRead.IdOf(e),
                category = e.Category?.Name,
                type_name = ModelRead.TypeName(doc, e),
                level = ModelRead.LevelName(doc, e.LevelId),
                geometry = ModelRead.GeometrySummary(doc, e, u),
            });
        }

        return RpcResponse.Success(request.Id, new
        {
            unit = u.LengthLabel,
            count = list.Count,
            truncated,
            limit,
            elements = list,
        });
    }

    private static ElementId? ResolveLevel(Document doc, string? name, int? id)
    {
        if (id is { } i) return ModelRead.ToElementId(i);
        if (name == null) return null;
        var lvl = new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
            .FirstOrDefault(l => string.Equals(l.Name, name, StringComparison.OrdinalIgnoreCase));
        return lvl?.Id;
    }

    private static bool WithinXY(Element e, XYZ center, double rFeet)
    {
        XYZ? pt = e.Location switch
        {
            LocationPoint lp => lp.Point,
            LocationCurve lc => lc.Curve.Evaluate(0.5, true),
            _ => e.get_BoundingBox(null) is { } bb ? (bb.Min + bb.Max) * 0.5 : null,
        };
        if (pt == null) return false;
        var dx = pt.X - center.X;
        var dy = pt.Y - center.Y;
        return dx * dx + dy * dy <= rFeet * rFeet;
    }

    private static int? GetInt(JsonElement p, string name) =>
        p.ValueKind == JsonValueKind.Object && p.TryGetProperty(name, out var v) && v.TryGetInt32(out var i) ? i : null;

    private static double? GetDouble(JsonElement p, string name) =>
        p.ValueKind == JsonValueKind.Object && p.TryGetProperty(name, out var v) && v.TryGetDouble(out var d) ? d : null;

    private static List<long> GetLongArray(JsonElement p, string name)
    {
        var result = new List<long>();
        if (p.ValueKind == JsonValueKind.Object && p.TryGetProperty(name, out var arr) && arr.ValueKind == JsonValueKind.Array)
            foreach (var el in arr.EnumerateArray())
                if (el.TryGetInt64(out var v)) result.Add(v);
        return result;
    }

    private static List<double> GetDoubleArray(JsonElement p, string name)
    {
        var result = new List<double>();
        if (p.ValueKind == JsonValueKind.Object && p.TryGetProperty(name, out var arr) && arr.ValueKind == JsonValueKind.Array)
            foreach (var el in arr.EnumerateArray())
                if (el.TryGetDouble(out var v)) result.Add(v);
        return result;
    }
}
