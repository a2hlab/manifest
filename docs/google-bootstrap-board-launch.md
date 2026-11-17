# Launching the Google bootstrap board experiment

Latest bounded result: [Westlake 51d5366](https://github.com/a2hlab/westlake/blob/51d53662e1f13749b8bcbe074cc19bbdf8b9ece0/docs/google-auth-delegation-validation.md)
returned Google OAuth/server-code results through microG and official GMS to
Spotify, which advanced to its new-account form. Testing stopped there without
signup. The older failed runs below are preserved as historical evidence.

The Westlake experiment is documented in
[google-bootstrap-experiment.md](https://github.com/a2hlab/westlake/blob/experiment/microg-bootstrap/docs/google-bootstrap-experiment.md).
This manifest change supplies the launcher prerequisites; it does not establish
Google device approval or production account isolation.
The completed experiment and its limits are recorded in
[the board results](https://github.com/a2hlab/westlake/blob/experiment/microg-bootstrap/docs/google-bootstrap-board-results.md).
The later [official-auth/Spotify follow-up](https://github.com/a2hlab/westlake/blob/cd0293b6e00ecf05c8a422554b6bd67b06dd773e/docs/google-official-auth-validation.md)
failed official GMS token issuance and Spotify Google login; the earlier bounded
Store/API success does not establish full authentication compatibility.

`probe_source_app.py` now copies its authorized spawn request into the app's
runtime as `spawn-request.bin`, owned by the host UID with mode 0600. It supplies
`WESTLAKE_SPAWN_SOCKET` and `WESTLAKE_SPAWN_REQUEST` so
`WESTLAKE_APP_PROCESSES=1` can actually launch declared secondary processes.
Previously, enabling that switch alone could leave those processes unavailable.

Use `--touch-mode isolated` for parallel board work. It creates a mode-0600
per-process tap mailbox, preserves the global tap link, and leaves existing
touch forwarders running. Input is delivered explicitly to the selected PID.
The ordinary stream, tap and off modes retain their existing behavior.

Pin the same native compatibility payload for microG and official GMS:

```text
--webview-input <locked-webview-input>
--bionic-shim-build <verified-source-bionic-shim-build>
--android-native-net-app-libraries
```

The current launcher bundles the Bionic boundary with its WebView input. It is
also needed for official GMS's native libraries, even for a launch using
`WESTLAKE_NO_ACTIVITY=1`. Omitting it produced a missing
`com.google.android.gms.org.conscrypt.NativeCrypto.SSL_CTX_new` implementation
in the preliminary experiment. A broker connection or token result does not
prove the complete native runtime was configured.

Before entering credentials, deploy Westlake's private-log runtime and use
`WESTLAKE_GOOGLE_PRIVATE_LOGS=1`. HDC logs shell command strings: credentials
must not be embedded in those commands. Use private temporary input files and
the target process's private text mailbox. Do not attach account stores,
bootstrap envelopes, cookies, unrestricted logs, or login screenshots to git.

The lock adds the pinned official GMS, microG and source-built external probe
inputs used in the experiment. They are separate from the HK corpus results.
The probe APK must match its recorded hash; it does not validate all Google
APIs or any corpus-wide improvement.

## Live two-path validation

The concurrent auth/API implementation and bounded board results are pinned to
[Westlake dbcc2f08c20a16c313284410bd46691e6ccd8254](https://github.com/a2hlab/westlake/blob/dbcc2f08c20a16c313284410bd46691e6ccd8254/docs/google-two-path-validation.md).
Use that source checkout explicitly with `--westlake-source` when building and
launching this experiment; the general `sources.lock.json` is not advanced by
this experimental input update.

The additional app-input keys are `google-two-path-probe` (the original lifecycle
probe), `google-two-path-probe-v2` (adds wrong-account and denial classification
checks), `google-two-path-denied-probe` (same package, different ungranted signer),
and `google-two-path-store` (the unmodified official Store and its splits). These
are separate experiment fixtures, not new HK corpus acceptance claims.

The final run obtained scoped tokens from a live microG host and Advertising ID
from official GMS in the same client. Official Play Store loaded its catalogue,
downloaded and installed WhatsApp. Provider failure/restart and authorization
revocation checks passed. The reusable credential remained only in microG;
official GMS still reported uncertified status.

In addition to the launcher flags above, configure separate auth and Play sockets,
enforce channel identity, pin the auth provider APK/root spawner and install exact
package/certificate/scope grants in microG's private data. The linked report
contains the tested flags and pins. It also records a Store-only private install
mount: the existing global installed-package directory belonged to another native
host UID, so the fixture used a directory owned by its own UID inside its mount
namespace. It did not change the global directory's permissions.

The successful install is in Westlake's package registry within that namespace.
It does not establish native OH BMS publication, production UID/SELinux isolation,
Google certification, Play Integrity, or full API/corpus coverage.

## Official SDK token and Spotify follow-up

The input keys `google-official-auth-probe` and `google-official-auth-probe-v2`
pin two source-built diagnostic APKs. The first has SDK/Binder tests; v2 adds a
direct microG positive control. Both launch
`org.westlake.googlebootstrap.probe.OfficialAuthActivity`. They use the same
existing probe package/signer and exact `ac2dm` grant. Their source, Maven lock,
builder and private-log reports are in
[Westlake cd0293b6e00ecf05c8a422554b6bd67b06dd773e](https://github.com/a2hlab/westlake/tree/cd0293b6e00ecf05c8a422554b6bd67b06dd773e/tests/google-auth).
Use that checkout for the current v2 probe. Its framework sources still match
the earlier deployed build 04; no new runtime fix is claimed here.

The 2026-11-15 Pacific / 2026-11-16 UTC board comparison found:

| Operation | Result |
| --- | --- |
| Forced microG `AccountManager.getAuthToken` control | Passed |
| Official Google SDK `GoogleAuthUtil.getToken` | `BadAuthentication` |
| Official GMS token Binder | `BadAuthentication` |
| Existing corpus Spotify Google login | Error after its bundled sign-in activity; no completed login or new-account signup |

The current proxy withholds the credential/cache reads used by official GMS's
token implementation; those failed operations did not issue a microG token
request. Cross-package activity/result transport is also incomplete. Spotify's
returned Google status was not captured, so its precise cause must not be
equated with the SDK token error. The linked report distinguishes measured
failures from source-confirmed gaps and preserves the reviewed public error
screen without account data.

These are experiment fixtures, not new corpus acceptance passes. The general
`sources.lock.json` remains unchanged. The pinned APKs require the original
development signing key/toolchain to reproduce their identity; a new signer
requires a new input hash and an explicitly authorized provider grant.

The subsequent [Spotify log diagnosis at Westlake b29cc0b](https://github.com/a2hlab/westlake/blob/b29cc0bda7798cea3cf1fae8b7b3607f35ae2460/docs/spotify-google-signin-diagnosis.md)
confirms the immediate cause: OH activity resolution returns no handler for
Google Sign-In, Android start error `-91` becomes `ActivityNotFoundException`,
and Spotify's bundled SDK returns Google `Status(17)`. The Google account
picker is never reached. The target activity is present in the GMS APK and its
declared UI process is alive. This is separate from the token-service error.

That replay adds opt-in, value-free activity diagnostics to a rebuilt adapter
using `WESTLAKE_GOOGLE_SIGNIN_DIAGNOSTICS=1` together with private logs. The
base framework JAR, Spotify APK and provider hosts remain the same; no new
app-input pin or activity-routing fix is introduced. The linked report records
the diagnostic build/source hashes and exact board events.

## Activity/result bridge and final Spotify replay

[Westlake 4e564a4d3ca051076ee27db19c58322dc9a02d68](https://github.com/a2hlab/westlake/blob/4e564a4d3ca051076ee27db19c58322dc9a02d68/docs/remote-activity-results.md)
implements the opt-in activity/result route, same-app PendingIntent preparation,
account-picker visibility metadata, and `FLAG_ACTIVITY_FORWARD_RESULT` handling.
Build this checkout explicitly with `--westlake-source`. Both client and target
need `WESTLAKE_REMOTE_ACTIVITIES=1`, `WESTLAKE_CHANNEL_IDENTITY=enforce` and
`WESTLAKE_GOOGLE_PRIVATE_LOGS=1`, in addition to the experiment's existing
separate auth and Play endpoints and provider pins.

The final board replay reached official Google's account picker from Spotify,
accepted the authorized existing account, and traversed all three forwarding
redirects without premature cancellation. Google then displayed "Verify it's
you" and requested sign-in again. Back returned exactly one canceled result to
Spotify (Google status 12501 after that deliberate cancellation); GMS's UI
process survived. Spotify is **not authenticated**. Official GMS still requests
credential/cache reads withheld by the token-only proxy. The reusable credential
remains only in microG; completing native official auth needs a separate scoped
token-mediation contract.

The new `remote-activity-host` and `remote-activity-client` lock entries pin the
source-only contract fixture from that Westlake commit. The host deliberately
uses package `com.google.android.gms` but contains no Google code or account
data. Run it on a dedicated `wl.remote.fixture...` endpoint without an auth
connection. Stage each app sequentially when using the shared input cache.
The linked fixture README supplies its build and board checks.

The final fixture passed its filtering, caller/referrer, nested Parcelable,
PendingIntent, result-forwarding, foreign-access denial, cancellation and
target-death checks. A separate run verified caller-death cleanup. Java build,
packaging, boot generation, framework preload and six existing bootstrap tests
passed. The unchanged manifest app-input test has a pre-existing failure:
modified-APK rejection leaves an output directory; this was reproduced against
the baseline files and is not fixed by this change.

These results do not advance HK corpus acceptance, production UID/SELinux
isolation, physical-touch/task acceptance, certification or full hybrid
compatibility. The general source lock remains unchanged. Value-free results
and source/runtime hashes are committed in Westlake; account-bearing captures
and private app data are excluded.

## Continued auth-boundary validation

[Westlake eda489528ee9cfe91843a0c4b212b471372689dc](https://github.com/a2hlab/westlake/blob/eda489528ee9cfe91843a0c4b212b471372689dc/docs/google-auth-boundary-validation.md)
adds opt-in, value-free tracing at official GMS credential/cache reads and a
four-button token probe. The new `google-official-auth-probe-v3` input pins that
probe signed with the existing approved development signer. Verify the signer
before launch; the first diagnostic build used the wrong key and was correctly
rejected during account listing. That setup failure is excluded from the actual
package-spoof test, and no provider grant was changed.

The approved probe repeated the successful forced microG `ac2dm` control and
the official SDK/Binder `BadAuthentication` results. The same probe claiming
Spotify in both package options received `SecurityException`. A separate real
Spotify replay again reached Google's account picker and verification screen,
then returned one cancellation after explicit Back.

The new trace observes Spotify-owned OAuth and server-client cache keys with
request options. At the cache boundary, the immediate caller is another GMS
process. Completing the token-only path still requires verified original-app
delegation, OAuth options, consent, expiry and invalidation; a cache-key string
alone is not authorization. Native GMS token issuance and Spotify login remain
unproven.

Enable `WESTLAKE_GOOGLE_AUTH_BOUNDARY_TRACE=1` together with private logs on the
official host. The trace emits fixed categories and stack frames, not raw keys,
accounts or tokens. Build/source/runtime hashes and the approved probe results
are pinned in the linked report. This input update leaves the general source
lock unchanged and does not advance corpus acceptance or production isolation.

## Delegated Spotify authentication

Build explicitly from
[Westlake 51d53662e1f13749b8bcbe074cc19bbdf8b9ece0](https://github.com/a2hlab/westlake/tree/51d53662e1f13749b8bcbe074cc19bbdf8b9ece0).
The new `google-official-auth-probe-v4` input pins the six-button source-built
probe, SHA-256
`475755430db28ad1012bd9dc02871d29af7f8c9f390848987a10ba75251b9979`,
with the existing approved development signer. It adds two negative tests for
the GMS UI and microG delegation endpoints. The real Spotify APK supplies the
positive interactive test; the probe does not impersonate a successful Spotify
login.

In addition to the existing identity, private-log, remote-activity and pinned
provider settings, enable `WESTLAKE_GOOGLE_AUTH_DELEGATION=1` on official GMS and
microG. Install the exact private broker/original-app policy documented in the
linked Westlake report. Spotify retains only official GMS/Store connections,
with no direct microG grant. The provider independently verifies the original
Spotify process/APK and requires a live account-selection witness before and
after network I/O. Reusable credentials are withheld from official GMS.

The final build-11 run observed four fresh OAuth responses, three fresh server-code
responses, one exact cache invalidation, and one official activity `RESULT_OK`
received by Spotify. These are repeated reads during one flow, not seven APIs.
Spotify displayed its Create account / date-of-birth form. No date of birth was
entered and no signup was submitted. Completed account login and playback remain
untested. The forced direct microG control passed; both foreign delegation
requests and the official token package-spoof test were rejected.

The earlier delegated requests had failed locally with
`NetworkOnMainThreadException`; the tested change executes HTTP on a bounded
worker while preserving channel and selection checks. The initial client-ID
grant was also corrected to Spotify's actual compiled login client, rather than
its different `default_web_client_id` resource. The report preserves the failure
and success evidence, source/runtime hashes, private-credential entry counts and
remaining limitations.

Use fresh app runtime directories for this replay, preserving account data only
on-device. Reusing old runtime directories caused an unresolved physical-display
discovery abort in preliminary UI runs. Stage apps sequentially, start microG,
then official GMS and Store, then Spotify. When microG's spawner changes, update
the provider pin in every client. A missing Store host can make Spotify select
`NO_IMPL` before authentication begins.

The new bridge is opt-in and tied to the tested GMS cache protocol. General
consent/recovery, background refresh, account switching and in-flight auth
cancellation/revocation still need work or validation. All experiment apps share
native UID 20010056; per-app production isolation is not proven. This update
leaves `sources.lock.json` and HK corpus acceptance unchanged.

## Retest of the 26 previously refused corpus apps

The [complete Westlake retest report](https://github.com/a2hlab/westlake/blob/027c5b923efa0306e0f3db69d7156b041f3e711c/docs/google-service-retest.md)
records the fresh 2026-11-16 UTC board run and sanitized per-app evidence. This
manifest update adds the 22 original corpus input pins missing from this worktree;
four target pins were already present. Existing input pins and `sources.lock.json`
are unchanged. All 26 archives/APKs and signers were checked before launch.

The run used the same build-11 adapter from Westlake
`51d53662e1f13749b8bcbe074cc19bbdf8b9ece0`, with SHA-256
`59864362f89b0f9d01a02bec9e1582b67d988cd5c546f22ec2321355f03ff2f3`.
Launch one app at a time with fresh private data/runtime directories and
`--touch-mode isolated`. Retain each app's native-library remedies listed in the
report's per-app JSON. Corpus clients used these runtime settings:

```text
WESTLAKE_REMOTE_ACTIVITIES=1
WESTLAKE_GOOGLE_PRIVATE_LOGS=1
WESTLAKE_GOOGLE_SIGNIN_DIAGNOSTICS=1
WESTLAKE_CHANNEL_IDENTITY=enforce
WESTLAKE_LOCATION_GNSS=0
WESTLAKE_PLAY_TRACE=1
WESTLAKE_PLAY_SERVICES_CONNECT=wl.twopath.gms01
WESTLAKE_PLAY_STORE_CONNECT=wl.twopath.store01
```

The named endpoints refer to the existing verified official GMS and Store hosts;
use the corresponding live endpoints in a new fixture. Clients have no direct
microG connection. The hosts retain the private delegation setup described above.

All 26 apps had at least one successful Google service callback, with no sampled
status 9. Twenty-five primary processes survived baseline observation; Artrace
crashed in a native `libpag.so` path. Several apps still showed device rejection,
empty/splash content, or no target UI. The separately authorized FotMob Google
sign-in failed locally while routing a cross-package `PendingIntent`, before
account selection or token delegation. No new account was created.

Official GMS had recorded `uncertified_status=1` without an override throughout
this run, unlike the earlier restricted snapshot. This comparison did not change
only registration and cannot establish a registration workaround. Service
connections are not completed features; native UID isolation, certification and
full corpus acceptance remain unproven. Private raw logs and screenshots are not
part of this update.
