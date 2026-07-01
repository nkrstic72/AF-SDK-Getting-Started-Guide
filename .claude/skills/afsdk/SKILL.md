---
name: afsdk
description: Reference for building .NET applications that talk to the PI System / AF Server using the OSIsoft/AVEVA PI AF SDK (OSIsoft.AFSDK.dll) — connecting to PISystems/AFDatabase, searching assets, reading and writing time-series data, building AF element hierarchies/templates, and working with event frames. Use whenever the task involves AFSDK, PI AF, AFElement, AFAttribute, AFValue, PISystem/PISystems, AFDatabase, or PI Data Archive integration from C#.
---

# PI AF SDK (AFSDK) Reference

Base knowledge distilled from the AF-SDK-Getting-Started-Guide sample (AF 2.10,
targets `net48`). Use these patterns as the starting point for any app that
reads/writes PI System Asset Framework data via `OSIsoft.AFSDK.dll`.

## Project setup

- Target framework in this era of AFSDK is .NET Framework (`net48`); the SDK
  ships as a COM/GAC-registered assembly, referenced via HintPath, not NuGet:
  ```xml
  <Reference Include="OSIsoft.AFSDK, Version=4.0.0.0, Culture=neutral, PublicKeyToken=6238be57836698e6, processorArchitecture=MSIL">
    <HintPath>C:\Program Files (x86)\PIPC\AF\PublicAssemblies\4.0\OSIsoft.AFSDK.dll</HintPath>
  </Reference>
  ```
  This requires the PI AF Client (part of PI System Explorer / PI Developer's
  Toolkit) installed on the machine that builds/runs the app. Newer AF SDK
  versions (AF 2.11+) also publish an `OSIsoft.AFSDK` NuGet package — prefer
  that if targeting .NET Framework/`.NET` on a machine without the full client
  install, but confirm the version matches the target AF Server.
- Common `using` namespaces: `OSIsoft.AF`, `OSIsoft.AF.Asset`, `OSIsoft.AF.Data`,
  `OSIsoft.AF.PI`, `OSIsoft.AF.Search`, `OSIsoft.AF.Time`, `OSIsoft.AF.EventFrame`,
  `OSIsoft.AF.UnitsOfMeasure`.
- Keep server/database names out of source: load them from an
  `appsettings.json` (or equivalent) at startup, e.g.:
  ```csharp
  public class AppSettings
  {
      public string AFServerName { get; set; }
      public string AFDatabaseName { get; set; }
  }
  // Setup()
  AppSettings settings = JsonSerializer.Deserialize<AppSettings>(
      File.ReadAllText(Directory.GetCurrentDirectory() + "/appsettings.json"));
  ```

## Connecting: PISystems -> PISystem -> AFDatabase

```csharp
public static AFDatabase GetDatabase(string serverName, string databaseName)
{
    PISystems systems = new PISystems();
    PISystem assetServer = !string.IsNullOrEmpty(serverName)
        ? systems[serverName]
        : systems.DefaultPISystem;

    return !string.IsNullOrEmpty(databaseName)
        ? assetServer.Databases[databaseName]
        : assetServer.Databases.DefaultDatabase;
}
```

- `new PISystems()` reads the local KST (Known Servers Table) — no explicit
  credentials needed for Windows-integrated auth against a trusted server.
  Indexing `systems[serverName]` returns `null` if the server isn't known/found
  — always null-check before use.
- Falling back to `DefaultPISystem` / `Databases.DefaultDatabase` lets a tool
  work with sensible defaults when config is left blank.

### Exploring structure once connected

```csharp
database.Elements                       // root AFElement collection
database.ElementTemplates.FilterBy(typeof(AFElement))
database.ElementTemplates["MeterAdvanced"].AttributeTemplates
database.PISystem.UOMDatabase.UOMClasses["Energy"].UOMs
database.EnumerationSets                 // enumerated value sets
database.ElementCategories / database.AttributeCategories
element.Template.Name
attrTemp.DataReferencePlugIn?.Name       // e.g. "PI Point"
```

