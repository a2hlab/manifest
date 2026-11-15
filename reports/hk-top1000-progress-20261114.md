# Hong Kong top-1000 apps: progress and API adaptation inventory

Snapshot: **2026-11-14 America/Los_Angeles**, aggregated at **2026-11-15 07:49 UTC**.
This report counts retained device evidence and distinguishes it from static
analysis, source implementation, proposed work and full application acceptance.

## What the numbers establish

| Measure | Count | Meaning |
| --- | ---: | --- |
| Ranked corpus | 1,000 | 706 applications and 294 games |
| Static scans and gap maps | 982 each | API/dependency analysis exists; not a runtime verdict |
| Current download-registry entries | 980 | Acquisition records, not a claim that all inputs are currently launchable |
| Packages with a lifecycle score in retained rounds | 978 | 97.8% of the ranked corpus has scored device evidence |
| No retained lifecycle score | 22 | Unscored, not automatically an engineering failure |
| Latest score per package: drawing | 785 / 978 | 80.3% of scored packages; a mixture of builds and dates |
| Best score ever: drawing | 829 / 978 | 84.8%; historical reach, not a current-build pass rate |
| Latest broad cohort, `l8f` | 308 / 335 drawing | 91.9% of a selected cohort; not 91.9% of the top 1,000 |
| Packages with exploratory interaction records | 515 | 1,277 retained exploration runs, mostly older than the latest launch rounds |
| Latest scripted functional set, `chk6` | 6 apps; 16 / 16 steps | Navigation and onboarding/login-gate checks, not complete app acceptance |

**There is no demonstrated current-build, full-functional pass rate for all
1,000 apps.** A login screen, splash screen, consent page or app-rendered error can
satisfy a drawing check. A service connection can succeed while the requested
feature still fails. The last broad cohort does not cover the remaining 643
previously scored packages on the same build.

