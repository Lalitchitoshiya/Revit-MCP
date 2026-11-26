namespace RevitMCP.Addin.Auth;

/// <summary>
/// Per-method access scopes. MUST mirror METHOD_SCOPES in
/// server/revit_mcp/auth.py. Unlisted methods require <see cref="Write"/>
/// (fail closed), so a new mutating command is never accidentally read-only.
/// </summary>
public static class Scopes
{
    public const string Read = "model:read";
    public const string Write = "model:write";

    public static readonly string[] All = { Read, Write };

    private static readonly Dictionary<string, string> MethodScopes = new(StringComparer.Ordinal)
    {
        ["health.check"] = Read,
        ["model.summary"] = Read,
        ["levels.list"] = Read,
        ["grids.list"] = Read,
        ["types.list"] = Read,
        ["families.search"] = Read,
        ["elements.query"] = Read,
        ["context.get"] = Read,
        ["plan.preview"] = Read, // read-only validation; opens no transaction
        ["plan.commit"] = Write,
        ["plan.undo"] = Write,
    };

    public static string RequiredFor(string? method) =>
        method != null && MethodScopes.TryGetValue(method, out var s) ? s : Write;
}

/// <summary>Who is calling, as established by token verification.</summary>
public sealed class Principal
{
    /// <summary>"scoped" (signed token) or "session" (legacy session.json token).</summary>
    public string Kind { get; init; } = "session";
    public string Sub { get; init; } = "session";
    public IReadOnlyList<string> Scopes { get; init; } = Array.Empty<string>();
    public string? Jti { get; init; }
    public long? Exp { get; init; }

    public bool Can(string scope) => Scopes.Contains(scope);

    /// <summary>Shape written into audit records.</summary>
    public object ToAudit() => new { kind = Kind, sub = Sub, scopes = Scopes, jti = Jti };
}

/// <summary>Verification failure with a wire error code.</summary>
public sealed class AuthException : Exception
{
    public AuthException(string code, string message) : base(message) => Code = code;
    public string Code { get; }
}
