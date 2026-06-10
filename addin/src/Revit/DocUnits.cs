using Autodesk.Revit.DB;

namespace RevitMCP.Addin.Revit;

/// <summary>
/// Converts Revit internal units (feet, square feet) to the document's display
/// units for the wire (docs/06 §6.1). Read paths return model units + a label;
/// nothing leaks implicit feet (NFR-9).
/// </summary>
public sealed class DocUnits
{
    private readonly ForgeTypeId _length;
    private readonly ForgeTypeId _area;

    public string LengthLabel { get; }
    public string AreaLabel { get; }

    private DocUnits(ForgeTypeId length, string lengthLabel, ForgeTypeId area, string areaLabel)
    {
        _length = length;
        _area = area;
        LengthLabel = lengthLabel;
        AreaLabel = areaLabel;
    }

    public static DocUnits From(Document doc)
    {
        var units = doc.GetUnits();
        var len = units.GetFormatOptions(SpecTypeId.Length).GetUnitTypeId();
        var area = units.GetFormatOptions(SpecTypeId.Area).GetUnitTypeId();
        return new DocUnits(len, SafeLabel(len), area, SafeLabel(area));
    }

    /// <summary>Internal feet -> model length unit, rounded for clean JSON.</summary>
    public double Len(double feet) => Math.Round(UnitUtils.ConvertFromInternalUnits(feet, _length), 4);

    /// <summary>Internal square feet -> model area unit.</summary>
    public double Area(double squareFeet) => Math.Round(UnitUtils.ConvertFromInternalUnits(squareFeet, _area), 4);

    /// <summary>Model length unit -> internal feet (for inbound filters).</summary>
    public double ToFeet(double modelValue) => UnitUtils.ConvertToInternalUnits(modelValue, _length);

    public double[] Pt2(XYZ p) => [Len(p.X), Len(p.Y)];
    public double[] Pt3(XYZ p) => [Len(p.X), Len(p.Y), Len(p.Z)];

    private static string SafeLabel(ForgeTypeId unit)
    {
        try { return LabelUtils.GetLabelForUnit(unit); }
        catch { return ""; }
    }
}
