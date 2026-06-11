using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Plans.Actions;

/// <summary>`place_room` (docs/04 §4.3, FR-E5): a room at a point inside an
/// enclosed region on a level, with optional name/number.</summary>
public sealed class RoomActionHandler : IActionHandler
{
    public string Op => "place_room";
    public string ProducedCategory => "rooms";

    public ActionPreview Preview(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, string> handleCategories)
    {
        var r = new ActionPreview();
        var p = action.Params;

        if (!PlanJson.TryPoint(p, "point", u, out _, out var ptErr)) r.Add(ptErr!);
        var haveLevel = PlanJson.TryResolveLevel(doc, p, "level", out var level, out var lErr);
        if (!haveLevel) r.Add(lErr!);

        // Whether the point is actually enclosed can only be known at commit; flag that.
        r.Add(Diagnostic.Info("ENCLOSURE_AT_COMMIT", "Room enclosure is verified when committed."));
        r.Resolved = new { level_id = haveLevel ? level!.Id.Value : (long?)null };
        return r;
    }

    public ActionResult Execute(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles)
    {
        var p = action.Params;
        if (!PlanJson.TryPoint(p, "point", u, out var pt, out var e1)) throw new InvalidOperationException(e1!.Message);
        if (!PlanJson.TryResolveLevel(doc, p, "level", out var level, out var e2)) throw new InvalidOperationException(e2!.Message);

        var room = doc.Create.NewRoom(level, new UV(pt.X, pt.Y));
        if (room == null)
            throw new InvalidOperationException("Point is not inside an enclosed region (ROOM_NOT_ENCLOSED).");

        if (TypesGetString(p, "name") is { } name) room.Name = name;
        if (TypesGetString(p, "number") is { } number) room.Number = number;

        return new ActionResult(room.Id, "Rooms");
    }

    private static string? TypesGetString(System.Text.Json.JsonElement p, string name) =>
        p.ValueKind == System.Text.Json.JsonValueKind.Object && p.TryGetProperty(name, out var v) &&
        v.ValueKind == System.Text.Json.JsonValueKind.String
            ? v.GetString()
            : null;
}
