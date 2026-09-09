# Bomana public context

**Basic Desktop** is the separate minimal native Windows surface: only a cycle
timer and official bombing-zone/airfield Basic Navigation. It does not include
the complete Standard Edition, Web assets or an Enhanced calculation module.

**App Web** is the browser application distributed by the online **Launcher**. **Bridge** is the local Go process that relays official 8111 observations and provides local resource storage and mobile pairing transport. **Public Runtime** owns sortie lifecycle, timer, Basic Navigation, speed and fuel estimates. **Basic Navigation** includes official zones and airfields only. **Mobile Pairing** grants short-lived access to one local Bridge; Standard pairing requires no account. **Enhanced** is a separately authorized private extension.

The public tree is a generated source distribution, not a separate development trunk. The same Public Runtime and Web entry are used in maintained production Lite / Standard builds. A public source sync is not a production release. Formal Web / Bridge version metadata in the online Launcher identifies production downloads; old GitHub release records remain historical.
