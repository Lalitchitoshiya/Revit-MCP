using Autodesk.Revit.DB;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Plans.Actions;

/// <summary>`create_level` (docs/04 §4.3, FR-E6): a new level at an elevation.</summary>
public sealed class LevelActionHandler : IActionHandler
{
    public string Op => "create_level";
    public string ProducedCategory => "levels";

    public ActionPreview Preview(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, string> handleCategories)
    {
        var r = new ActionPreview();
        var p = action.Params;

        var haveElev = PlanJson.TryLength(p, "elevation", u, required: true, out var elev, out var eErr);
        if (!haveElev) r.Add(eErr!);

        var name = GetString(p, "name");
        if (name != null && LevelNameExists(doc, name))
            r.Add(Diagnostic.Error(DiagCodes.AmbiguousRef, $"A level named '{name}' already exists."));

        if (haveElev)
            r.Preview = new { elevation = new { value = u.Len(elev), unit = u.LengthLabel }, name };
        return r;
    }

    public ActionResult Execute(Document doc, DocUnits u, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles)
    {
        var p = action.Params;
        if (!PlanJson.TryLength(p, "elevation", u, true, out var elev, out var e1))
            throw new InvalidOperationException(e1!.Message);

        var level = Level.Create(doc, elev);
        var name = GetString(p, "name");
        if (name != null && !LevelNameExists(doc, name)) level.Name = name;

        return new ActionResult(level.Id, "Levels");
    }

    private static bool LevelNameExists(Document doc, string name) =>
        new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>()
            .Any(l => string.Equals(l.Name, name, StringComparison.OrdinalIgnoreCase));

    private static string? GetString(System.Text.Json.JsonElement p, string name) =>
        p.ValueKind == System.Text.Json.JsonValueKind.Object && p.TryGetProperty(name, out var v) &&
        v.ValueKind == System.Text.Json.JsonValueKind.String
            ? v.GetString()
            : null;
}
