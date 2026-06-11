using Autodesk.Revit.DB;
using RevitMCP.Addin.Revit;

namespace RevitMCP.Addin.Plans.Actions;

/// <summary>Result of executing one action inside a commit.</summary>
public readonly record struct ActionResult(ElementId Id, string Category);

/// <summary>
/// Handles one op kind. Preview is strictly read-only (docs/03 §3.3); Execute
/// runs inside a Transaction opened by the commit command and may create model
/// elements.
///
/// Two handle views support intra-plan references (docs/06 §6.4):
/// - Preview gets <paramref name="handleCategories"/>: handle -> the category an
///   earlier action will produce (e.g. "$w1" -> "walls"), so a hosted element can
///   validate its host before anything exists.
/// - Execute gets the real handle -> ElementId map of already-created elements.
/// </summary>
public interface IActionHandler
{
    string Op { get; }

    /// <summary>Category key this op produces, for handle typing (e.g. "walls").</summary>
    string ProducedCategory { get; }

    ActionPreview Preview(Document doc, DocUnits units, ActionNode action,
        IReadOnlyDictionary<string, string> handleCategories);

    ActionResult Execute(Document doc, DocUnits units, ActionNode action,
        IReadOnlyDictionary<string, ElementId> handles);
}

/// <summary>Maps op names to handlers (Phase 2 walls + Phase 3 breadth).</summary>
public static class ActionHandlers
{
    private static readonly Dictionary<string, IActionHandler> Map = new IActionHandler[]
        {
            new WallActionHandler(),
            new DoorActionHandler(),
            new WindowActionHandler(),
            new FloorActionHandler(),
            new RoomActionHandler(),
            new LevelActionHandler(),
        }
        .ToDictionary(h => h.Op, StringComparer.Ordinal);

    public static bool TryGet(string op, out IActionHandler handler) => Map.TryGetValue(op, out handler!);
}
