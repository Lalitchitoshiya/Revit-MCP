using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using RevitMCP.Addin.Diagnostics;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Auth;

/// <summary>
/// Verifies credentials presented by clients (handshake and every request).
///
/// Two kinds are accepted:
///  - the per-Revit-session token from session.json → full access ("session"),
///    unless auth.json sets allow_session_token=false;
///  - signed scoped tokens issued by `python -m revit_mcp.auth issue`:
///      rmcp1.&lt;b64url(payload)&gt;.&lt;b64url(HMAC-SHA256(key, "rmcp1." + payload_b64))&gt;
///
/// Policy and keys live in %LOCALAPPDATA%\RevitMCP\auth.json and are re-read
/// whenever the file changes, so rotation and revocation take effect without
/// restarting Revit. Mirrors verify() in server/revit_mcp/auth.py.
/// </summary>
public sealed class TokenValidator
{
    private const string Prefix = "rmcp1";

    private readonly string _sessionToken;
    private readonly string _policyPath;
    private readonly object _gate = new();
    private DateTime _loadedMtime = DateTime.MinValue;
    private Policy? _policy;

    public TokenValidator(string sessionToken, string? policyPath = null)
    {
        _sessionToken = sessionToken;
        _policyPath = policyPath ?? DefaultPolicyPath;
    }

