# Lightjack laboratory installer and loader

Added 2026-10-21. These separate build profiles reuse the upstream wireless installation method and loader. They compile and their generated images have been inspected. **Neither profile has been tested on physical hardware.** They are not a validated flashing release.

## Two different processors

| Artifact | Runs on | Role |
| --- | --- | --- |
| `loader/wyze_loader.bin` | ESP32-C3 inside a compatible Wyze bulb | Recovery, backup, and application management |
| `installer/lightjack_installer.bin` | Separate ESP32-S3 development board | Wireless installation aid containing the C3 loader |
| Installer bootloader and partition table | The same ESP32-S3 board | Startup and flash layout for the installation aid |

The shopping-list Freenove ESP32-S3 is the installation aid. Verify the received board, its flash type, USB connection and chip revision before writing it. The profile uses a 4 MiB DIO/40 MHz flash layout and no PSRAM; it does not require or initialize all 16 MiB of a larger module. Successful compilation does not prove board compatibility. Never interchange the S3 and C3 images or write the installer partition table to a bulb.

## Preserve settings before backup

The original loader calls `nvs_flash_init()` and erases its NVS partition when initialization reports no free pages or an incompatible version. The separate `LIGHTJACK_LOADER_POC` profile omits that startup initialization/erase block. It sets Wi-Fi NVS use to zero, selects RAM storage for Wi-Fi settings, and disables persistent PHY calibration. The pinned SDK performs full radio calibration at boot when persistence is disabled.

This removes the identified loader erase fallback. It does not prove that all flash remains unchanged on real hardware. Wireless installation still writes an application slot and OTA selection, and entering factory mode can change stock settings. The loader still has its original write and boot-selection endpoints; it is not a read-only firmware. Use it on an isolated laboratory network. Its AP and HTTP interface remain unauthenticated.

The original `src/wyze-loader` build keeps its previous NVS behavior. The installer can accept a separate built payload without overwriting the upstream `src/wyze-hijack-ap/payload.bin`. The upstream installation protocol is unchanged, including its automatic installation trigger when a compatible bulb joins. Keep the installer powered off until the intended test unit and installation session are ready.

## Build without flashing

Use [ESP-IDF v6.1](https://docs.espressif.com/projects/esp-idf/en/v6.1/esp32s3/get-started/index.html), pinned to commit `fff9895c82d744c7237be8847347bdd1b07c6643`, with its recommended C3 and S3 toolchains. Activate that SDK environment first. From this repository's root:

```sh
python scripts/build_lightjack_installer.py --output ../lightjack-installer-build
```

The script checks the SDK commit, uses a dedicated output directory outside the checkout, builds the C3 loader, copies that completed application into its own payload directory, and builds the S3 installer with that payload. It checks both application sizes and requires exactly one byte-for-byte copy of the C3 image in the S3 image. It never invokes a flash, erase, serial-port or network-install command. An existing output directory is accepted only when its marker identifies this source checkout and SDK commit. It does not delete previous build directories.

The two profiles use separate generated SDK configurations in their build directories. Their project names are `wyze_loader`, required by the Lightjack recovery check, and `lightjack_installer`. Build timestamps are embedded, so later builds can have different hashes even with the same source.

## Recorded image checks

| Image | Bytes | Target revision range | Application slot |
| --- | ---: | --- | ---: |
| C3 loader | 818,240 | C3 v0.3 through v1.99 | 1,966,080 bytes |
| S3 installer | 1,529,552 | S3 v0.0 through v0.99 | 3,145,728 bytes |

The image headers select DIO, 40 MHz and 4 MiB. esptool verified each application and the S3 bootloader checksum and appended SHA256. The compiled partition tables matched the corresponding source CSVs, including their MD5 records. The C3 object was built with `LIGHTJACK_LOADER_POC=1`, contains a Wi-Fi RAM-storage call, and has no reference to `nvs_flash_init` or `nvs_flash_erase`. Final startup disassembly was inspected. These are build and static inspection results, not runtime preservation evidence.

Exact hashes, source identities and limitations are recorded in [verification results](../verification/lightjack-installer-results.json). The legacy upstream I2C driver still produces the SDK deprecation warning; it has not been replaced as part of this profile.

## Arrival session

1. Confirm the received S3 board and bulb model/revision. Keep a second bulb stock. Do not assume an image's revision requirement establishes the actual chip revision.
2. Validate the S3 board's connection and image selection before flashing it. The S3 layout uses bootloader offset `0x0`, partition-table offset `0x8000` and installer application offset `0x10000`. These offsets are for the installation board only.
3. Test the wireless method on the intended bulb in an isolated session. Record success or failure without assuming a stock firmware revision is compatible.
4. After the loader starts, verify a private post-loader snapshot before uploading a Lightjack application. The [backup-tool draft](https://github.com/p1r473/wyze-bulb-color-pwned/pull/1) checks two full reads and rejects incomplete downloads. The snapshot is not untouched factory firmware.
5. Verify recovery, normal lighting, radio stability and actual settings preservation on the bulb. A reliable backup and a compiled image do not substitute for a successful recovery test.

New integration files use the existing MIT license. Upstream source and notices are retained.
