# Managed launch (ADR-0008) on the test board

A managed launch runs an APK as an OH application, not as a direct launch inside a borrowed Westlake host
window:
- The app has its own OH bundle, named after its Android package, with its own uid, data and token.
- `aa start` goes through OH's application manager, which asks for the process. Westlake's spawner
  (appspawn-x) creates it.
- OH's ability manager and SceneBoard own the app's lifecycle and windows. `aa dump` and the window
  manager list it as they list any OH app, and `aa force-stop` ends it.

The design is westlake's `docs/adr/0008-one-oh-process-model-for-apks-and-haps.md`. This page is the
procedure.

## How OH reaches Westlake's spawner

OH 6.1's application manager asks the Cangjie spawner's socket, `CJAppSpawn`, for any bundle whose entry
module names a dotted class as its `srcEntry` (`AppMgrServiceInner`'s `IsCjApplication`). The app's bundle
has such an entry. The launcher runs one spawn router, `appspawn-x --socket-name CJAppSpawn --route`, on
that socket. The router passes each request to the spawner of the bundle it names, which it finds in a
root-only registry: `/data/service/el1/public/westlake-registry/managed/<bundle>`.

The router's socket carries appspawn's SELinux context (`WESTLAKE_SPAWN_SOCKET_CONTEXT=u:r:appspawn:s0`),
because OH's foundation process may not connect to a socket of the shell's `su` domain. A launch's spawner
admits the application manager's request (foundation's uid and SELinux context) only for the bundle it was
started for.

**Test board only.** While the router holds `CJAppSpawn`, Cangjie applications cannot start. A reboot
restores init's socket. A product needs its own ART branch in the application manager, which is the
platform owner's decision (ADR-0008, feasibility question 2).

## Steps

1. **Make the app's bundle** from a source Westlake host build (`imehost-unsigned.hap` and its
   `artifacts.json`). `--activity` is the app's launcher activity, fully qualified as in its manifest:

   ```bash
   python3 tools/make_managed_bundle.py --host-build <host build> \
       --package <android package> --activity <launcher activity> --out <new dir>
   ```

2. **Sign it** with OH's public development certificates:

   ```bash
   python3 tools/sign_development_host.py --workspace <workspace> --host-build <bundle dir> \
       --managed --out <new dir>
   ```

3. **Install `source-host.hap`** with `bm install -p <hap>`. Reinstall with `bm install -r -p <hap>`,
   which keeps the bundle's uid.

4. **Launch** with `tools/probe_source_app.py` as for a direct launch, plus:
   - `--host <android package>`, the app's bundle;
   - `--managed`;
   - `--runtime-library appspawn-x`, or any other way to supply a spawner with routing and managed-bundle
     admission.

   The launcher then:
   - registers this launch's spawner socket for the bundle;
   - starts the router if none runs;
   - stops a running instance (`aa force-stop`);
   - starts the bundle with `aa start -b <package> -a <launcher activity>`;
   - waits for its spawner's `Spawned child pid=N for <package>` line.

   It also sets these for the app:
   - `WESTLAKE_MANAGED_LAUNCH=1`: one OH ability hosts the app's Android task, so the app's own
     activities start in its process.
   - `APPSPAWNX_BACKGROUND_GC=CMS`, unless a `--runtime-env` setting chooses another collector. This
     keeps ART's background collector non-moving, because a moving collection crashed apps that OH
     moved to the background.

5. **Stop it** with `aa force-stop <android package>`. That removes the process, its windows and its
   ability record.

## Installed apps: started and stopped by OH

The steps above start an app through the launcher. Two more launcher options leave it installed, so OH starts it
again from its own entry points (the home screen, `aa start`, recents), as an installed app starts on a phone.

- **The spawner's start is registered.** A managed launch also writes
  `/data/service/el1/public/westlake-registry/managed/<package>.start`, root's only like the registry. It holds
  the launch's own start of the app's spawner. When OH asks for the app's process and the registered spawner
  does not accept connections, the spawn router (westlake `managed/on-demand-spawner`) runs that script, waits up
  to 30 s for the spawner, and passes the request on. This happens after `aa force-stop` of the spawner, or after
  a reboot. A spawner that accepts but does not answer is not asked twice.
- **`--stage-root /data/local/tmp/a2hlab-installed`** keeps the launch's stage (helpers, the installed APK files,
  `parent.log`) out of `/data/local/tmp/a2hlab-app-*`, which rounds delete. The default stays `/data/local/tmp`.
- **Relaunching replaces the app's spawner.** The launcher stops the bundle's previous spawner, the one the
  registry named before this launch. appspawn-x ends a spawner's processes with it (SIGTERM), and ends an app's
  other processes when its main process ends.

The app's data is in `<runtime>/app-data/<package>`. A relaunch carries it into the new runtime
(`--carried-app-data`, `PERSIST_DATA=<package>` in the harness). `bm uninstall` removes it with the bundle.
Uninstalling should also remove the app's registry entries and its stage under the stage root.

After a reboot the router is not running and parameters set with `param set` are gone. Re-set them, then start the
router again with the library path of its first start; that path is in the launch's state, under the spawner
socket's runtime.


- One process per app: an app's declared secondary processes are not under OH's application manager
  yet (ADR-0002, ADR-0008 decision 2).
- The bundle requests only the network permissions. Android permissions are not mapped to OH grants
  yet (ADR-0004).
- The OH keyboard shows on `showSoftInput` and BACK hides it first. The input-method metadata is not
  supplied yet, so Android's input method manager binds no IME. Typing into a managed app is not
  verified yet.
- A SurfaceView's window is placed 54 px off.
