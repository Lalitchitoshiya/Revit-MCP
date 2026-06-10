using System.Text.Json;
using Autodesk.Revit.DB;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>`types.list` (docs/04 §4.1, FR-D3). Lists placeable types for a category.</summary>
public sealed class TypesListCommand : DocumentCommand
{
    public override string Method => "types.list";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var category = GetString(request.Params, "category");
        if (!CategoryMap.TryResolve(category, out var bic))
        {
            return RpcResponse.Failure(request.Id, ErrorCodes.InvalidParams,
                $"Unknown or missing category '{category}'.",
                "Use one of: walls, doors, windows, floors, rooms, grids, levels.");
        }

        var types = new FilteredElementCollector(ctx.Doc)
            .OfCategory(bic).WhereElementIsElementType().Cast<ElementType>()
            .Select(t => new
            {
                id = ModelRead.IdOf(t),
                family_name = t.FamilyName,
                type_name = t.Name,
                // System types are always placeable; family symbols may need
                // activation at placement time but are still selectable here.
                is_active = t is not FamilySymbol fs || fs.IsActive,
            })
            .OrderBy(t => t.family_name).ThenBy(t => t.type_name)
            .ToList();

        return RpcResponse.Success(request.Id, new { category, types });
    }

    internal static string? GetString(JsonElement p, string name) =>
        p.ValueKind == JsonValueKind.Object && p.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString()
            : null;
}
