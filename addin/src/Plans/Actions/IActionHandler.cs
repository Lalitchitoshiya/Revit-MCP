using Autodesk.Revit.DB;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Plans.Actions;

/// <summary>Result of executing one action inside a commit.</summary>
public readonly record struct ActionResult(ElementId Id, string Category);

/// <summary>
/// Handles one op kind. Preview is strictly read-only (docs/03 §3.3); Execute
/// runs inside a Transaction opened by the commit command and may create model
/// elements. `handles` maps plan-local handles to created ids for intra-plan
/// references (docs/06 §6.4).
/// </summary>
public interface IActionHandler
{
    string Op { get; }

    ActionPreview Preview(Document doc, DocUnits units, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles);

    ActionResult Execute(Document doc, DocUnits units, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles);
}

/// <summary>Maps op names to handlers (Phase 2: place_wall).</summary>
public static class ActionHandlers
{
    private static readonly Dictionary<string, IActionHandler> Map =
        new[] { (IActionHandler)new WallActionHandler() }
            .ToDictionary(h => h.Op, StringComparer.Ordinal);

    public static bool TryGet(string op, out IActionHandler handler) => Map.TryGetValue(op, out handler!);
}
