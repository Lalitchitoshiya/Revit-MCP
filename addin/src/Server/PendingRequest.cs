using System.Collections.Concurrent;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Server;

/// <summary>
/// A request handed from the socket thread to the Revit UI thread (docs/03 §3.2).
/// The socket thread waits on <see cref="Done"/> with a timeout; the
/// ExternalEvent handler fills <see cref="Response"/> and signals it.
/// </summary>
public sealed class PendingRequest
{
    public PendingRequest(RpcRequest request) => Request = request;

    public RpcRequest Request { get; }
    public RpcResponse? Response { get; private set; }
    public ManualResetEventSlim Done { get; } = new(initialState: false);

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
