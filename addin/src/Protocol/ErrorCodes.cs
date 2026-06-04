namespace RevitMCP.Addin.Protocol;

/// <summary>Canonical error codes (docs/05-addin-protocol.md §5.5).</summary>
public static class ErrorCodes
{
    public const string BadToken = "BAD_TOKEN";
    public const string VersionIncompatible = "VERSION_INCOMPATIBLE";
    public const string NoActiveDocument = "NO_ACTIVE_DOCUMENT";
    public const string RevitBusyTimeout = "REVIT_BUSY_TIMEOUT";
    public const string UnknownMethod = "UNKNOWN_METHOD";
    public const string InvalidParams = "INVALID_PARAMS";
    public const string InternalError = "INTERNAL_ERROR";
}
