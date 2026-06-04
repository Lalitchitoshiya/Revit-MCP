using Autodesk.Revit.UI;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Commands;

/// <summary>Context passed to a command, executing on the Revit UI thread.</summary>
public sealed class CommandContext
{
    public CommandContext(UIApplication app) => App = app;

    public UIApplication App { get; }
}

/// <summary>
/// A single protocol method (docs/05 §5.4). Implementations run inside the
/// ExternalEvent handler on the UI thread, in a valid Revit API context.
/// </summary>
public interface ICommand
{
    /// <summary>Wire method name, e.g. "health.check".</summary>
    string Method { get; }

    RpcResponse Execute(CommandContext ctx, RpcRequest request);
}
