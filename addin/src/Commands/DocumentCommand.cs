using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// Base for commands that need an open document. Resolves the active document
/// (or returns NO_ACTIVE_DOCUMENT) so each command only handles its own logic.
/// </summary>
public abstract class DocumentCommand : ICommand
{
    public abstract string Method { get; }

    public RpcResponse Execute(CommandContext ctx, RpcRequest request)
    {
        var uidoc = ctx.App.ActiveUIDocument;
        var doc = uidoc?.Document;
        if (doc == null)
        {
            return RpcResponse.Failure(request.Id, ErrorCodes.NoActiveDocument,
                "No active Revit document.", "Open a project in Revit and retry.");
        }
        return ExecuteOnDocument(new DocumentContext(ctx.App, uidoc!, doc), request);
    }

    protected abstract RpcResponse ExecuteOnDocument(DocumentContext ctx, RpcRequest request);
}

/// <summary>Context with a guaranteed-open document.</summary>
public sealed class DocumentContext
{
    public DocumentContext(UIApplication app, UIDocument uiDoc, Document doc)
    {
        App = app;
        UIDoc = uiDoc;
        Doc = doc;
    }

    public UIApplication App { get; }
    public UIDocument UIDoc { get; }
    public Document Doc { get; }
}
