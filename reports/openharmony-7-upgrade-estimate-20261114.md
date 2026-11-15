# Westlake migration to OpenHarmony 7.0: effort estimate

Date: 2026-11-14. Status: preliminary planning estimate, not an implementation or
device-acceptance report.

## Estimate and scope

Allow **6–10 engineer-weeks** to reproduce Westlake's current working results on
OpenHarmony 7.0, approximately **4–6 calendar weeks with two experienced
engineers**, or 6–10 weeks with one. An engineer-week means one engineer working
full time. Parallel work is possible, but board bring-up, rendering and application
acceptance have sequential dependencies.

This assumes a working OH 7.0 firmware/BSP for the current ARM64 board, access to
the required platform headers and libraries, and retention of the current AOSP 15
framework/ART baseline. The scope is migration of existing working application
flows. The accepted proposals for a unified APK/HAP process and security model,
sandboxed Play services, and additional OH-backed Android services require
separate implementation budgets.

Confidence is moderate for the conditional estimate. The assessment checked the
live OH 6.1 board and selected upstream 6.1/7.0 source interfaces; no OH 7.0 build,
deployment or application acceptance was performed. A full dependency/ABI audit
remains part of the initial investigation.

| Work | Engineer-weeks |
| --- | ---: |
| Freeze the working baseline; prepare OH 7.0 SDK, firmware and build inputs | 1 |
| Rebuild native libraries; fix linking, loader and runtime integration | 1–2 |
| Adapt windows, rendering, input and IME integration | 2–3 |
| Adapt appspawn-x, permissions, AccessToken and SELinux integration | 1–2 |
| Device regression: existing APKs, Play services, rendering, interaction and performance | 1–2 |
| **Total** | **6–10** |

A first APK displaying successfully could be an earlier **1–2 calendar-week
milestone**, assuming firmware is ready. That milestone is included in the
estimate and does not establish functional parity or complete regression coverage.

## Assessed baseline

- Live device: OpenHarmony **6.1.0.31**, API **23**, ARM64, Linux **5.15.180**.
  These values were read from device parameters and `uname` during the assessment.
