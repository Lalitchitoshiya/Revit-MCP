using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Plans.Actions;

/// <summary>
/// Shared logic for wall-hosted family instances (doors, windows). The host is
/// an existing wall id or a plan-local handle of a wall created earlier in the
/// same plan (docs/06 §6.4). Location is by distance-along-wall or a point.
/// </summary>
public abstract class HostedInstanceHandler : IActionHandler
{
    public abstract string Op { get; }
    public abstract string ProducedCategory { get; }
    protected abstract BuiltInCategory Category { get; }
    protected abstract string ResultCategory { get; }

    public ActionPreview Preview(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, string> handleCategories)
    {
        var r = new ActionPreview();
        var p = action.Params;

        // Host must resolve to a wall (existing or a same-plan wall handle).
        if (PlanJson.TryGetHostRef(p, "host", out var id, out var handle, out var hErr))
        {
            if (handle != null)
            {
                if (!handleCategories.TryGetValue(handle, out var cat))
                    r.Add(Diagnostic.Error(DiagCodes.HostMissing,
                        $"Host handle '{handle}' is not produced by an earlier action."));
                else if (cat != "walls")
                    r.Add(Diagnostic.Error(DiagCodes.HostWrongCategory,
                        $"Host handle '{handle}' is a '{cat}', not a wall."));
            }
            else
            {
                var el = doc.GetElement(ModelRead.ToElementId(id!.Value));
                if (el == null)
                    r.Add(Diagnostic.Error(DiagCodes.HostMissing, $"Host wall {id} not found."));
                else if (el is not Wall)
                    r.Add(Diagnostic.Error(DiagCodes.HostWrongCategory, $"Host {id} is not a wall."));
            }
        }
        else r.Add(hErr!);

        if (!PlanJson.TryResolveSymbol(doc, p, "type", Category, out var symbol, out var tErr)) r.Add(tErr!);

        var hasDist = p.ValueKind == System.Text.Json.JsonValueKind.Object && p.TryGetProperty("distance_along", out _);
        var hasPoint = p.ValueKind == System.Text.Json.JsonValueKind.Object && p.TryGetProperty("point", out _);
        if (!hasDist && !hasPoint)
            r.Add(Diagnostic.Error(DiagCodes.MissingField, "Provide 'distance_along' or 'point' for the location."));

        ValidateExtra(p, u, r);

        r.Resolved = new { type_id = symbol?.Id.Value, host = handle ?? id?.ToString() };
        return r;
    }

    public ActionResult Execute(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles)
    {
        var p = action.Params;

        if (!PlanJson.TryResolveHostElement(doc, p, "host", BuiltInCategory.OST_Walls, handles, out var host, out var e1))
            throw new InvalidOperationException(e1!.Message);
        if (!PlanJson.TryResolveSymbol(doc, p, "type", Category, out var symbol, out var e2))
            throw new InvalidOperationException(e2!.Message);

        var wall = (Wall)host;
        if (wall.Location is not LocationCurve lc || lc.Curve is not { } curve)
            throw new InvalidOperationException("Host wall has no location curve.");

        XYZ point;
        if (PlanJson.TryLength(p, "distance_along", u, false, out var dist, out _))
        {
            var t = curve.Length > 0 ? Math.Clamp(dist / curve.Length, 0, 1) : 0;
            point = curve.Evaluate(t, true);
        }
        else if (PlanJson.TryPoint(p, "point", u, out var pt, out _))
        {
            point = new XYZ(pt.X, pt.Y, curve.Evaluate(0.5, true).Z);
        }
        else throw new InvalidOperationException("Missing 'distance_along' or 'point'.");

        if (!symbol.IsActive)
        {
            symbol.Activate();
            doc.Regenerate();
        }

        var instance = doc.Create.NewFamilyInstance(point, symbol, host, StructuralType.NonStructural);
        ApplyExtra(instance, p, u);
        return new ActionResult(instance.Id, ResultCategory);
    }

    /// <summary>Subclass hook: validate op-specific params (e.g. sill height).</summary>
    protected virtual void ValidateExtra(System.Text.Json.JsonElement p, DocUnits u, ActionPreview r) { }

    /// <summary>Subclass hook: apply op-specific params after creation.</summary>
    protected virtual void ApplyExtra(FamilyInstance instance, System.Text.Json.JsonElement p, DocUnits u) { }
}

/// <summary>`place_door` (docs/04 §4.3, FR-E2).</summary>
public sealed class DoorActionHandler : HostedInstanceHandler
{
    public override string Op => "place_door";
    public override string ProducedCategory => "doors";
    protected override BuiltInCategory Category => BuiltInCategory.OST_Doors;
    protected override string ResultCategory => "Doors";
}

/// <summary>`place_window` (docs/04 §4.3, FR-E3): door-like, plus a sill height.</summary>
public sealed class WindowActionHandler : HostedInstanceHandler
{
    public override string Op => "place_window";
    public override string ProducedCategory => "windows";
    protected override BuiltInCategory Category => BuiltInCategory.OST_Windows;
    protected override string ResultCategory => "Windows";

    protected override void ApplyExtra(FamilyInstance instance, System.Text.Json.JsonElement p, DocUnits u)
    {
        if (PlanJson.TryLength(p, "sill_height", u, false, out var sill, out _))
        {
            var param = instance.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM);
            if (param is { IsReadOnly: false }) param.Set(sill);
        }
    }
}