    public static string DefaultPolicyPath =>
        Environment.GetEnvironmentVariable("REVIT_MCP_AUTH") is { Length: > 0 } p
            ? p
            : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "RevitMCP", "auth.json");

    /// <summary>Returns the caller's principal or throws <see cref="AuthException"/>.</summary>
    public Principal Verify(string? token, long? nowUnix = null)
    {
        var now = nowUnix ?? DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        if (string.IsNullOrEmpty(token)) throw new AuthException(ErrorCodes.BadToken, "Missing token.");
        var policy = CurrentPolicy();

        if (!IsScoped(token))
        {
            if (FixedEquals(token, _sessionToken))
            {
                if (policy != null && !policy.AllowSessionToken)
                    throw new AuthException(ErrorCodes.BadToken,
                        "Session token disabled by policy; use a scoped token.");
                return new Principal { Kind = "session", Sub = "session", Scopes = Scopes.All };
            }
            throw new AuthException(ErrorCodes.BadToken, "Invalid token.");
        }

        if (policy == null)
            throw new AuthException(ErrorCodes.BadToken, "Scoped token presented but no auth.json is configured.");

        var parts = token.Split('.');
        JsonElement claims;
        byte[] sig;
        try
        {
            claims = JsonDocument.Parse(B64Decode(parts[1])).RootElement.Clone();
            sig = B64Decode(parts[2]);
        }
        catch
        {
            throw new AuthException(ErrorCodes.BadToken, "Malformed token.");
        }

        var kid = Str(claims, "kid");
        var key = policy.Keys.FirstOrDefault(k => k.Kid == kid)
                  ?? throw new AuthException(ErrorCodes.BadToken, "Token signed by an unknown key (rotated out?).");
        var expect = HMACSHA256.HashData(key.Secret, Encoding.ASCII.GetBytes($"{Prefix}.{parts[1]}"));
        if (!CryptographicOperations.FixedTimeEquals(sig, expect))
            throw new AuthException(ErrorCodes.BadToken, "Bad token signature.");
        if (key.RetireAfter is long ra && now > ra)
            throw new AuthException(ErrorCodes.TokenExpired, "Token's signing key was rotated out; issue a new token.");
        var exp = Int(claims, "exp") ?? 0;
        if (now >= exp)
            throw new AuthException(ErrorCodes.TokenExpired, "Token has expired; issue a new one.");
        var jti = Str(claims, "jti");
        if (jti != null && policy.RevokedJti.Contains(jti))
            throw new AuthException(ErrorCodes.TokenRevoked, "Token has been revoked.");

        var scopes = claims.TryGetProperty("scopes", out var sc) && sc.ValueKind == JsonValueKind.Array
            ? sc.EnumerateArray().Where(x => x.ValueKind == JsonValueKind.String).Select(x => x.GetString()!).ToList()
            : new List<string>();
        return new Principal { Kind = "scoped", Sub = Str(claims, "sub") ?? "?", Scopes = scopes, Jti = jti, Exp = exp };
    }

    /// <summary>Best-effort identity for audit of a REJECTED token (claims are unverified).</summary>
    public static object DescribeUnverified(string? token)
    {
        if (!IsScoped(token)) return new { kind = string.IsNullOrEmpty(token) ? "none" : "opaque" };
        try
        {
            var c = JsonDocument.Parse(B64Decode(token!.Split('.')[1])).RootElement;
            return new { kind = "scoped(unverified)", sub = Str(c, "sub"), jti = Str(c, "jti") };
        }
        catch { return new { kind = "malformed" }; }
    }

    // ------------------------------------------------------------------ policy

    private sealed class Key
    {
        public string Kid = "";
        public byte[] Secret = Array.Empty<byte>();
        public long? RetireAfter;
    }

    private sealed class Policy
    {
        public bool AllowSessionToken = true;
        public List<Key> Keys = new();
        public HashSet<string> RevokedJti = new(StringComparer.Ordinal);
    }

    private Policy? CurrentPolicy()
    {
        lock (_gate)
        {
            DateTime mtime;
            try
            {
                if (!File.Exists(_policyPath)) { _policy = null; _loadedMtime = DateTime.MinValue; return null; }
                mtime = File.GetLastWriteTimeUtc(_policyPath);
            }
            catch { return _policy; }
            if (mtime == _loadedMtime && _policy != null) return _policy;

            // The issuer swaps the file atomically; retry briefly on a sharing violation.
            for (var attempt = 0; attempt < 5; attempt++)
            {
                try
                {
                    _policy = Parse(File.ReadAllText(_policyPath));
                    _loadedMtime = mtime;
                    AddinLog.Info($"Loaded auth policy ({_policy.Keys.Count} key(s), " +
                                  $"session token {(_policy.AllowSessionToken ? "allowed" : "disabled")}).");
                    return _policy;
                }
                catch (IOException) { Thread.Sleep(20); }
                catch (Exception ex)
                {
                    // A corrupt policy must not silently fall back to "no policy" (= session token OK).
                    AddinLog.Error("auth.json is invalid; refusing scoped tokens until fixed", ex);
                    _policy = new Policy { AllowSessionToken = _policy?.AllowSessionToken ?? true };
                    _loadedMtime = mtime;
                    return _policy;
                }
            }
            return _policy;
        }
    }

    private static Policy Parse(string json)
    {
        var root = JsonDocument.Parse(json).RootElement;
        var p = new Policy();
        if (root.TryGetProperty("allow_session_token", out var a) &&
            (a.ValueKind == JsonValueKind.True || a.ValueKind == JsonValueKind.False))
            p.AllowSessionToken = a.GetBoolean();
        if (root.TryGetProperty("keys", out var keys) && keys.ValueKind == JsonValueKind.Array)
        {
            foreach (var k in keys.EnumerateArray())
            {
                var kid = Str(k, "kid");
                var secret = Str(k, "secret");
                if (kid == null || secret == null) continue;
                long? ra = Int(k, "retire_after");
                p.Keys.Add(new Key { Kid = kid, Secret = B64Decode(secret), RetireAfter = ra });
            }
        }
        if (root.TryGetProperty("revoked_jti", out var rev) && rev.ValueKind == JsonValueKind.Array)
            foreach (var j in rev.EnumerateArray())
                if (j.ValueKind == JsonValueKind.String) p.RevokedJti.Add(j.GetString()!);
        return p;
    }

    // ----------------------------------------------------------------- helpers

    private static bool IsScoped(string? token) =>
        token != null && token.StartsWith(Prefix + ".", StringComparison.Ordinal) && token.Count(c => c == '.') == 2;

    private static bool FixedEquals(string a, string b) =>
        CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(a), Encoding.UTF8.GetBytes(b));

    private static string? Str(JsonElement el, string name) =>
        el.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    // TryGetInt64 THROWS on non-number kinds (e.g. "retire_after": null), so check the kind first.
    private static long? Int(JsonElement el, string name) =>
        el.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt64(out var n)
            ? n : null;

    private static byte[] B64Decode(string s)
    {
        var t = s.Replace('-', '+').Replace('_', '/');
        return Convert.FromBase64String(t.PadRight(t.Length + (4 - t.Length % 4) % 4, '='));
    }
}
