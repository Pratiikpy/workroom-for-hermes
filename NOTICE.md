# Notice

Workroom's code was written for this project. As of this version no third-party source code has been copied into it. Ideas and behaviours were studied from the sources below; where code is adapted later it will be listed here with the file it went into.

Studied (ideas only so far):
- Hermes Agent plugin and Desktop SDK documentation and source (NousResearch/hermes-agent): plugin layout, route authentication, tool and toolset enforcement.
- office-desk (DECRUX9812/hermes-office), SolverForge Planner (blackopsrepl/hermes-solverforge-planner), No Cap (jedbrnth-eng/no-cap), Dirtside, hermes-lineage: packaging, the in-chat approval card pattern, how evidence is presented.
- Workiva, UpSlide, think-cell, Displayr, Claude for Microsoft 365, OpenAI deck-report-qc: link states, health checks, roll-forward, QC rule families (behaviour only; their code and assets are not used).
- Public test files from Apache POI used as a test corpus (not shipped).
- Public data used by the update-cycle trials in `bench/verify/` and not shipped: FRED (Federal Reserve Bank of St. Louis) series GDP, GDPC1, GPDI, UNRATE, CPIAUCSL, PAYEMS; World Bank indicator NY.GDP.PCAP.CD. Company earnings releases (public web pages) were read as test text for the claim reader and are not shipped.
- Test tool, not shipped: Microsoft's Open XML SDK (`DocumentFormat.OpenXml`, MIT licence) referenced by the small console project in `bench/verify/oxml_validate`; it is restored from NuGet when the benchmark is built and nothing compiled is committed.
