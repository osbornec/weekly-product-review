# Independent local beta verification

Checked on 18 November 2026 using a new, invented subscription-helpdesk project. The evaluating agents received the installed Skill, raw local evidence and ordinary review requests. They did not receive the development history, regression tests, expected answers or earlier beta findings. Scoring criteria were kept outside their workspaces. The later user-requested font reversal restores Google Fonts; the no-remote-resource observations below describe the historical beta version, not the current renderer.

## Original installed version

| Phase | Independent task | Measured result |
| --- | --- | --- |
| Setup | Select metrics, collect four historical windows and prepare the first review | Eight metrics; all 32 expected metric/calculated observations matched; seven original files unchanged. |
| Source outage | Refresh the next week with unavailable analytics, verified support zero and missing CSAT | No fabricated zeros; historical metrics and prior reviews unchanged. Ambiguous coverage wording caused the whole week to remain preview, hiding independently verified support data in the workbook. |
| Same-date recovery | Restore evidence and refresh an existing review containing a new owner note | All 40 expected metric/calculated observations matched; five unique weeks; three dated reviews; earlier metric history/reviews and the owner note preserved. |

The original agent also recorded its own editing-tool and local-verifier errors. Those were corrected within the synthetic project and were not classified as product defects. Missing historical CSAT, sample sizes, workload context and action-completion evidence remained explicit gaps.

## Fresh installation retest

A second agent received a fresh isolated CLI installation and raw evidence including an unavailable current analytics source. It received none of the first agent's findings or scoring criteria.

- All 40 expected metric/calculated observations matched, including missing and undefined values.
- Five reporting intervals were closed after cutoff. The current verified support zero was visible in both quarter and annual reporting; the other seven current metrics remained unavailable.
- Original evidence was unchanged. The prior action retained exact status `In Progress`; the unrelated open question was excluded from carry-over actions.
- Five relative evidence links in the exported HTML resolved to their intended local targets. No automatic remote resources were present; no project font-removal workaround was needed.
- This pass discovered F13 in the generated numeric draft. The authoritative review reported the gaps correctly; a separate regression and updated-package recheck cover the draft correction.

The reporter then rebuilt with the updated local package without editing evidence or authored reviews. All six missing automated/calculated rows showed `Unavailable`; validation/build and all seven local HTML link occurrences passed. Source evidence and authored reviews stayed unchanged. No further defects were found in those scoped checks; the missing evidence remained explicit.

## Demonstrated findings and changes

| ID | Priority | Finding | Change |
| --- | --- | --- | --- |
| F09 | P1 | Source-relative evidence links broke when the review was copied to a different output directory. An absolute `file://` workaround was also ineffective in HTML because that scheme is intentionally not rendered as a link. | Rebase relative links for final Markdown/HTML, archive, generated draft and workbook Notes; preserve the source, web links, query/fragment and code text. Document portable links and supported HTML schemes. |
| F10 | Withdrawn | Opening generated HTML could request three external font resources; this was interpreted too broadly as a local-only restriction. | User requested reversal. Inter now loads from Google Fonts again, with local/system fallback. |
| F11 | P1 | Coverage wording caused a source outage to hide independent verified metrics after the reporting cutoff. | Separate the closed reporting interval from per-metric availability. Verified values remain visible; unavailable/stale values stay blank and excluded. Keep unfinished intervals as preview. |
| F12 | P2 | The agent promoted an unrelated open question into carry-over actions and appended prose to an exact-match status. | Restrict action carry-over to prior Decisions; retain the exact Status value and put commentary in Update or adjacent prose. Keep general questions in Discussion. |
| F13 | P1 | The second independent agent found blank automated/calculated metrics labelled `On track` in the generated draft. | Label missing automated/calculated values `Unavailable`; preserve `Pending input` for missing manual inputs. |

## Development checks

- All 83 standard-library tests pass on Windows x64 CPython 3.8.10 and 3.14.5.
- New regression checks cover portable links across output directories, source preservation, code/web/fragment links, generated carry-over links, Google Fonts loading, mixed verified-zero/unavailable metrics, and truthful missing-value signals.
- The isolated Skills CLI installation keeps development tests and beta records outside the 18-file runtime package. Installed workflow checks use synthetic projects and do not write to a service.
- HTML resource and link targets were checked structurally; no new rendered browser or Excel visual check was performed.

## Scope limits

These checks establish the tested local instructions, calculations, files and recovery paths. They do not establish every agent's behaviour, authenticated execution through additional connectors, native cloud rendering or logged-out scheduling. Those checks retain the limits recorded in [recovery-and-compatibility.md](recovery-and-compatibility.md).

No private reference evidence is used in this beta, no cloud reports or schedules are created, and nothing is pushed or published. Raw beta records, scoring criteria and detailed machine-local evidence remain in the ignored local workbench rather than the installed Skill.
