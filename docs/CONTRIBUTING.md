# Contributing

Use Node.js 22.23.4, pnpm 11.3.0, Go 1.27.3 and PowerShell 7. These Node.js and Go versions include the October 2026 security fixes. Run `pnpm --dir frontend install --frozen-lockfile`, `pnpm --dir frontend check`, `go -C native/telemetry_gateway test ./...` and `go -C native/telemetry_gateway vet ./...`.

For the independent minimal Windows timer/navigation EXE, use
`pwsh -NoProfile -File tools/build_basic_desktop.ps1 -Version <version>` on clean
committed source. See [Basic Desktop](../native/telemetry_gateway/cmd/bomana_basic/README.md).

Report a bug or propose a patch in this public repository. Accepted changes are incorporated in the single maintained source, then exported here. Public `main` is generated; do not merge independent changes there or create a separate official release pipeline. Run the complete commands above locally. No hosted workflow is generated, and public PRs are never automatically executed on the maintainer's private runner. The trusted private export independently builds and audits this public source before publishing it.

Read the [edition boundary](specs/public-editions.md). Do not reintroduce the old Python App / desktop Launcher or Enhanced implementation. Historical releases remain accessible; current users should download through the [online Launcher](https://bomana.ruikang.wang/launcher/).