## Searching for assets (`OSIsoft.AF.Search`)

`AFElementSearch` takes a database, a display/query name, and a query string
using AF's search-query mini-language. Always wrap in `using` (it allocates
server-side query state) and set a `CacheTimeout` for repeated use:

```csharp
using (AFElementSearch elementQuery = new AFElementSearch(database, "ElementSearch", "\"Meter00*\""))
{
    elementQuery.CacheTimeout = TimeSpan.FromMinutes(5);
    foreach (AFElement element in elementQuery.FindObjects())
    {
        // ...
    }
}
```

Query string patterns that come up constantly:
- Bare quoted string → element name mask: `"Meter00*"`
- By template: `template:"MeterBasic"` (also matches templates derived from it —
  check `element.Template.Name != templateName` if you need to distinguish)
- By attribute value (equality): `template:"MeterBasic" "|Substation":"SSA*"`
- By attribute value (comparison): `template:"MeterBasic" "|Energy Usage":>300`
- Combine multiple constraints by space-separating clauses (implicit AND).

To filter on attribute categories, search elements by template, then iterate
`element.Attributes` and check `attr.Categories.Contains(someAFCategory)` —
there's no direct "search by attribute category" query token.

`AFEventFrameSearch` follows the same shape but takes a search mode and time
window (see Event Frames section below).

## Reading time-series data (`OSIsoft.AF.Data`, `OSIsoft.AF.Time`)

Resolve an attribute by path or via search, then call methods on `attr.Data`:

```csharp
AFAttribute attr = AFAttribute.FindAttribute(@"\Meters\Meter001|Energy Usage", database);

AFTime start = new AFTime("*-30s");   // AF relative-time syntax: *, t, y, -Nd/h/m/s
AFTime end = new AFTime("*");
AFTimeRange timeRange = new AFTimeRange(start, end);

// Raw archive events in the range
AFValues recorded = attr.Data.RecordedValues(
    timeRange: timeRange,
    boundaryType: AFBoundaryType.Inside,
    desiredUOM: database.PISystem.UOMDatabase.UOMs["kilojoule"], // optional unit conversion
    filterExpression: null,
    includeFilteredValues: false);

// Evenly-spaced interpolation
AFValues interpolated = attr.Data.InterpolatedValues(
    timeRange: timeRange,
    interval: new AFTimeSpan(TimeSpan.FromSeconds(10)),
    desiredUOM: null,
    filterExpression: null,
    includeFilteredValues: false);

// Bucketed aggregate (returns a dictionary keyed by summary type)
IDictionary<AFSummaryTypes, AFValues> hourly = attr.Data.Summaries(
    timeRange: timeRange,
    summaryDuration: new AFTimeSpan(TimeSpan.FromHours(1)),
    summaryType: AFSummaryTypes.Average,
    calcBasis: AFCalculationBasis.TimeWeighted,
    timeType: AFTimestampCalculation.EarliestTime);
foreach (AFValue v in hourly[AFSummaryTypes.Average]) { /* ... */ }
```

Relative time tokens: `*` = now, `t` = today, `y` = yesterday, and offsets like
`t+10h`, `t-7d`. `AFTime.LocalTime` / `.UtcTime` give `DateTime` in either zone.
`val.UOM?.Abbreviation` gives the display unit; always null-check.

### Bulk reads across many attributes: `AFAttributeList`

Batch the same query across many elements instead of looping one attribute at
a time — the SDK pipelines/pages these server-side:

