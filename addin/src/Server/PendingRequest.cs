using System.Collections.Concurrent;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Server;

/// <summary>
/// A request handed from the socket thread to the Revit UI thread (docs/03 §3.2).
/// The socket thread waits on <see cref="Done"/> with a timeout; the
/// ExternalEvent handler fills <see cref="Response"/> and signals it.
///
/// State machine (prevents "ghost" commits): a request the client has already
/// been told timed out must NEVER run later when Revit becomes idle.
///   Queued --TryStart (UI thread)--> Running --Complete--> done
///   Queued --TryCancel (socket thread, on timeout)--> Cancelled (skipped)
/// Exactly one of TryStart / TryCancel wins.
/// </summary>
public sealed class PendingRequest
{
    private const int Queued = 0, Running = 1, Cancelled = 2;
    private int _state = Queued;

    public PendingRequest(RpcRequest request) => Request = request;

    public RpcRequest Request { get; }
    public RpcResponse? Response { get; private set; }
    public ManualResetEventSlim Done { get; } = new(initialState: false);

    /// <summary>UI thread: claim the request. False = it was cancelled; skip it.</summary>
    public bool TryStart() => Interlocked.CompareExchange(ref _state, Running, Queued) == Queued;

    /// <summary>Socket thread: cancel if not yet started. False = it is already running.</summary>
    public bool TryCancel() => Interlocked.CompareExchange(ref _state, Cancelled, Queued) == Queued;

    public void Complete(RpcResponse response)
    {
        Response = response;
        Done.Set();
    }
}

/// <summary>Thread-safe FIFO of pending requests drained on the UI thread.</summary>
public sealed class RequestQueue
{
    private readonly ConcurrentQueue<PendingRequest> _queue = new();

    public void Enqueue(PendingRequest request) => _queue.Enqueue(request);

    public bool TryDequeue(out PendingRequest request) => _queue.TryDequeue(out request!);
}
