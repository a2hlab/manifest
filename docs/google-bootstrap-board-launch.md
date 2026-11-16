# Launching the Google bootstrap board experiment

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
