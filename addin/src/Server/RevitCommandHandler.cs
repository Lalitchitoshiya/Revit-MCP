using System.Diagnostics;
using Autodesk.Revit.UI;
using RevitMCP.Addin.Commands;
using RevitMCP.Addin.Diagnostics;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Server;

/// <summary>
/// The single bridge onto Revit's UI thread (docs/03 §3.2). Revit invokes
/// <see cref="Execute"/> in a valid API context after the socket thread calls
/// ExternalEvent.Raise(). It drains the queue, runs each command, and signals
/// the waiting socket thread. This is the ONLY place the Revit API is touched.
/// </summary>
public sealed class RevitCommandHandler : IExternalEventHandler
{
    private readonly RequestQueue _queue;
    private readonly CommandRegistry _registry;

    public RevitCommandHandler(RequestQueue queue, CommandRegistry registry)
    {
        _queue = queue;
        _registry = registry;
    }

    public string GetName() => "RevitMCP.CommandHandler";

    public void Execute(UIApplication app)
    {
        var ctx = new CommandContext(app);

        while (_queue.TryDequeue(out var pending))
        {
            var req = pending.Request;
            var sw = Stopwatch.StartNew();
            RpcResponse response;
            try
            {
                if (!_registry.TryGet(req.Method, out var command))
                {
                    response = RpcResponse.Failure(req.Id, ErrorCodes.UnknownMethod,
                        $"Unknown method '{req.Method}'.");
                }
                else
                {
                    response = command.Execute(ctx, req);
                }
            }
            catch (Exception ex)
            {
                AddinLog.Error($"Command '{req.Method}' threw", ex);
                response = RpcResponse.Failure(req.Id, ErrorCodes.InternalError, ex.Message);
            }

            sw.Stop();
            AddinLog.Request(req.Id, req.Method, sw.ElapsedMilliseconds,
                response.Ok ? "ok" : response.Error?.Code ?? "error");
            pending.Complete(response);
        }
    }
}
