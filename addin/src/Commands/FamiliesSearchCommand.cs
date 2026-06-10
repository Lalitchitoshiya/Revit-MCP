using System.Text.Json;
using Autodesk.Revit.DB;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `families.search` (docs/04 §4.1, FR-D4). Keyword search over loaded element
/// types (system + loadable), ranked. Returns nothing for unloaded families.
/// </summary>
public sealed class FamiliesSearchCommand : DocumentCommand
{
    public override string Method => "families.search";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var query = TypesListCommand.GetString(request.Params, "query") ?? "";
        var categoryFilter = TypesListCommand.GetString(request.Params, "category");
        var limit = GetInt(request.Params, "limit") ?? 10;

        var tokens = query.ToLowerInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries);
        CategoryMap.TryResolve(categoryFilter, out var bic);

        var collector = new FilteredElementCollector(ctx.Doc).WhereElementIsElementType();
        if (categoryFilter != null && bic != BuiltInCategory.INVALID)
            collector = collector.OfCategory(bic);

        var matches = collector.Cast<ElementType>()
            .Select(t => new
            {
                t,
                hay = $"{t.FamilyName} {t.Name}".ToLowerInvariant(),
            })
            .Select(x => new { x.t, score = Score(x.hay, tokens) })
            .Where(x => x.score > 0)
            .OrderByDescending(x => x.score)
            .Take(limit)
            .Select(x => new
            {
                id = ModelRead.IdOf(x.t),
                family_name = x.t.FamilyName,
                type_name = x.t.Name,
                category = x.t.Category?.Name,
                score = Math.Round(x.score, 3),
            })
            .ToList();

        var hint = matches.Count == 0
            ? "No loaded type matched. The family may need to be loaded into the project first."
            : null;

        return RpcResponse.Success(request.Id, new { query, results = matches, hint });
    }

    /// <summary>Fraction of query tokens present, with a bonus for whole-string containment.</summary>
    private static double Score(string hay, string[] tokens)
    {
        if (tokens.Length == 0) return 0;
        var hits = tokens.Count(hay.Contains);
        if (hits == 0) return 0;
        var basic = (double)hits / tokens.Length;
        var phrase = hay.Contains(string.Join(' ', tokens)) ? 0.25 : 0;
        return Math.Min(1.0, basic + phrase);
    }

    private static int? GetInt(JsonElement p, string name) =>
        p.ValueKind == JsonValueKind.Object && p.TryGetProperty(name, out var v) && v.TryGetInt32(out var i)
            ? i
            : null;
}
