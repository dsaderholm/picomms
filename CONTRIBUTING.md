# Contributing

Crewline is useful to other schools and venues. The most valuable contributions are **real hardware results**.

1. **Run the validation tests** in [docs/04-validation-plan.md](docs/04-validation-plan.md) on your hardware and send the filled-in
   results log (including `crewline-probe inventory`). Say clearly what you ran and what you did *not*.
2. **Add a row to the compatibility matrix** ([docs/compatibility.md](docs/compatibility.md)) for each headset/adapter you test.
3. Code changes: keep the live audio path free of custom code (PipeWire does the audio), keep every hardware-dependent claim
   labelled "unverified" until measured, and add tests (`pytest`). Browser tests need Chromium (`CREWLINE_TEST_CHROMIUM`).
4. Never add features that silence what a person *hears* under a "lock" label (docs/07).
5. Do not commit audio recordings of students or transcripts.