```csharp
AFAttributeList attrList = new AFAttributeList();
using (AFElementSearch q = new AFElementSearch(database, "s", "template:\"MeterBasic\""))
{
    foreach (AFElement el in q.FindObjects())
        foreach (AFAttribute a in el.Attributes)
            if (a.Name == "Energy Usage") attrList.Add(a);
}

IList<AFValue> snapshotAtTime = attrList.Data.RecordedValue(new AFTime("t+10h"));

// Large fan-out: page requests instead of sending everything in one call
PIPagingConfiguration paging = new PIPagingConfiguration(PIPageType.TagCount, 100);
IEnumerable<IDictionary<AFSummaryTypes, AFValues>> summaries = attrList.Data.Summaries(
    timeRange: timeRange,
    summaryDuration: new AFTimeSpan(TimeSpan.FromDays(1)),
    summaryTypes: AFSummaryTypes.Average,
    calculationBasis: AFCalculationBasis.TimeWeighted,
    timeType: AFTimestampCalculation.EarliestTime,
    pagingConfig: paging);
foreach (var dict in summaries)
{
    AFValues vals = dict[AFSummaryTypes.Average];
    Console.WriteLine(vals.Attribute.Element.Name); // AFValues remembers its source attribute
}
```
Use `PIPagingConfiguration` whenever a query fans out over many PI Points to
avoid overloading the Data Archive with one giant request.

## Writing / updating data

```csharp
// Simple current-value or config write
attribute.SetValue(new AFValue("some string"));
attribute.SetValue(new AFValue(350));

// Bulk insert/replace/remove across many AFValue objects at once
AFListData.UpdateValues(valuesToRemove, AFUpdateOption.Remove);
AFListData.UpdateValues(valuesToInsert, AFUpdateOption.Insert);
```

**Gotcha:** there is no built-in transaction/rollback for archive value edits.
If a write could destroy data (e.g. swapping/overwriting a time range), read
and persist the values you're about to remove *before* calling
`AFListData.UpdateValues(..., AFUpdateOption.Remove)`, in case you need to
restore them.

## Building an AF hierarchy (templates, elements, references)

Everything that edits the AF database (adding elements, templates,
categories, enum sets, attribute values) is transactional per-database via
`database.CheckIn()`. Always guard with `database.IsDirty` and call
`CheckIn()` after a batch of edits — uncommitted changes are only visible to
your session:

```csharp
// Element template + attribute templates
AFElementTemplate template = database.ElementTemplates.Add("FeederTemplate");
AFAttributeTemplate cityAttr = template.AttributeTemplates.Add("City");
cityAttr.Type = typeof(string);

AFAttributeTemplate power = template.AttributeTemplates.Add("Power");
power.Type = typeof(Single);
power.DefaultUOM = database.PISystem.UOMDatabase.UOMs["watt"];
power.DataReferencePlugIn = database.PISystem.DataReferencePlugIns["PI Point"]; // ties attr to a PI tag

// Instantiate an element from a template
AFElement feeder001 = feedersRoot.Elements.Add("Feeder001", template);
feeder001.Attributes["City"].SetValue(new AFValue("London"));
feeder001.Attributes["Power"].ConfigString = @"%@\Configuration|PIDataArchiveName%\SINUSOID";

if (database.IsDirty) database.CheckIn();
```

Other building blocks seen throughout:
- **Template inheritance**: `childTemplate.BaseTemplate = parentTemplate;`
  then add/override attribute templates on the child.
- **Enumeration sets** (for status/type dropdowns):
  `AFEnumerationSet set = database.EnumerationSets.Add("Building Type"); set.Add("Residential", 0);`
  then `attrTemplate.TypeQualifier = set;` and
  `attr.SetValue(new AFValue(set["Residential"]));`
- **Categories** (for grouping/searching elements & attributes):
  `database.ElementCategories.Add("Measures Energy")`,
  `database.AttributeCategories.Add("Building Info")`, then
  `template.Categories.Add(category)` or `attrTemplate.Categories.Add(category)`.
- **Weak references** (non-hierarchical cross-links, e.g. a meter also shown
  under a city): `AFReferenceType weak = database.ReferenceTypes["Weak Reference"];`
  then `otherElement.Elements.Add(existingElement, weak);` — always
  `.Contains(...)` check first to avoid duplicate refs.
