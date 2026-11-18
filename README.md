# Weekly Product Review

Run a weekly product review from Markdown files in your project. Use your agent to choose 7 to 10 metrics, bring numbers and customer feedback together, and record what the team will change. Next week's review starts from the same files and decisions.

```bash
npx skills add osbornec/weekly-product-review
```

Open your project in an agent that supports the Agent Skills format and ask it to set up a Weekly Product Review. The runtime uses the Python 3.8+ standard library. Google sync requires an authorized connector with access to the target Sheet and Doc.

## Try the synthetic example

From a checkout of this repository, run:

```bash
python skills/weekly-product-review/scripts/wpr_sync.py build --wpr-dir examples/b2b-saas-wpr --out-dir wpr-output
```

Open `wpr-output/wpr-workbook.xlsx` for the scorecard and `wpr-output/wpr-review-brief.html` for the review. New workspaces rise from 39 to 48 while activation falls from 43% to 38%. Two mobile onboarding replays give the team a place to investigate. All figures and events are invented.

| Output | Use |
| --- | --- |
| `wpr-workbook.xlsx` | Quarter and full-year scorecards |
| `wpr-review-brief.md` and `wpr-review-brief.html` | Latest reviewed brief |
| `wpr-review-archive.md` | Review history, newest first |
| `wpr-review-draft.md` | Fresh figures to reconcile with an existing review |
| `sheets-payload.json` | Inputs for a date-scoped Sheets update plan |

The build works without Google access. The HTML uses Google Fonts with a system font fallback. See the [creator example](skills/weekly-product-review/examples/creator-wpr/README.md) for a preview, a partial close and a read-only collector you can run locally.

## Run your review

| Ask your agent | What happens |
| --- | --- |
| “Set up a Weekly Product Review for this project.” | Choose metrics, map their sources and create the `wpr/` records. |
| “Refresh this week's review.” | Collect from configured sources, identify missing inputs and rebuild the scorecard. An open week shows labelled previews. After cutoff, publish verified figures and name missing sources. |
| “Help me run the review.” | Investigate changes with customer evidence, review prior actions and record owners and due dates for new decisions. |
| “Split activation by mobile and desktop.” | Update the catalog and record the definition change so past comparisons stay interpretable. |

Keep one Markdown review per week in `wpr/reviews/`. The checked-in or local Markdown records are the source of truth. If you authorize Google sync, the agent checks access, updates the matching date on the existing Sheet and Doc, and verifies the result by reading it back. A blocked destination is reported and local outputs still build.

- [Markdown schema and command reference](skills/weekly-product-review/references/markdown-schema.md)
- [Google connector setup and sync procedure](skills/weekly-product-review/references/connector-sync.md)
- [Integration and local-only options](skills/weekly-product-review/references/integrations.md)

## Develop and verify

The installable folder is [`skills/weekly-product-review/`](skills/weekly-product-review/). It contains the [agent instructions](skills/weekly-product-review/SKILL.md), runtime, templates, references and the compact creator example. The repository keeps development tests and the B2B example at the top level.

```bash
python -B -m unittest discover -s tests
python -B tests/verify_skill_install.py --skills-cli /path/to/skills/bin/cli.mjs --report .local/install-verification.json
```

Run the second command from a clean checkout with an existing Skills CLI. It checks installed files, links and workflows in a temporary workspace. See the [release verification](docs/release-verification.md) for results and test scope.

MIT. See [LICENSE](LICENSE).