- Target: OpenHarmony **7.0 Release**, API **26**, as recorded in the
  [official release plan](https://github.com/openharmony/release-management/blob/master/OpenHarmony-RoadMap-en.md).
- Westlake source inspected: experimental `play-processes` at
  [`941cb262d2cccc9c2c646dee7e282d7f823d9292`](https://github.com/a2hlab/westlake/tree/941cb262d2cccc9c2c646dee7e282d7f823d9292).
  This identifies the source snapshot reviewed; it does not assert that every
  artifact running on the device was built from that commit.
- The inspected experimental branch is not a change to this manifest's pinned
  source revisions. Freeze and reproduce the actual working payload before
  comparing it with an OH 7.0 candidate.

## Confirmed interface changes and cost drivers

Westlake's [2026-11-06 API inventory](https://github.com/a2hlab/westlake/blob/941cb262d2cccc9c2c646dee7e282d7f823d9292/docs/API-SHIM-INVENTORY-2026-11-06.md)
estimates about 630 distinct OH function dependencies. These include about 320
public NDK functions and about 370 directly linked functions, mostly platform C++
interfaces; the sets overlap. The inventory describes the counts as approximate,
about ±10%. The adapter bridge alone links 257 OH functions. Private window,
render-service, ability and input interfaces make this more than an SDK update.

The following comparisons use the upstream `window_window_manager` release-tag
commits, rather than a moving development branch:

- OH 6.1: `f1f70fb36c2150b479526d286a388472a6fc499a`
  (`OpenHarmony-v6.1-Release`).
- OH 7.0: `ba27caaa88accddcb2785a25a75815857d8b3241`
  (`OpenHarmony-v7.0-Release`).

### Window IPC operation numbers

Westlake's [main-window lookup](https://github.com/a2hlab/westlake/blob/941cb262d2cccc9c2c646dee7e282d7f823d9292/framework/window/jni/oh_window_manager_client.cpp#L169)
hardcodes `SendRequest(56, ...)` for `TRANS_ID_GET_ALL_MAIN_WINDOW_INFO`.
Evaluating the sequential enum values in the release headers gives:

| Operation | OH 6.1 | OH 7.0 |
| --- | ---: | ---: |
| `TRANS_ID_LIST_WINDOW_INFO` | 54 | 56 |
| `TRANS_ID_GET_ALL_MAIN_WINDOW_INFO` | 56 | 58 |

Sources: [OH 6.1 interface](https://github.com/openharmony/window_window_manager/blob/f1f70fb36c2150b479526d286a388472a6fc499a/window_scene/session_manager/include/zidl/scene_session_manager_interface.h),
[OH 7.0 interface](https://github.com/openharmony/window_window_manager/blob/ba27caaa88accddcb2785a25a75815857d8b3241/window_scene/session_manager/include/zidl/scene_session_manager_interface.h).

On the inspected OH 7.0 interface, the unchanged request targets a different
operation. Audit hardcoded IPC identifiers and request/reply formats, use the
target version's declarations or client interfaces where practical, and verify
against the actual board firmware. Changing this one number is not a complete
window migration.

### Window callbacks and property structures

Westlake's [session-stage adapter](https://github.com/a2hlab/westlake/blob/941cb262d2cccc9c2c646dee7e282d7f823d9292/framework/window/jni/session_stage_adapter.h#L98)
implements `UpdateWindowMode(WindowMode)`. The upstream
[OH 6.1 callback interface](https://github.com/openharmony/window_window_manager/blob/f1f70fb36c2150b479526d286a388472a6fc499a/window_scene/session/container/include/zidl/session_stage_interface.h)
uses that signature; the
[OH 7.0 callback interface](https://github.com/openharmony/window_window_manager/blob/ba27caaa88accddcb2785a25a75815857d8b3241/window_scene/session/container/include/zidl/session_stage_interface.h)
requires `UpdateWindowMode(const WindowModeInfo&)`. Other callbacks also change.
The [OH 7.0 window-property header](https://github.com/openharmony/window_window_manager/blob/ba27caaa88accddcb2785a25a75815857d8b3241/window_scene/common/include/window_session_property.h)
changes methods and fields relative to 6.1. These are source-adaptation and rebuild
tasks, followed by runtime validation of serialization and behavior; old private
C++ binaries should not be assumed compatible.

### Native bridge build recovery

The November 13 [ADR-0008 build record](https://github.com/a2hlab/westlake/blob/8e7f8b0844d851fa7567c06f5e7ea04a1ffd7721/docs/adr/0008-one-oh-process-model-for-apks-and-haps.md#L98)
reports that all 50 native bridge sources now compile and the linked library is
byte-identical to the deployed one. It records jsoncpp 1.9.6 and stand-ins for
seven OH-generated IDL headers as the missing inputs that were restored. This
removes an earlier OH 6.1 build blocker. It is a recorded result, not an OH 7.0
rebuild performed by this assessment. The target-version header graph still
needs to be established.

## Dependencies and additional scope

**Exact-board firmware is the largest unresolved scheduling dependency.** A
working OH 7.0 image/BSP for the current board was not confirmed. SDK availability
or support for another board is insufficient. If kernel, GPU or vendor-driver
porting is required, the project could become a multi-month effort. Obtain the
exact board/vendor support status before treating the conditional schedule as a
delivery commitment.

**Architecture improvements are separate from preserving current results.**
[ADR-0008](https://github.com/a2hlab/westlake/blob/8e7f8b0844d851fa7567c06f5e7ea04a1ffd7721/docs/adr/0008-one-oh-process-model-for-apks-and-haps.md)
and [ADR-0009](https://github.com/a2hlab/westlake/blob/8e7f8b0844d851fa7567c06f5e7ea04a1ffd7721/docs/adr/0009-android-system-services-on-oh-services.md)
describe accepted directions for shared APK/HAP management and OH-backed Android
services. At the cited snapshot those proposals are not implemented or
device-accepted. An OH upgrade alone does not provide the proposed isolation,
lifecycle integration or full Play compatibility.

Subsequent partial implementation and board probes are recorded in the
[November 14 corpus progress report](hk-top1000-progress-20261114.md). That newer
work does not establish completion of the entire architecture or change this
estimate into an OH 7.0 validation result.

The existing [full-build gates](../full-build-gaps.json) remain the authority for
source-closure claims. Successful component compilation, application launch,
visible rendering and complete end-to-end acceptance are separate milestones.

## Initial investigation and acceptance

Allocate **3–5 engineering days within the estimate** to:

1. Confirm an OH 7.0 firmware/BSP for the exact board, including graphics and
   required peripherals, and pin its matching platform sources.
2. Freeze the OH 6.1 payload, source revisions, APK versions and actually passing
   application flows. Record known failures as baseline limitations.
3. Rebuild the native bridge against OH 7.0; inventory missing symbols, changed
   callbacks, generated headers and hardcoded IPC formats.
4. On an OH 7.0 test device, exercise one representative APK through launch,
   first frame, touch and text input, foreground/background and process exit.
5. Produce an updated task list and estimate based on measured build/runtime
   failures and board availability.

Migration acceptance should replay the frozen passing flows with the same APK
versions, including existing Play-services flows, graphics, input, audio and
network behavior. Compare launch time, memory, CPU and frame behavior under the
same workload. Measure energy on suitable hardware; the current board's dummy
battery is not evidence of phone battery life. Source and deployed-payload
provenance must accompany the results. No performance improvement or complete
Google compatibility is implied by the version upgrade.