- **Config indirection pattern**: store the Data Archive name once on a
  "Configuration" element attribute, then reference it from every PI Point
  ConfigString via substitution parameter, e.g.
  `@"\\%@\Configuration|PIDataArchiveName%\%Element%.%Attribute%"` — avoids
  hardcoding server names across hundreds of tags.
- Check existence before creating anything (`database.Elements.Contains(name)`,
  `database.ElementTemplates.Contains(name)`) so setup scripts are idempotent
  and safe to re-run.

## Event Frames (`OSIsoft.AF.EventFrame`)

An event frame type is just an `AFElementTemplate` whose `InstanceType` is
`AFEventFrame`:

```csharp
AFElementTemplate efTemplate = database.ElementTemplates.Add("Daily Usage");
efTemplate.InstanceType = typeof(AFEventFrame);
efTemplate.NamingPattern = @"%TEMPLATE%-%ELEMENT%-%STARTTIME:yyyy-MM-dd%-EF*";

AFAttributeTemplate usage = efTemplate.AttributeTemplates.Add("Average Energy Usage");
usage.Type = typeof(Single);
usage.DataReferencePlugIn = AFDataReference.GetPIPointDataReference();
// Relative reference: pull from the primary referenced element's own attribute,
// aggregated over the event frame's own time range
usage.ConfigString = @".\Elements[.]|Energy Usage;TimeRangeMethod=Average";
usage.DefaultUOM = database.PISystem.UOMDatabase.UOMs["kilowatt hour"];

// Create instances
AFEventFrame ef = new AFEventFrame(database, "*", efTemplate);
ef.SetStartTime(startTime);
ef.SetEndTime(endTime);
ef.PrimaryReferencedElement = someElement;  // links the EF to the asset it describes

// Freeze the rolled-up values into the event frame's own attributes
ef.CaptureValues();
```

Searching event frames uses `AFEventFrameSearch` instead of `AFElementSearch`,
with an explicit search mode and time anchor:

```csharp
using (AFEventFrameSearch search = new AFEventFrameSearch(
    database, "EventFrame Captures", AFEventFrameSearchMode.ForwardFromStartTime,
    startTime, $"template:\"{efTemplate.Name}\""))
{
    search.CacheTimeout = TimeSpan.FromMinutes(5);
    foreach (AFEventFrame ef in search.FindObjects()) { /* ... */ }
}

// Or a bounded window with AFSearchMode + explicit end time:
using (AFEventFrameSearch search = new AFEventFrameSearch(
    database, "name", AFSearchMode.StartInclusive, startTime, endTime,
    $"template:'{efTemplate.Name}' ElementName:Meter003"))
{ /* ... */ }
```

**Batching checkpoint**: when creating/updating many event frames in a loop,
periodically call `database.CheckIn()` (e.g. every 500 items) instead of only
at the end — keeps a single failure from losing an entire large batch and
avoids an oversized uncommitted transaction.

## General gotchas / conventions to carry forward

1. Null-check every SDK lookup by name/indexer (`systems[name]`,
   `database.Elements[name]`, `database.ElementTemplates[name]`) — they return
   `null` rather than throwing when not found.
2. Wrap every `AFElementSearch` / `AFEventFrameSearch` in `using` and set
   `CacheTimeout` for anything reused.
3. Check `database.IsDirty` and call `database.CheckIn()` after edits; check
   `.Contains(name)` before `.Add(name)` to keep setup/migration code
   idempotent and safe to re-run.
4. For bulk operations (many elements/attributes/event frames), use
   `AFAttributeList` / `PIPagingConfiguration` for reads and periodic
   `CheckIn()` for writes — don't do it one-object-at-a-time in a tight loop
   against the server.
5. Prefer `AFTime` relative syntax (`*`, `t`, `y`, `t-7d`) over building
   `DateTime` math by hand when expressing PI-style relative windows.
6. Keep server/database names in external config (`appsettings.json`), never
   hardcoded, and support falling back to `DefaultPISystem` /
   `DefaultDatabase`.
