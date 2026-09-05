# A2HLAB full-source reproduction workstream

Target: https://github.com/a2hlab (not A2OH).
Profile: `toutiao-aosp15-oh61-legacy`; separate from the existing AOSP16 work.

The user requires a full reproducible repository/build setup. Creation of private
repos and publishing scoped sources is authorized; existing projects, private
app data and the accepted device runtime must remain intact. No successful
source/component gate implies the full stack or live Toutiao gate passed.

## Completion gates

- [x] Publish source-only Westlake and ART build repos, upstream-ancestry ART mirror.
- [x] Lock and fetch source/SDK/toolchain inputs for native, apps and ART profiles.
- [x] Build public-SDK native helpers twice in fresh distinct roots; compare hashes.
- [x] Build ART and runtime boundary twice without historical objects or boundary DSO.
- [x] Rebuild V1 Restool and host/Pinyin packages from source; identical unsigned HAPs.
- [x] Commit upstream dependency snapshots and actual SDK/compiler inputs under a2hlab.
- [x] Preserve missing local graphics sources/overlays with exact content inventories.
- [ ] Close the complete framework/graphics source and deployed-provider manifest.
- [ ] Rebuild host dex2oat, framework/JARs and boot images without candidate04 inputs.
- [ ] Rebuild bridge/HWUI and host/Pinyin/control packages from declared sources.
- [ ] Prove two independent full builds have identical unsigned payloads.
- [ ] Fresh board/Toutiao Chinese-search/scroll acceptance and matched native tests.

Initial audit: the existing stack depends on a frozen framework/HWUI baseline,
mixed OH revisions/local headers, a third clean ART checkout, generated Ninja
include flags and local compatibility sysroots. The implementation must expose
and remove these assumptions, not relabel an archived binary bundle as a build.

Repositories published: `westlake`, `art-build`, `aosp-art-15`, `manifest`, 16
`dep-*` repositories, `toolchains` and `legacy-runtime-sources`.
Only newly created private repositories are written; no existing main branch,
repository visibility, organization policy or device state is changed.
