using Autodesk.Revit.DB;
using RevitMCP.Addin.Protocol;

namespace RevitMCP.Addin.Commands;

/// <summary>
/// `health.check` (docs/04 §4.1, docs/05 §5.4). Reports Revit version, document
/// state, and units. Runs on the UI thread, read-only, no transaction.
/// </summary>
public sealed class HealthCheckCommand : ICommand
{
    public string Method => "health.check";

    public RpcResponse Execute(CommandContext ctx, RpcRequest request)
    {
        var app = ctx.App.Application;
        var uidoc = ctx.App.ActiveUIDocument;
        var doc = uidoc?.Document;

        string? lengthUnit = null;
        string? areaUnit = null;
        if (doc != null)
        {
            lengthUnit = SafeUnitLabel(doc, SpecTypeId.Length);
            areaUnit = SafeUnitLabel(doc, SpecTypeId.Area);
        }

        var result = new
        {
            revit_connected = true,
            revit_version = app.VersionNumber,
            revit_version_name = app.VersionName,
            protocol_version = Wire.ProtocolVersion,
            document_open = doc != null,
            document_title = doc?.Title,
            units = new { length = lengthUnit, area = areaUnit },
        };

        return RpcResponse.Success(request.Id, result);
    }

    private static string? SafeUnitLabel(Document doc, ForgeTypeId spec)
    {
        try
        {
            var unitTypeId = doc.GetUnits().GetFormatOptions(spec).GetUnitTypeId();
            return LabelUtils.GetLabelForUnit(unitTypeId);
        }
        catch
        {
            return null;
        }
    }
}
