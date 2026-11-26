using System.Globalization;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace RevitMCP.Addin.UI;

/// <summary>
/// Ribbon icons drawn at startup (no image files to ship or keep in sync): a
/// coloured rounded tile with a white Segoe Fluent/MDL2 glyph. Readable on
/// Revit's light and dark themes. Must be called on the UI thread.
/// </summary>
internal static class Icons
{
    public const string Status = "";   // Diagnostic
    public const string Link = "";     // Link
    public const string Pause = "";
    public const string Play = "";
    public const string Document = "";
    public const string Help = "";
    public const string Folder = "";   // FolderOpen

    public static readonly Color Blue = Color.FromRgb(0x1F, 0x6F, 0xEB);
    public static readonly Color Green = Color.FromRgb(0x1A, 0x7F, 0x37);
    public static readonly Color Amber = Color.FromRgb(0xB2, 0x5E, 0x09);
    public static readonly Color Slate = Color.FromRgb(0x4B, 0x55, 0x63);
    public static readonly Color Purple = Color.FromRgb(0x6E, 0x40, 0xC9);

    private static readonly FontFamily GlyphFont = new("Segoe Fluent Icons, Segoe MDL2 Assets");

    public static ImageSource Tile(string glyph, Color background, int size)
    {
        var visual = new DrawingVisual();
        using (var dc = visual.RenderOpen())
        {
            var radius = size * 0.2;
            dc.DrawRoundedRectangle(new SolidColorBrush(background), null,
                new Rect(0, 0, size, size), radius, radius);
            var text = new FormattedText(glyph, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
                new Typeface(GlyphFont, FontStyles.Normal, FontWeights.Normal, FontStretches.Normal),
                size * 0.6, Brushes.White, 1.0);
            dc.DrawText(text, new Point((size - text.Width) / 2, (size - text.Height) / 2));
        }
        var bitmap = new RenderTargetBitmap(size, size, 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(visual);
        bitmap.Freeze();
        return bitmap;
    }
}
