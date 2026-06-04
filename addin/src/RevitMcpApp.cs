using System.Security.Cryptography;
using Autodesk.Revit.UI;
using RevitMCP.Addin.Commands;
using RevitMCP.Addin.Diagnostics;
using RevitMCP.Addin.Server;

namespace RevitMCP.Addin;

/// <summary>
/// Entry point (docs/03 §3.7). On startup: create the ExternalEvent bridge,
/// generate a per-session token, start the loopback socket server, and publish
/// session.json. On shutdown: tear it all down.
/// </summary>
public sealed class RevitMcpApp : IExternalApplication
{
    private ExternalEvent? _externalEvent;
    private SocketServer? _server;

    public Result OnStartup(UIControlledApplication application)
    {
        try
        {
            AddinLog.Init();
            AddinLog.Info($"RevitMCP starting (Revit {application.ControlledApplication.VersionNumber}).");

            var queue = new RequestQueue();
            var handler = new RevitCommandHandler(queue, CommandRegistry.CreateDefault());
            _externalEvent = ExternalEvent.Create(handler);

            var token = GenerateToken();
            _server = new SocketServer(token, queue, _externalEvent);
            _server.Start();

            SessionFile.Write(_server.Port, token, application.ControlledApplication.VersionNumber);

            AddinLog.Info("RevitMCP started.");
            return Result.Succeeded;
        }
        catch (Exception ex)
        {
            AddinLog.Error("RevitMCP failed to start", ex);
            return Result.Failed;
        }
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        try
        {
            _server?.Stop();
            _externalEvent?.Dispose();
            SessionFile.Delete();
            AddinLog.Info("RevitMCP shut down.");
        }
        catch (Exception ex)
        {
            AddinLog.Error("Error during shutdown", ex);
        }
        return Result.Succeeded;
    }

    private static string GenerateToken()
    {
        var bytes = RandomNumberGenerator.GetBytes(32); // 256-bit (docs/06 §6.7)
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}
