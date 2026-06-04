using System.Text.Json;
using System.Text.Json.Serialization;

namespace RevitMCP.Addin.Protocol;

/// <summary>
/// Wire DTOs for the add-in protocol (docs/05-addin-protocol.md).
/// All messages are newline-delimited JSON, snake_case on the wire.
/// </summary>
public static class Wire
{
    public const string ProtocolVersion = "1.0";

    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    /// <summary>Major version compatibility check (docs/05 §5.8).</summary>
    public static bool IsCompatible(string? clientVersion)
    {
        if (string.IsNullOrWhiteSpace(clientVersion)) return false;
        var theirs = clientVersion.Split('.')[0];
        var ours = ProtocolVersion.Split('.')[0];
        return theirs == ours;
    }
}

/// <summary>First message from the client on connect.</summary>
public sealed class HelloMessage
{
    public string? Type { get; set; }
    public string? ProtocolVersion { get; set; }
    public string? Token { get; set; }
}

/// <summary>Add-in's reply to a successful handshake.</summary>
public sealed class WelcomeMessage
{
    public string Type { get; set; } = "welcome";
    public string ProtocolVersion { get; set; } = Wire.ProtocolVersion;
    public string? RevitVersion { get; set; }
    public bool DocumentOpen { get; set; }
    public string? DocumentTitle { get; set; }
}

/// <summary>Add-in's reply to a failed handshake (then the socket is closed).</summary>
public sealed class HandshakeError
{
    public string Type { get; set; } = "error";
    public string Code { get; set; } = "";
}

/// <summary>A method request (docs/05 §5.3).</summary>
public sealed class RpcRequest
{
    public string? Id { get; set; }
    public string? Token { get; set; }
    public string? Method { get; set; }
    public JsonElement Params { get; set; }
}

/// <summary>A method response (docs/05 §5.3).</summary>
public sealed class RpcResponse
{
    public string? Id { get; set; }
    public bool Ok { get; set; }
    public object? Result { get; set; }
    public RpcError? Error { get; set; }

    public static RpcResponse Success(string? id, object result) => new() { Id = id, Ok = true, Result = result };

    public static RpcResponse Failure(string? id, string code, string message, string? hint = null) =>
        new() { Id = id, Ok = false, Error = new RpcError { Code = code, Message = message, Hint = hint } };
}

public sealed class RpcError
{
    public string Code { get; set; } = "";
    public string Message { get; set; } = "";
    public string? Hint { get; set; }
}
