using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Autodesk.Revit.UI;
using RevitMCP.Addin.Diagnostics;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Server;

/// <summary>
/// Loopback TCP server (docs/05). Runs on a background thread and NEVER touches
/// the Revit API (NFR-1): it parses requests, enqueues them, raises the
/// ExternalEvent, and waits (bounded) for the UI thread to produce a response.
///
/// Newline-delimited JSON framing, one client at a time, per-session token auth.
/// </summary>
public sealed class SocketServer
{
    private const int RequestTimeoutMs = 30_000; // NFR-7 bounded wait → REVIT_BUSY_TIMEOUT

    private readonly string _token;
    private readonly RequestQueue _queue;
    private readonly ExternalEvent _externalEvent;

    private TcpListener? _listener;
    private Thread? _acceptThread;
    private volatile bool _running;

    public int Port { get; private set; }

    public SocketServer(string token, RequestQueue queue, ExternalEvent externalEvent)
    {
        _token = token;
        _queue = queue;
        _externalEvent = externalEvent;
    }

    public void Start()
    {
        // Bind to an ephemeral loopback port (NFR-3: 127.0.0.1 only) and publish it.
        _listener = new TcpListener(IPAddress.Loopback, 0);
        _listener.Start();
        Port = ((IPEndPoint)_listener.LocalEndpoint).Port;
        _running = true;

        _acceptThread = new Thread(AcceptLoop) { IsBackground = true, Name = "RevitMCP.Accept" };
        _acceptThread.Start();
        AddinLog.Info($"Socket server listening on 127.0.0.1:{Port}");
    }

    public void Stop()
    {
        _running = false;
        try { _listener?.Stop(); } catch { /* ignore */ }
        AddinLog.Info("Socket server stopped.");
    }

    private void AcceptLoop()
    {
        while (_running)
        {
            TcpClient client;
            try
            {
                client = _listener!.AcceptTcpClient();
            }
            catch (SocketException)
            {
                if (_running) AddinLog.Warn("Accept failed; continuing.");
                break;
            }
            catch (ObjectDisposedException)
            {
                break; // listener stopped
            }

            // One client at a time (docs/05 §5.1).
            try { HandleClient(client); }
            catch (Exception ex) { AddinLog.Error("Client handler crashed", ex); }
            finally { try { client.Close(); } catch { } }
        }
    }

    private void HandleClient(TcpClient client)
    {
        using var stream = client.GetStream();
        using var reader = new StreamReader(stream, Encoding.UTF8);
        using var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" };

        AddinLog.Info("Client connected.");

        // --- Handshake (docs/05 §5.2) ---
        var helloLine = reader.ReadLine();
        if (helloLine == null) return;

        HelloMessage? hello;
        try { hello = JsonSerializer.Deserialize<HelloMessage>(helloLine, Wire.Json); }
        catch { WriteHandshakeError(writer, ErrorCodes.InvalidParams); return; }

        if (hello?.Type != "hello" || !Wire.IsCompatible(hello.ProtocolVersion))
        {
            WriteHandshakeError(writer, ErrorCodes.VersionIncompatible);
            return;
        }
        if (!TokenMatches(hello.Token))
        {
            WriteHandshakeError(writer, ErrorCodes.BadToken);
            return;
        }

        // Probe live doc state via the bridge so the welcome is accurate (docs/05 §5.2).
        WriteWelcome(writer, ProbeDocumentState());

        // --- Request loop (docs/05 §5.3) ---
        string? line;
        while (_running && (line = reader.ReadLine()) != null)
        {
            if (line.Length == 0) continue;

            RpcRequest? req;
            try { req = JsonSerializer.Deserialize<RpcRequest>(line, Wire.Json); }
            catch
            {
                WriteResponse(writer, RpcResponse.Failure(null, ErrorCodes.InvalidParams, "Malformed JSON request."));
                continue;
            }
            if (req == null) continue;

            if (!TokenMatches(req.Token))
            {
                WriteResponse(writer, RpcResponse.Failure(req.Id, ErrorCodes.BadToken, "Invalid or missing token."));
                continue;
            }

            var response = Dispatch(req);
            WriteResponse(writer, response);
        }

        AddinLog.Info("Client disconnected.");
    }

    /// <summary>
    /// Marshal one request onto the UI thread and wait (bounded) for its result.
    /// </summary>
    private RpcResponse Dispatch(RpcRequest req)
    {
        var pending = new PendingRequest(req);
        _queue.Enqueue(pending);
        _externalEvent.Raise(); // serviced by Revit on the UI thread when idle

        if (!pending.Done.Wait(RequestTimeoutMs))
        {
            // UI thread never serviced us in time (e.g. modal dialog open) — NFR-7.
            AddinLog.Warn($"Request id={req.Id} method={req.Method} timed out after {RequestTimeoutMs}ms.");
            return RpcResponse.Failure(req.Id, ErrorCodes.RevitBusyTimeout,
                "Revit did not service the request in time.",
                "Revit may be busy or showing a modal dialog. Close any dialogs and retry.");
        }

        return pending.Response!;
    }

    private bool TokenMatches(string? candidate) =>
        !string.IsNullOrEmpty(candidate) &&
        System.Security.Cryptography.CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(candidate), Encoding.UTF8.GetBytes(_token));

    /// <summary>
    /// Run a health.check through the bridge to learn live version/document state
    /// for the welcome message. Falls back to an empty welcome if Revit is busy.
    /// </summary>
    private WelcomeMessage ProbeDocumentState()
    {
        var probe = Dispatch(new RpcRequest { Id = "hello", Token = _token, Method = "health.check" });
        var welcome = new WelcomeMessage();
        if (!probe.Ok || probe.Result == null) return welcome;

        try
        {
            var el = JsonSerializer.SerializeToElement(probe.Result, Wire.Json);
            if (el.TryGetProperty("revit_version", out var v) && v.ValueKind == JsonValueKind.String)
                welcome.RevitVersion = v.GetString();
            if (el.TryGetProperty("document_open", out var o) &&
                (o.ValueKind == JsonValueKind.True || o.ValueKind == JsonValueKind.False))
                welcome.DocumentOpen = o.GetBoolean();
            if (el.TryGetProperty("document_title", out var t) && t.ValueKind == JsonValueKind.String)
                welcome.DocumentTitle = t.GetString();
        }
        catch (Exception ex)
        {
            AddinLog.Warn($"Could not parse health probe for welcome: {ex.Message}");
        }
        return welcome;
    }

    private static void WriteWelcome(TextWriter writer, WelcomeMessage welcome) =>
        writer.WriteLine(JsonSerializer.Serialize(welcome, Wire.Json));

    private static void WriteHandshakeError(TextWriter writer, string code)
    {
        AddinLog.Warn($"Handshake rejected: {code}");
        writer.WriteLine(JsonSerializer.Serialize(new HandshakeError { Code = code }, Wire.Json));
    }

    private static void WriteResponse(TextWriter writer, RpcResponse response) =>
        writer.WriteLine(JsonSerializer.Serialize(response, Wire.Json));
}
