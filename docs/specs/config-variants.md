# Edition and Feature Profile Contract

This contract governs the public Lite/Standard profiles and the stable channel
identity used to hand subscriber delivery to the private system.

- `CFG-01`: `bomana.editions` MUST be the single authority for canonical
  channel names, access class, feature policy, and public-build eligibility.
- `CFG-02`: The canonical channels MUST remain `Lite`, `Standard`, and
  `Enhanced`; Lite and Standard are public, while Enhanced is subscriber-only.
- `CFG-03`: The public source profile MUST default to Standard.
- `CFG-04`: Public profiles MUST use the shared configuration schema and MUST
  apply compile-time feature limits before persisted preferences.
- `CFG-05`: Unknown channel names MUST fail closed.
- `CFG-06`: Lite MUST enable the timer and minimal desktop controls while
  disabling navigation zones, airfields, fuel, and subscriber features.
- `CFG-07`: Standard MUST enable the public navigation, airfield, fuel,
  checklist, speed, and advanced-settings features.
- `CFG-08`: Lite and Standard MUST disable subscriber Strike Prediction and Web
  Cockpit capabilities regardless of saved preferences.
- `CFG-09`: A disabled feature MUST NOT create its runtime service or UI surface.
- `CFG-10`: Switching public profiles MUST NOT require a second user-config
  file or mutate the working-tree source.
- `CFG-11`: The artifact profile MUST be rendered into build staging, leaving
  the checked-out Standard source profile byte-for-byte unchanged.
- `CFG-12`: An ambiguous or duplicated edition declaration MUST fail the build.
- `CFG-13`: The public builder MUST accept only Lite and Standard App variants.
- `CFG-14`: Public CI MUST contain no Enhanced App matrix entry or artifact
  upload.
- `CFG-15`: Public archives MUST exclude every path classified as subscriber
  closure by `bomana.release_closure`.
- `CFG-16`: The universal Launcher MAY retain inactive subscriber preferences
  for compatibility, but Lite/Standard launch MUST NOT start subscriber
  services or contact CheemsPay.

Tests MUST verify both the policy module and generated archive contents. A build
flag alone is not evidence that subscriber implementation is absent.