The corpus is an interim market proxy: reciprocal-rank fusion of 102 Hong Kong
Play charts captured on 2026-10-23, with overall charts weighted more heavily.
It is not a purchased active-user ranking or a refreshed November market chart.
See the [original corpus record](https://github.com/a2hlab/westlake-harness/blob/7cdc40c54/benchmark/2026-10-25-hk-top1000-static-baseline/README.md).

The acquisition and scan counts have different histories. Existing static maps
cover 982 packages, while the current download registry has 980 entries and
includes one `apkpure-no-arm64` label. Earlier corpus reports also recorded
32-bit-only inputs. Neither count establishes 982 runnable ARM64 apps. Missing
or unscored packages include watch-only, regional and unavailable titles; the
per-app table preserves each distinction without guessing a cause.

## Lifecycle coverage across the corpus

The harness orders observations as spawned, runtime initialized, application
bound, activity launch attempted, view built, and drawing. Activity is partly
inferred from launch/view markers, not proof that an activity completed startup.
The scorer also uses screenshots and first-frame evidence to distinguish the app
from the host screen. These remain startup observations.

| Deepest stage | Latest observation per package | Best observation ever |
| --- | ---: | ---: |
| Runtime initialized | 119 | 111 |
| Application bound | 16 | 10 |
| Activity attempted | 2 | 2 |
| View built | 56 | 26 |
| Drawing | 785 | 829 |
| **Scored** | **978** | **978** |
| Unscored | 22 | 22 |

The latest-per-package column combines evidence dated November 6–14 UTC. Only
335 of those selected observations are dated November 14. It is a tracking view,
not a release qualification result. Likewise, the difference between best-ever
and latest scores is not by itself proof of a regression caused by one change:
builds, feature switches, app state and run-to-run variation differ.

| Rank band | Scored / ranked | Latest mixed-history drawing | Best-ever drawing |
| --- | ---: | ---: | ---: |
| 1–100 | 100 / 100 | 82 | 87 |
| 101–300 | 196 / 200 | 152 | 167 |
| 301–500 | 194 / 200 | 150 | 163 |
| 501–700 | 197 / 200 | 170 | 177 |
| 701–1,000 | 291 / 300 | 231 | 235 |

By type, 691 of 706 applications have scores, with 569 drawing in their latest
record and 598 at their historical best. For games, 287 of 294 have scores, with
216 latest drawing and 231 best-ever drawing.

## Device-round progression and remaining blockers

Counts below are recomputed from the final score for each ranked package in each
retained round log. They use scored-package denominators, which can differ from
launch counts or older narrative reports.

| Round | Scored packages | Drawing | Interpretation |
| --- | ---: | ---: | --- |
| `hk1` | 98 | 59 | Initial top-100 baseline |
| `hkg100` | 98 | 66 | Early microG integration |
| `hkr124` | 98 | 72 | Early media/native-interface work |
| `hka` | 960 | 755 | Broad historical sweep, completed November 7 UTC |
| `l7n` | 330 | 297 | Later selected cohort |
| `l8b` | 335 | 307 | Later selected cohort |
| `l8c` | 336 | 310 | Later selected cohort |
| `l8d` | 330 | 280 | A poorer candidate round; not a new overall baseline |
| `l8f` | 335 | 308 | Latest broad scored cohort, completed November 14 UTC |
| `s251a` | 23 | 21 | Permission-rule A/B sample, log-only |
| `s251b` | 23 | 20 | Same sample with phase-A permission enforcement |

These cohorts differ, so successive numerators are not a controlled performance
trend. The `l8f` history classifier labels 271 steady, 49 flaky, 12 settled and 3
regression candidates. Those labels guide repeated A/B investigation; they are
not a count of independently established root causes.

The 193 latest mixed-history records below drawing have these recorded blocker
categories:

| Recorded category | Packages |
| --- | ---: |
| Native crash | 124 |
| Stall | 16 |
| App/framework exception | 12 |
| Self-exit | 10 |
| Resumed without a frame | 9 |
| Native loading, symbols or upcalls | 4 |
| Self-kill or self-finish | 4 |
| No classified blocker | 14 |

These are symptoms from the scorer, not 193 confirmed Westlake defects. Earlier
investigations found protection libraries, native-loader/ABI mismatches,
framework gaps, graphics problems and app/environment failures. In particular,
a native crash must not automatically be called an anti-tamper failure.

Shared fixes already exercised during this programme include process identity,
declared shared libraries, Bionic/musl and native-loader behavior, Android native
window/buffer interfaces, video decoding and ImageReader, WebView startup,
graphics/input handling, and Play-services integration. The older
[plan/progress record](https://github.com/a2hlab/westlake/blob/941cb262d2cccc9c2c646dee7e282d7f823d9292/docs/HK-TOP1000-PLAN-AND-PROGRESS-2026-10-27.md)
explains the early fixes; its microG-only plan and November 2 status are historical.

## Interaction and functional depth

There are 1,277 retained OH exploration results covering 515 ranked packages. For
each package's latest exploration record:

- 315 survived the exploration and did not have mostly empty view dumps.
- 176 ended during exploration; this bucket does not distinguish every crash,
  intentional exit or app/environment issue.
- 24 had empty view dumps for more than 60% of steps. Games, WebViews and other
  custom surfaces can also expose sparse view trees, so this is not a pixel-level
  blank-screen verdict.

The newest exploration record is November 10 UTC. These counts therefore do not
validate the latest November 14 stack. No matching Android-reference exploration
results were found under the inspected evidence root; cross-platform parity
cannot be derived from this collection alone.

The newest retained scripted set, `chk6`, is dated November 11 UTC:

| App | Steps passed | What the script exercises |
| --- | ---: | --- |
| YouTube | 5 / 5 | Consent, navigation markers, Shorts view, Back |
| Instagram | 3 / 3 | Wait for onboarding, consent, login/account-creation choices |
| Spotify | 2 / 2 | Consent and login/sign-up gate |
| Uber | 1 / 1 | Native welcome or embedded sign-in view exists |
| Viber | 3 / 3 | Start screen, Start action, phone/country gate |
| WhatsApp | 2 / 2 | Consent and phone-number/companion-device gate |

These checks do not establish authenticated messaging, completed rides, playback
quality, purchases, background push, or full business-flow acceptance. The script
steps and denominators also changed across earlier `chk*` sets, so they should
not be compared as an unchanged test suite.

## Google services: demand versus observed behavior

The November 13 client-family scan maps 982 packages, of which 961 contain at
least one recognized Play-services client family:

| Static client family | Packages referencing it |
| --- | ---: |
| Client telemetry | 944 |
| Advertising ID | 919 |
| Push | 849 |
| Measurement | 840 |
| Location | 761 |
| Sign-in | 667 |
| App-set ID | 615 |
| SMS retriever | 554 |
| GASS | 522 |
| AdMob | 515 |
| Games | 170 |

This scan has a different taxonomy from the original gap map; its counts should
not be interpreted as increases/decreases in support. References can be dormant
SDK code and do not prove an app invokes a feature.

Re-running the [GMS trace scorer](https://github.com/a2hlab/westlake-harness/blob/6a22d743fa487797943199355990d712977b4c95/device/play/score_gms.py)
on the retained `l8f` logs gives:

| Service | Apps requesting a connection | Apps with a success callback |
| --- | ---: | ---: |
| Measurement | 305 | 303 |
| App-set ID | 207 | 205 |
| Phenotype | 139 | 139 |
| GASS | 72 | 69 |
| Games | 60 | 0 |
| Google location manager | 35 | 34 |
| AdMob | 31 | 27 |
| Google sign-in | 27 | 27 |
| Cast | 13 | 11 |
| Wear | 12 | 0 |

Successful and unsuccessful callbacks can both occur for one app, so error
counts are not disjoint from successes. The trace also shows advertising-ID
replies for 296 apps and content-provider replies for 322. Phenotype has
SecurityException replies in 21 apps, and direct location-interface calls have
them in 2. Some broker requests have no observed final callback.

A successful connection is not a completed login, delivered location fix,
downloaded module, push delivery or attestation. In particular, the SafetyNet and
Wallet binders appearing in the trace do not prove attestation or payment works.
The full aggregate is in [gms-l8f.txt](hk-top1000-20261114/gms-l8f.txt).

## New implementation work after the broad round

The following PRs were **open at this snapshot**. Their source and reported board
tests show progress beyond the old plan, but do not constitute a new full-corpus
qualification. The local integration branch inspected was `spawner-auth` at
`74b1bfc1ef8f37d91880bbbfbe4eb432c2df571e`; this is distinct from manifest-pinned
main and from every historical round's payload.

| Work | Evidence and current limit |
| --- | --- |
| [Spawner/caller identity, PR 159](https://github.com/a2hlab/westlake/pull/159) | Credential requests are rebuilt from trusted launch information; a root-owned registry and package/APK/certificate checks are implemented. Reported identity checks and split-file fixes have board samples. Channel identity enforcement remains an explicit switch; this is not complete per-APK OH isolation. |
| [Permission levels, PR 162](https://github.com/a2hlab/westlake/pull/162) | Protection-level rules and tracing implemented. The 23-app A/B has 21 versus 20 drawing, with no reported Java fatal/SecurityException in either sample. Enforcement remains off pending full-corpus A/B; dangerous permission handling is still incomplete. |
| [PackageInstaller sessions, PR 163](https://github.com/a2hlab/westlake/pull/163) | Genuine Play Store downloaded, verified and published Luminar; install, user-confirmed uninstall, reinstall and welcome-screen launch are recorded on the board. Update-owner metadata is recorded. This is one tested app/workflow, not general Store acceptance. |
| [OH location, PR 164](https://github.com/a2hlab/westlake/pull/164) | Requests reach OH, provider/switch behavior is exercised, and cancellation/timeout paths exist. The retained probe ends `NO_FIXES`: no listener fix in 180 s. The board GNSS engine fails; GNSS requests also disrupted Wi-Fi, so its GNSS mode is disabled there. Actual fix delivery still needs validation. |
| [OH notifications, PR 165](https://github.com/a2hlab/westlake/pull/165) | Eight probe notifications reached OH; the center displayed their text/progress/messages, individual cancel worked, and cancelAll removed the remainder. Content intents/actions, icons/pictures and user-dismiss callbacks remain open. OH ownership is still the host application. |
| [Play module files, PR 166](https://github.com/a2hlab/westlake/pull/166) | Read-only descriptor transfer and private copies with matching hashes are exercised. The PR explicitly has not demonstrated a module loading from a copy; Play advertises module version 0 and its downloads are throttled. Default mode remains observe-only. |

The unified OH AppMgr/AbilityManager process model in ADR-0008 and the wider
service mappings in ADR-0009 remain larger workstreams. Partial implementation
of a few decisions must not be described as completed GrapheneOS-equivalent
sandboxing, Android compatibility or HAP/APK security parity.

## How many API adaptations?

The latest published overall inventory located is dated **2026-11-06**. It
estimates **about 3,300 Android-facing entry points** implemented or answered by
Westlake, plus about **630 distinct OH functions** used underneath. These are
inventory estimates, not a count of 3,300 fully implemented or tested Android
APIs. They have not been fully recounted for the November 14 experimental PR stack.

| Layer | Inventory count | Interpretation |
| --- | ---: | --- |
| Full Java Binder adapters | 14 interfaces, 1,012 methods | 351 methods have custom logic; 661 intentionally return default/empty answers |
| Lightweight service stand-ins | 38 named services | Together with the adapters, about 52 service names are answered |
| JNI entry points | About 1,295 | 1,026 registered entries and 269 exported `Java_*` entries |
| Native Android ABI functions | About 985 | Export inventory across Bionic, native/media/camera/network and related shims |
| Mainline stand-ins | 115 classes | Class-load compatibility; classes are not API methods |
| OH public NDK dependencies | About 320 functions in 30 libraries | The host API side of the adaptation |
| Direct OH dependencies | About 370, mostly platform C++ | Overlap with public/source counts; not added to 630 again |

The three principal entry-point layers sum to about **3,292**, rounded to 3,300.
One Android feature can cross several layers, so this is not a deduplicated count
of user-visible features. Of the 1,012 methods in the 14 full service adapters,
34.7% had their own logic and 65.3% were default answers in that inventory; custom
logic itself does not establish complete semantics or host-backed behavior.

Native ABI breakdown: Bionic 506; missing-framework-native shim 154; media NDK
123; libandroid 75; bitmap JNI 59; camera NDK 49; network compatibility 13; sync
fences 6. These are exports, including compatibility/default behavior, not
separately accepted features.

The inventory estimates roughly 156,000 lines of Westlake framework/native code
and about ±10% uncertainty in its counts. Much of the Java framework, ART, HWUI,
Skia and other Android code remains AOSP 15; Westlake adapts the boundaries rather
than reimplementing all Android APIs. New location, notification, installation,
permission and module-sharing work above changes behavior beyond that inventory,
but adding six PRs does not mean adding six APIs. A current exact total needs a
versioned recount of methods, exports, defaults and accepted behavior.

Source: [API shim inventory at the assessed source snapshot](https://github.com/a2hlab/westlake/blob/941cb262d2cccc9c2c646dee7e282d7f823d9292/docs/API-SHIM-INVENTORY-2026-11-06.md).

## Evidence, aggregation method and next acceptance work

Published alongside this note:

- [apps.csv](hk-top1000-20261114/apps.csv): all 1,000 ranked packages, acquisition
  and scan flags, latest/best lifecycle stages and exploration status.
- [rounds.csv](hk-top1000-20261114/rounds.csv): 301 rounds with scored ranked
  packages, from 315 retained round logs read.
- [summary.json](hk-top1000-20261114/summary.json): aggregate counts and static
  Play client-family reach.
- [functional-checks.csv](hk-top1000-20261114/functional-checks.csv): the six-app
  `chk6` set with dates and step counts.
- [source-hashes.json](hk-top1000-20261114/source-hashes.json): SHA-256 and size
  of the input metadata, round logs and exploration/check records read. Names
  are portable evidence identifiers, not download links or machine paths.

For each round, the last printed lifecycle row for a ranked package wins; this
deduplicates cumulative score tables. Across rounds, latest means the newest
per-app stderr file modification time, falling back to the round-log modification
time if that stderr is absent. This is a file-provenance heuristic, not an
independent measurement timestamp. Best-ever takes the maximum observed rung.
Exploration similarly selects the newest retained record per package. Acquisition
records, scans and scored packages are counted separately. The aggregate was
checked for unique corpus membership and matching totals. Existing traces were
analyzed; no new application/device run was performed for this report.

Raw logs, screenshots, account data and APKs remain outside this publication.
The source hashes allow an operator with the evidence collection to verify the
inputs without treating this report as a replacement for that evidence.

Next acceptance should freeze one candidate payload and its APK versions, rerun
the acquired corpus on that same payload, and repeat suspected regressions on
both sides. Then expand beyond the six onboarding checks to signed-in flows,
video/audio playback, push with the app closed, location fixes, permission
revocation, Store install/update/uninstall, notification actions and process-death
recovery. Track those per feature and per app; keep startup reach separate from
functional and security acceptance.
