// Validate Office files against the Open XML schemas with Microsoft's own SDK, as a second reader independent of Workroom's code.
// usage: oxml_validate <file.pptx|docx|xlsx> [more files]   prints one JSON object per file: {"file":..., "errors":[{"part","path","description"}]}
using System.Text.Json;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;

foreach (var path in args)
{
    var errors = new List<object>();
    string? fatal = null;
    try
    {
        var validator = new OpenXmlValidator(DocumentFormat.OpenXml.FileFormatVersions.Office2019);
        IEnumerable<ValidationErrorInfo> found;
        var ext = Path.GetExtension(path).ToLowerInvariant();
        if (ext == ".pptx") { using var d = PresentationDocument.Open(path, false); found = validator.Validate(d).ToList(); }
        else if (ext == ".docx") { using var d = WordprocessingDocument.Open(path, false); found = validator.Validate(d).ToList(); }
        else if (ext == ".xlsx") { using var d = SpreadsheetDocument.Open(path, false); found = validator.Validate(d).ToList(); }
        else throw new InvalidOperationException("not an Office file");
        foreach (var e in found)
            errors.Add(new { part = e.Part?.Uri.ToString(), path = e.Path?.XPath, description = e.Description, id = e.Id });
    }
    catch (Exception ex) { fatal = ex.GetType().Name + ": " + ex.Message; }
    Console.WriteLine(JsonSerializer.Serialize(new { file = path, fatal, errors }));
}
