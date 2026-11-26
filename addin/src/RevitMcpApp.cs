using System.Security.Cryptography;
using Autodesk.Revit.UI;
using RevitMCP.Addin.Auth;
using RevitMCP.Addin.Commands;
using RevitMCP.Addin.Diagnostics;
using RevitMCP.Addin.Server;
using RevitMCP.Addin.UI;

namespace RevitMCP.Addin;

/// <summary>
/// Entry point (docs/03 §3.7). On startup: create the ExternalEvent bridge,
/// start the loopback socket server with a fresh per-session token, publish
/// session.json, and add the "Revit MCP" ribbon tab. On shutdown: tear it all down.
///
/// The server can be paused/resumed from the ribbon (<see cref="StopServer"/> /
/// <see cref="StartServer"/>); resuming issues a new session token and port.
/// </summary>
public sealed class RevitMcpApp : IExternalApplication
{
    /// <summary>The running application (ribbon commands use it).</summary>
    public static RevitMcpApp? Current { get; private set; }

    private ExternalEvent? _externalEvent;
    private RequestQueue? _queue;
    private SocketServer? _server;
    private string? _revitVersion;
    private readonly object _gate = new();

    public SocketServer? Server => _server;
    public bool IsRunning => _server != null;
    public string? RevitVersion => _revitVersion;

    public Result OnStartup(UIControlledApplication application)
    {
        try
        {
            AddinLog.Init();
            _revitVersion = application.ControlledApplication.VersionNumber;
            AddinLog.Info($"{Product.Name} {Product.Version} starting (Revit {_revitVersion}, add-in at {Product.AddinDirectory}).");
            FirstRun.Record();

            _queue = new RequestQueue();
            var handler = new RevitCommandHandler(_queue, CommandRegistry.CreateDefault());
            _externalEvent = ExternalEvent.Create(handler);
            Current = this;

            StartServer();
        }
        catch (Exception ex)
        {
            AddinLog.Error("RevitMCP failed to start", ex);
            return Result.Failed;
        }

        // The ribbon is convenience UI: a failure here must not stop the bridge.
        try { Ribbon.Create(application); }
        catch (Exception ex) { AddinLog.Error("Could not create the Revit MCP ribbon", ex); }

        // Installs that didn't come from our MSI (e.g. the Autodesk App Store
        // installer) never ran `setup register`; do it once per new version,
        // in the background, so Revit startup isn't delayed. Idempotent.
        if (FirstRun.IsFirstRunOfThisVersion && Product.ServerExe is { } exe)
        {
            Task.Run(() =>
            {
                var (code, output) = Shell.Run(exe, "setup register", TimeSpan.FromSeconds(90));
                AddinLog.Info($"First-run Claude registration (exit {code}): {output}");
            });
        }

        AddinLog.Info("RevitMCP started.");
        return Result.Succeeded;
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        try
        {
            StopServer();
            _externalEvent?.Dispose();
            Current = null;
            AddinLog.Info("RevitMCP shut down.");
        }
        catch (Exception ex)
        {
            AddinLog.Error("Error during shutdown", ex);
        }
        return Result.Succeeded;
    }

    /// <summary>Start listening (no-op if already running). New token + port each time.</summary>
    public void StartServer()
    {
        lock (_gate)
        {
            if (_server != null || _queue == null || _externalEvent == null) return;
            var token = GenerateToken();
            var validator = new TokenValidator(token); // session token + scoped tokens (auth.json)
            var server = new SocketServer(token, validator, _queue, _externalEvent);
            server.Start();
            SessionFile.Write(server.Port, token, _revitVersion);
            _server = server;
        }
    }

    /// <summary>Stop listening and disconnect the client; session.json is removed,
    /// so the MCP server reports "Revit not reachable" until resumed.</summary>
    public void StopServer()
    {
        lock (_gate)
        {
            if (_server == null) return;
            _server.Stop();
            _server = null;
            SessionFile.Delete();
        }
    }

    private static string GenerateToken()
    {
        var bytes = RandomNumberGenerator.GetBytes(32); // 256-bit (docs/06 §6.7)
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}
