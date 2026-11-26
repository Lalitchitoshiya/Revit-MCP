using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Autodesk.Revit.UI;
using RevitMCP.Addin.Audit;
using RevitMCP.Addin.Auth;
using RevitMCP.Addin.Diagnostics;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Server;

/// <summary>
/// Loopback TCP server (docs/05). Runs on a background thread and NEVER touches
/// the Revit API (NFR-1): it parses requests, enqueues them, raises the
/// ExternalEvent, and waits (bounded) for the UI thread to produce a response.
///
/// Newline-delimited JSON framing, one client at a time. Every request is
/// authenticated (session or scoped token, see <see cref="TokenValidator"/>) and
/// authorised against the method's scope (<see cref="Scopes"/>); denials are
/// written to the audit log.
/// </summary>
public sealed class SocketServer
{
    private const int RequestTimeoutMs = 30_000;   // NFR-7 bounded wait → REVIT_BUSY_TIMEOUT
    private const int MutationTimeoutMs = 120_000; // commit/undo (matches server COMMIT_TIMEOUT_S)
    private const int RunningGraceMs = 600_000;    // a mutation already running is allowed to finish

    private readonly string _token;
    private readonly TokenValidator _validator;
    private readonly RequestQueue _queue;
    private readonly ExternalEvent _externalEvent;

    private TcpListener? _listener;
    private Thread? _acceptThread;
    private volatile bool _running;
    private volatile TcpClient? _current;
    private long _requestsServed;

    public int Port { get; private set; }

    // Read by the ribbon's Status dialog (any thread; values are informational).
    public bool ClientConnected => _current != null;
    public string? ClientIdentity { get; private set; }
    public DateTime? ClientConnectedAt { get; private set; }
    public long RequestsServed => Interlocked.Read(ref _requestsServed);
    // Claude connects once per request and disconnects, so "last request" is the
    // meaningful liveness signal, not "connected now".
    public DateTime? LastRequestAt { get; private set; }
    public string? LastClientIdentity { get; private set; }

    public SocketServer(string token, TokenValidator validator, RequestQueue queue, ExternalEvent externalEvent)
    {
        _token = token;
        _validator = validator;
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
        // Drop the connected client too (ribbon "Pause"), not just the listener.
        try { _current?.Close(); } catch { /* ignore */ }
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
            _current = client;
            try { HandleClient(client); }
            catch (IOException) when (!_running) { /* closed by Stop() (pause/shutdown) */ }
            catch (ObjectDisposedException) when (!_running) { }
            catch (Exception ex) { AddinLog.Error("Client handler crashed", ex); }
            finally
            {
                _current = null;
                ClientIdentity = null;
                ClientConnectedAt = null;
                try { client.Close(); } catch { }
            }
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
        try
        {
            var who = _validator.Verify(hello.Token);
            AddinLog.Info($"Handshake ok: {who.Kind} sub={who.Sub} scopes=[{string.Join(",", who.Scopes)}]");
            ClientIdentity = who.Kind == "session" ? "full access (session token)"
                : $"{who.Sub} [{string.Join(", ", who.Scopes)}]";
            ClientConnectedAt = DateTime.Now;
        }
        catch (AuthException ex)
        {
            AuditDenied("handshake", hello.Token, ex.Code, ex.Message);
            WriteHandshakeError(writer, ex.Code);
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

            // Re-verify on every request: tokens can expire, be revoked, or have
            // their key rotated out while a connection is open.
            Principal principal;
            try { principal = _validator.Verify(req.Token); }
            catch (AuthException ex)
            {
                AuditDenied(req.Method, req.Token, ex.Code, ex.Message);
                WriteResponse(writer, RpcResponse.Failure(req.Id, ex.Code, ex.Message,
                    "Issue a fresh token: revit-mcp-server auth issue ... (developer: python -m revit_mcp.auth issue)"));
                continue;
            }
            var need = Scopes.RequiredFor(req.Method);
            if (!principal.Can(need))
            {
                var msg = $"Token '{principal.Sub}' (scopes: {string.Join(", ", principal.Scopes)}) may not call '{req.Method}'; it needs '{need}'.";
                AuditDenied(req.Method, req.Token, ErrorCodes.ScopeDenied, msg, principal);
                WriteResponse(writer, RpcResponse.Failure(req.Id, ErrorCodes.ScopeDenied, msg,
                    "Use a client configured with a model:write token for changes."));
                continue;
            }
            req.Principal = principal;

            var response = Dispatch(req);
            Interlocked.Increment(ref _requestsServed);
            LastRequestAt = DateTime.Now;
            LastClientIdentity = ClientIdentity;
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

        var isMutation = Scopes.RequiredFor(req.Method) == Scopes.Write;
        var timeoutMs = isMutation ? MutationTimeoutMs : RequestTimeoutMs;
        if (pending.Done.Wait(timeoutMs)) return pending.Response!;

        if (pending.TryCancel())
        {
            // Never started: it is cancelled and will be skipped, so the client's
            // "timed out" is the truth — nothing was (or will be) applied.
            AddinLog.Warn($"Request id={req.Id} method={req.Method} timed out after {timeoutMs}ms; cancelled before it ran.");
            return RpcResponse.Failure(req.Id, ErrorCodes.RevitBusyTimeout,
                "Revit did not start the request in time; it was cancelled and NOT applied.",
                "Revit may be busy or showing a modal dialog. Close any dialogs and retry.");
        }

        // Already running on the UI thread: let it finish rather than report a
        // result we don't know.
        AddinLog.Warn($"Request id={req.Id} method={req.Method} still running after {timeoutMs}ms; waiting for it to finish.");
        if (pending.Done.Wait(RunningGraceMs)) return pending.Response!;
        return RpcResponse.Failure(req.Id, ErrorCodes.RevitBusyTimeout,
            "Revit started the request but has not finished it; its outcome is unknown.",
            "Check Revit for an open dialog, then check the audit log / model before retrying.");
    }

    private static void AuditDenied(string? method, string? token, string code, string reason, Principal? who = null) =>
        AuditLog.Append("auth.denied", code, new
        {
            method,
            reason,
            principal = who?.ToAudit() ?? TokenValidator.DescribeUnverified(token),
            os_user = Environment.UserName,
            machine = Environment.MachineName,
        });

    /// <summary>
    /// Run a health.check through the bridge to learn live version/document state
    /// for the welcome message. Falls back to an empty welcome if Revit is busy.
    /// </summary>
    private WelcomeMessage ProbeDocumentState()
    {
        var probe = Dispatch(new RpcRequest
        {
            Id = "hello", Token = _token, Method = "health.check",
            Principal = new Principal { Kind = "internal", Sub = "handshake-probe", Scopes = new[] { Scopes.Read } },
        });
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
