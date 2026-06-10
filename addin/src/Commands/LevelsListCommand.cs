using Autodesk.Revit.DB;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>`levels.list` (docs/04 §4.1, FR-D2).</summary>
public sealed class LevelsListCommand : DocumentCommand
{
    public override string Method => "levels.list";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var u = DocUnits.From(ctx.Doc);
        var levels = new FilteredElementCollector(ctx.Doc)
            .OfClass(typeof(Level)).Cast<Level>()
            .OrderBy(l => l.Elevation)
            .Select(l => new { id = ModelRead.IdOf(l), name = l.Name, elevation = u.Len(l.Elevation) })
            .ToList();

        return RpcResponse.Success(request.Id, new { unit = u.LengthLabel, levels });
    }
}
