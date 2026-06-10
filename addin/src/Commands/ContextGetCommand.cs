using Autodesk.Revit.DB;
using RevitMCP.Addin.Protocol;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `context.get` (docs/04 §4.1, FR-D6). Current selection + active view, so
/// Claude can resolve relative language like "this wall" / "this level".
/// </summary>
public sealed class ContextGetCommand : DocumentCommand
{
    public override string Method => "context.get";

    protected override RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request)
    {
        var doc = ctx.Doc;

        var selection = ctx.UIDoc.Selection.GetElementIds()
            .Select(id =>
            {
                var e = doc.GetElement(id);
                return new
                {
                    id = ModelRead.IdOf(id),
                    category = e?.Category?.Name,
                    type_name = e != null ? ModelRead.TypeName(doc, e) : null,
                };
            })
            .ToList();

        var view = doc.ActiveView;
        string? levelName = view is ViewPlan vp ? vp.GenLevel?.Name : null;

        var activeView = new
        {
            id = ModelRead.IdOf(view),
            name = view.Name,
            type = view.ViewType.ToString(),
            level = levelName,
        };

        return RpcResponse.Success(request.Id, new { selection, active_view = activeView });
    }
}
