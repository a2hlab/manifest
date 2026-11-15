# Launching the Google bootstrap board experiment

The Westlake experiment is documented in
[google-bootstrap-experiment.md](https://github.com/a2hlab/westlake/blob/experiment/microg-bootstrap/docs/google-bootstrap-experiment.md).
This manifest change supplies the launcher prerequisites; it does not establish
Google device approval or production account isolation.
The completed experiment and its limits are recorded in
[the board results](https://github.com/a2hlab/westlake/blob/experiment/microg-bootstrap/docs/google-bootstrap-board-results.md).

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
